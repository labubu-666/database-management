import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar
from urllib.parse import ParseResult, urlparse

logger = logging.getLogger(__name__)

DEFAULT_KEEP = 7


@dataclass(frozen=True)
class BackupArtifact:
    dbname: str
    timestamp: str
    local_path: Path  # finished dump in the staging area

    @property
    def name(self) -> str:
        return f"{self.dbname}_{self.timestamp}.dump"


class BaseBackend(ABC):
    """A storage destination, addressed by a target URI such as file:///path."""

    schemes: ClassVar[tuple[str, ...]]

    def __init__(self, uri: str, parsed: ParseResult, keep: int = DEFAULT_KEEP) -> None:
        if keep < 1:
            raise ValueError(f"keep must be at least 1, got {keep}")
        self.uri = uri
        self.parsed = parsed
        self.keep = keep

    @classmethod
    def from_uri(cls, uri: str, keep: int = DEFAULT_KEEP) -> "BaseBackend":
        parsed = urlparse(uri)
        return cls(uri, parsed, keep)

    def check(self) -> bool:
        """Preflight check (folder writable, bucket reachable). Default: OK."""
        return True

    def save(self, artifact: BackupArtifact) -> bool:
        """Store the artifact and log the outcome. Never raises."""
        try:
            location = self.store(artifact)
        except Exception as e:  # noqa: BLE001 - one failed target must not stop the others
            logger.error(f"Storing '{artifact.dbname}' to {self.uri} failed: {e}")
            return False
        size_mb = artifact.local_path.stat().st_size / (1024 * 1024)
        logger.info(f"Backed up '{artifact.dbname}' -> {location} ({size_mb:.2f} MB)")
        self.prune(artifact.dbname)
        return True

    @abstractmethod
    def store(self, artifact: BackupArtifact) -> str:
        """Put the dump in its final location and return that location.
        Raise an exception on failure."""

    @abstractmethod
    def list_backups(self, dbname: str) -> list[str]:
        """Return the names of finished backups of one database (any order).
        Raise an exception on failure."""

    @abstractmethod
    def delete(self, name: str) -> None:
        """Remove one finished backup by name. Raise an exception on failure."""

    def prune(self, dbname: str) -> list[str]:
        """Delete all but the newest `keep` backups of one database.
        Returns the names deleted. Never raises."""
        try:
            names = sorted(self.list_backups(dbname))
        except Exception as e:  # noqa: BLE001 - retention must not fail the backup
            logger.error(f"Listing backups of '{dbname}' in {self.uri} failed: {e}")
            return []

        # Names embed a fixed-width UTC timestamp, so sorting puts the oldest first
        deleted: list[str] = []
        for name in names[: -self.keep]:
            try:
                self.delete(name)
            except Exception as e:  # noqa: BLE001 - keep pruning the rest
                logger.error(f"Could not delete {name} from {self.uri}: {e}")
                continue
            deleted.append(name)

        if deleted:
            logger.info(
                f"Pruned {len(deleted)} old backup(s) of '{dbname}' from {self.uri}"
            )
        return deleted

    def __str__(self) -> str:
        return self.uri
