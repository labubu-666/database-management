from urllib.parse import urlparse

from .base import DEFAULT_KEEP, BackupArtifact, BaseBackend
from .file_backend import FileBackend

__all__ = [
    "DEFAULT_KEEP",
    "BackupArtifact",
    "BaseBackend",
    "FileBackend",
    "backend_for_uri",
    "parse_targets",
]

_REGISTRY: dict[str, type[BaseBackend]] = {}


def register(cls: type[BaseBackend]) -> type[BaseBackend]:
    for scheme in cls.schemes:
        _REGISTRY[scheme] = cls
    return cls


register(FileBackend)


def supported_schemes() -> list[str]:
    return sorted(_REGISTRY)


def backend_for_uri(uri: str, keep: int = DEFAULT_KEEP) -> BaseBackend:
    """Return a backend instance for a target URI. Raises ValueError if unsupported."""
    scheme = urlparse(uri).scheme
    cls = _REGISTRY.get(scheme)
    if cls is None:
        supported = ", ".join(f"{s}://" for s in supported_schemes())
        raise ValueError(f"Unsupported target '{uri}'; supported schemes: {supported}")
    return cls.from_uri(uri, keep)


def parse_targets(
    uris: list[str] | tuple[str, ...], keep: int = DEFAULT_KEEP
) -> list[BaseBackend]:
    """Build one backend per unique target URI, preserving the given order."""
    seen: set[str] = set()
    backends: list[BaseBackend] = []
    for uri in uris:
        if uri in seen:
            continue
        seen.add(uri)
        backends.append(backend_for_uri(uri, keep))
    return backends
