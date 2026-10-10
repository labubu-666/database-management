import logging
import os
import re
import shutil
from pathlib import Path
from urllib.request import url2pathname

from .base import BackupArtifact, BaseBackend

logger = logging.getLogger(__name__)


class FileBackend(BaseBackend):
    """Writes dumps to a local directory: file:///absolute/path."""

    schemes = ("file",)

    def __init__(self, uri, parsed, keep) -> None:
        super().__init__(uri, parsed, keep)
        self.directory = Path(url2pathname(parsed.path))

    def check(self) -> bool:
        if not self.parsed.path.startswith("/"):
            logger.error(f"file target must be an absolute path: {self.uri}")
            return False
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Cannot create {self.directory}: {e}")
            return False
        if not os.access(self.directory, os.W_OK):
            logger.error(f"Directory is not writable: {self.directory}")
            return False
        return True

    def store(self, artifact: BackupArtifact) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        dest = self.directory / artifact.name
        partial = dest.with_name(dest.name + ".partial")
        # Copy first, then rename, so the final name only ever points at a complete file
        shutil.copy2(artifact.local_path, partial)
        partial.replace(dest)
        return str(dest)

    def list_backups(self, dbname: str) -> list[str]:
        if not self.directory.is_dir():
            return []
        # Exact pattern: skips .partial files, other databases such as "db_test",
        # and anything else sitting in the folder
        pattern = re.compile(re.escape(dbname) + r"_\d{8}T\d{6}Z\.dump")
        return [
            p.name
            for p in self.directory.iterdir()
            if p.is_file() and pattern.fullmatch(p.name)
        ]

    def delete(self, name: str) -> None:
        (self.directory / name).unlink(missing_ok=True)
