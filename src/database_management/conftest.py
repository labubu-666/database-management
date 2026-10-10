import pytest

CONFIG_VARS = [
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "BACKUP_TARGETS",
    "BACKUP_INTERVAL_SECONDS",
    "BACKUP_STAGING_DIR",
    "BACKUP_KEEP",
]


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Keep tests independent of the host environment and the project's .env."""
    for name in CONFIG_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path
