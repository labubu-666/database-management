import logging
from pathlib import Path
from unittest import mock

import pytest

from database_management.backends import BackupArtifact, FileBackend, backend_for_uri
from database_management.backends.base import DEFAULT_KEEP


def write_dump(path: Path, content: bytes = b"dump-bytes") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def timestamp(day: int) -> str:
    return f"202401{day:02d}T000000Z"


@pytest.fixture
def target_dir(tmp_path):
    return tmp_path / "out"


@pytest.fixture
def make_backend(target_dir):
    def factory(keep: int = DEFAULT_KEEP) -> FileBackend:
        return backend_for_uri(f"file://{target_dir}", keep)

    return factory


@pytest.fixture
def backend(make_backend):
    return make_backend()


@pytest.fixture
def make_backups(target_dir):
    """Create finished backups of one database, one per day, oldest first."""

    def factory(dbname: str, count: int) -> list[str]:
        names = []
        for day in range(1, count + 1):
            name = f"{dbname}_{timestamp(day)}.dump"
            write_dump(target_dir / name)
            names.append(name)
        return names

    return factory


@pytest.fixture
def staged(tmp_path):
    return write_dump(tmp_path / "staging" / "db_ts.dump.partial")


def remaining(target_dir: Path) -> list[str]:
    return sorted(p.name for p in target_dir.iterdir())


def test_backend_for_uri_returns_file_backend(target_dir):
    backend = backend_for_uri(f"file://{target_dir}")
    assert isinstance(backend, FileBackend)
    assert backend.directory == target_dir


def test_file_check_rejects_relative_path():
    backend = backend_for_uri("file://relative/path")
    assert backend.check() is False


def test_file_check_creates_directory(target_dir, backend):
    assert backend.check() is True
    assert target_dir.is_dir()


def test_file_store_writes_final_file_without_partial(target_dir, backend, staged):
    assert backend.save(BackupArtifact("db", "ts", staged)) is True

    assert (target_dir / "db_ts.dump").read_bytes() == b"dump-bytes"
    assert not (target_dir / "db_ts.dump.partial").exists()


def test_default_keep_is_seven(target_dir):
    assert DEFAULT_KEEP == 7
    assert backend_for_uri(f"file://{target_dir}").keep == 7


@pytest.mark.parametrize("keep", [0, -1])
def test_keep_below_one_is_rejected(target_dir, keep):
    with pytest.raises(ValueError, match="keep must be at least 1"):
        backend_for_uri(f"file://{target_dir}", keep)


@pytest.mark.parametrize(
    ("keep", "existing"),
    [(7, 3), (7, 7), (7, 10), (1, 5), (3, 4)],
)
def test_prune_keeps_only_newest(
    make_backend, make_backups, target_dir, keep, existing
):
    names = make_backups("db", existing)

    make_backend(keep).prune("db")

    assert remaining(target_dir) == sorted(names[-keep:])


def test_prune_only_touches_the_named_database(make_backend, make_backups, target_dir):
    make_backups("db", 10)
    other = make_backups("db_test", 10)

    make_backend(keep=7).prune("db")

    assert sum(n.startswith("db_test_") for n in remaining(target_dir)) == 10
    assert all(name in remaining(target_dir) for name in other)


@pytest.mark.parametrize(
    "extra",
    ["db_20240105T000000Z.dump.partial", "notes.txt", "db_backup.dump"],
)
def test_prune_ignores_partial_and_unrelated_files(
    make_backend, make_backups, target_dir, extra
):
    make_backups("db", 3)
    write_dump(target_dir / extra)

    make_backend(keep=1).prune("db")

    assert extra in remaining(target_dir)


def test_list_backups_returns_empty_for_missing_directory(backend):
    assert backend.list_backups("db") == []


def test_prune_missing_directory_returns_empty(backend):
    assert backend.prune("db") == []


def test_save_prunes_old_backups_after_storing(
    make_backend, make_backups, target_dir, staged
):
    make_backups("db", 3)

    ok = make_backend(keep=2).save(BackupArtifact("db", timestamp(4), staged))

    assert ok is True
    assert remaining(target_dir) == [
        f"db_{timestamp(3)}.dump",
        f"db_{timestamp(4)}.dump",
    ]


def test_failed_store_leaves_existing_backups_alone(
    make_backend, make_backups, target_dir, tmp_path
):
    names = make_backups("db", 3)
    missing = tmp_path / "missing.partial"

    ok = make_backend(keep=1).save(BackupArtifact("db", timestamp(4), missing))

    assert ok is False
    assert remaining(target_dir) == sorted(names)


def test_delete_failure_is_logged_and_skipped(make_backend, make_backups, caplog):
    make_backups("db", 3)

    with (
        mock.patch.object(FileBackend, "delete", side_effect=OSError("denied")),
        caplog.at_level(logging.ERROR),
    ):
        deleted = make_backend(keep=1).prune("db")

    assert deleted == []
    assert "Could not delete" in caplog.text
