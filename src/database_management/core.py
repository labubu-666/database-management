import logging
import os
import shutil
import signal
import subprocess
import threading
from datetime import UTC, datetime

import psycopg2

from .backends import BackupArtifact, BaseBackend
from .config import Settings

logger = logging.getLogger(__name__)

# Shutdown coordination event
shutdown_event = threading.Event()


def handle_signal(signum, frame):
    sig_name = signal.Signals(signum).name
    logger.info(f"Received {sig_name}. Initiating graceful shutdown...")
    shutdown_event.set()


def register_signal_handlers() -> None:
    # SIGTERM (Docker stop) and SIGINT (Ctrl+C)
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)


def _connect(settings: Settings):
    return psycopg2.connect(
        host=settings.host,
        port=settings.port,
        dbname=settings.dbname,
        user=settings.user,
        password=settings.password.get_secret_value(),
        connect_timeout=3,
    )


def check_pg_dump() -> bool:
    pg_dump_path = shutil.which("pg_dump")
    if pg_dump_path is None:
        logger.error(
            "pg_dump binary not found in PATH. Install PostgreSQL client tools and retry."
        )
        return False

    logger.info(f"Found pg_dump: {pg_dump_path}")
    return True


def check_connection(settings: Settings) -> bool:
    conn = None
    try:
        conn = _connect(settings)
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            pg_version = cur.fetchone()[0]

        version_summary = f"{pg_version.split()[0]} {pg_version.split()[1]}"
        logger.info(f"Healthcheck OK: {settings.host} ({version_summary})")
        return True

    except Exception as e:  # noqa: BLE001 - a failed probe must not crash the daemon
        logger.error(f"Healthcheck failed: {e}")
        return False

    finally:
        if conn is not None and not conn.closed:
            conn.close()


def list_databases(settings: Settings) -> list[str]:
    conn = None
    try:
        conn = _connect(settings)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT datname FROM pg_database "
                "WHERE datistemplate = false AND datallowconn = true "
                "ORDER BY datname;"
            )
            return [row[0] for row in cur.fetchall()]

    except Exception as e:  # noqa: BLE001 - a failed query must not crash the daemon
        logger.error(f"Listing databases failed: {e}")
        return []

    finally:
        if conn is not None and not conn.closed:
            conn.close()


def dump_database(
    settings: Settings, targets: list[BaseBackend], dbname: str, timestamp: str
) -> bool:
    """Dump one database to staging, then save it to every target.
    Returns True only if every target stored the dump."""
    # ISO-8601 basic timestamp (YYYYMMDDTHHMMSS) keeps filenames sortable
    output_path = settings.staging_dir / f"{dbname}_{timestamp}.dump.partial"
    settings.staging_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "pg_dump",
        "--format=custom",  # compressed, restorable with pg_restore
        "--file",
        str(output_path),
        "--host",
        settings.host,
        "--port",
        str(settings.port),
        "--username",
        settings.user,
        "--dbname",
        dbname,
    ]
    env = {**os.environ, "PGPASSWORD": settings.password.get_secret_value()}

    try:
        try:
            result = subprocess.run(
                cmd, check=False, env=env, capture_output=True, text=True
            )
        except OSError as e:
            logger.error(f"Failed to run pg_dump for '{dbname}': {e}")
            return False

        if result.returncode != 0:
            logger.error(f"pg_dump failed for '{dbname}': {result.stderr.strip()}")
            return False

        artifact = BackupArtifact(dbname, timestamp, output_path)
        # Every target gets the dump, even if an earlier one failed
        results = [target.save(artifact) for target in targets]
        return all(results)
    finally:
        # Never leave a partial or staged dump behind
        output_path.unlink(missing_ok=True)


def perform_backup(settings: Settings, targets: list[BaseBackend]) -> tuple[int, int]:
    """Dump every database once and save to all targets. Returns (succeeded, total)."""
    databases = list_databases(settings)
    logger.info(f"Found {len(databases)} database(s): {', '.join(databases)}")
    if not databases:
        return 0, 0

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    succeeded = 0
    for dbname in databases:
        if shutdown_event.is_set():
            logger.info("Shutdown requested; stopping remaining dumps.")
            break
        if dump_database(settings, targets, dbname, timestamp):
            succeeded += 1

    logger.info(
        f"Backup cycle finished: {succeeded}/{len(databases)} database(s) dumped."
    )
    return succeeded, len(databases)


def run_automated_loop(settings: Settings, targets: list[BaseBackend]) -> None:
    """Back up every `interval_seconds` until SIGTERM/SIGINT is received."""
    register_signal_handlers()
    logger.info(
        f"Starting daemon... Probing {settings.host}:{settings.port} "
        f"every {settings.interval_seconds}s"
    )

    while not shutdown_event.is_set():
        if check_connection(settings):
            perform_backup(settings, targets)
        else:
            logger.warning("Skipping backup: database not reachable.")

        # Waits for INTERVAL seconds, OR wakes up immediately if shutdown_event is triggered
        shutdown_event.wait(timeout=settings.interval_seconds)

    logger.info("Cleanup complete. Exiting gracefully.")
