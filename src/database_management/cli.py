import logging
import sys

import click
from pydantic import ValidationError

from . import core
from .backends import BaseBackend, parse_targets
from .config import Settings, load_settings


def _load_settings(
    targets: tuple[str, ...],
    interval: int | None = None,
    keep: int | None = None,
) -> Settings:
    overrides = {}
    if targets:
        overrides["targets"] = targets
    if interval is not None:
        overrides["interval_seconds"] = interval
    if keep is not None:
        overrides["keep"] = keep
    try:
        return load_settings(**overrides)
    except ValidationError as e:
        click.echo(f"Invalid configuration:\n{e}", err=True)
        sys.exit(1)


def _prepare_targets(settings: Settings) -> list[BaseBackend]:
    """Parse and preflight every target. Exits with code 1 on any problem."""
    if not settings.targets:
        click.echo(
            "No targets given. Use --target file:///path or set BACKUP_TARGETS.",
            err=True,
        )
        sys.exit(1)
    try:
        targets = parse_targets(settings.targets, settings.keep)
    except ValueError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    if not all(target.check() for target in targets):
        sys.exit(1)
    return targets


@click.group()
def main() -> None:
    """PostgreSQL backup tool built on pg_dump."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


target_option = click.option(
    "--target",
    "targets",
    multiple=True,
    help="Backup destination URI, e.g. file:///var/backups/pg. Repeat for several. "
    "Overrides BACKUP_TARGETS.",
)


keep_option = click.option(
    "--keep",
    type=click.IntRange(min=1),
    default=None,
    help="Newest backups to keep per database, per target. "
    "Overrides BACKUP_KEEP (default: 7).",
)


@main.command()
@target_option
@keep_option
def backup(targets: tuple[str, ...], keep: int | None) -> None:
    """Run a single backup of every database and exit."""
    settings = _load_settings(targets, keep=keep)
    settings.log_summary(exclude=frozenset({"interval_seconds"}))
    backends = _prepare_targets(settings)

    if not core.check_pg_dump():
        sys.exit(1)
    if not core.check_connection(settings):
        sys.exit(1)

    succeeded, total = core.perform_backup(settings, backends)
    if total == 0 or succeeded != total:
        sys.exit(1)


@main.command("automated-backup")
@target_option
@click.option(
    "--interval",
    type=click.IntRange(min=1),
    default=None,
    help="Seconds between backup cycles. Overrides BACKUP_INTERVAL_SECONDS (default: 3600).",
)
@keep_option
def automated_backup(
    targets: tuple[str, ...], interval: int | None, keep: int | None
) -> None:
    """Run backups repeatedly on an interval until stopped (SIGTERM/SIGINT)."""
    settings = _load_settings(targets, interval, keep)
    settings.log_summary()
    backends = _prepare_targets(settings)

    if not core.check_pg_dump():
        sys.exit(1)

    core.run_automated_loop(settings, backends)
