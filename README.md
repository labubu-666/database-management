# database-management

PostgreSQL backup tool built on `pg_dump`. Every database is dumped once (custom format) and the same dump is sent to each configured target.

## Usage

```bash
# one-off backup to a local folder
uv run database-management backup --target file:///var/backups/pg

# several targets at once (repeat --target)
uv run database-management backup --target file:///var/backups/pg --target file:///mnt/nas/pg

# repeated every 3600 seconds (1 hour) until stopped
uv run database-management automated-backup --target file:///var/backups/pg --interval 3600
```

Targets can also come from the environment (comma or space separated). `--target` overrides it:

```bash
DATABASE_MANAGEMENT_TARGETS=file:///var/backups/pg,file:///mnt/nas/pg
```

A target is a URI. The scheme picks the backend. Supported today: `file://` (absolute path only).

## Configuration

| Variable                  | Default                         | Purpose                                      |
| ------------------------- | ------------------------------- | -------------------------------------------- |
| `POSTGRES_HOST`           | `postgres`                      | Server to back up                            |
| `POSTGRES_PORT`           | `5432`                          | Server port                                  |
| `POSTGRES_DB`             | `postgres`                      | Database used for the connection healthcheck |
| `POSTGRES_USER`           | `postgres`                      | User                                         |
| `POSTGRES_PASSWORD`       | `postgres`                      | Password                                     |
| `DATABASE_MANAGEMENT_TARGETS`          | _(none, required)_              | Target URIs, comma or space separated        |
| `DATABASE_MANAGEMENT_INTERVAL_SECONDS` | `3600`                          | Seconds between cycles in `automated-backup` |
| `DATABASE_MANAGEMENT_STAGING_DIR`      | `<system temp>/postgres-backup` | Where `pg_dump` writes before storing        |
| `DATABASE_MANAGEMENT_KEEP`             | `7`                             | Newest backups kept per database, per target |

Values can be set in a `.env` file in the working directory, or as environment variables. Environment variables take precedence over `.env`, and CLI flags take precedence over both. Invalid values (for example `DATABASE_MANAGEMENT_KEEP=0`) stop the command with exit code 1.

At startup, `backup` and `automated-backup` log the effective configuration. The password is always masked.

Dumps are named `<database>_<YYYYMMDDTHHMMSSZ>.dump`. A database counts as backed up only if every target stored it, and the command exits with code 1 otherwise.

## Adding a backend

Subclass `BaseBackend` in `src/database_management/backends/`, implement `store()` (and optionally `check()`), set `schemes`, and register the class in `backends/__init__.py`.

# Docker

    docker build . --tag database-management:latest
    docker run --rm --env-file .env --network host -v "$PWD/backups:/app/backups" database-management:latest database-management backup

The container user has UID/GID 1000 by default. The host backup directory must be writable by that UID. Override at build time with `--build-arg APP_UID=<uid> --build-arg APP_GID=<gid>` if needed.

