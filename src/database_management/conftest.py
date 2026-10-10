import pytest

CONFIG_VARS = [
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "DATABASE_MANAGEMENT_TARGETS",
    "DATABASE_MANAGEMENT_INTERVAL_SECONDS",
    "DATABASE_MANAGEMENT_STAGING_DIR",
    "DATABASE_MANAGEMENT_KEEP",
]


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Keep tests independent of the host environment and the project's .env."""
    for name in CONFIG_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path
