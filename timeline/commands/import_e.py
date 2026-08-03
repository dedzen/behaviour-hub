from pathlib import Path

import typer

from timeline.ingest.android import import_android_unlock_jsonl
from timeline.ingest.embed import import_embed_csv
from timeline.storage.repository import SQLiteRepository

app = typer.Typer(help="Import data into the database")


@app.command("embed")
def import_embed(
    csv: Path,
    database: Path = Path("timeline.db"),
):
    """Import an embed CSV log."""

    with SQLiteRepository(database) as repo:
        repo.ensure_schema()

        events = import_embed_csv(csv)
        inserted = 0

        for event in events:
            inserted += int(repo.insert_event(event))

    skipped = len(events) - inserted
    typer.echo(f"Imported {inserted} events.")
    if skipped:
        typer.echo(f"Skipped {skipped} duplicates.")


@app.command("android")
def import_android(
    jsonl: Path,
    database: Path = Path("timeline.db"),
    strategy: str = typer.Option(
        "keyguard",
        "--strategy",
        help="Interpret phone activity as either 'screen' or 'keyguard'.",
    ),
):
    """Import Android unlock/screen JSONL events."""

    if strategy not in {"screen", "keyguard"}:
        raise typer.BadParameter("strategy must be 'screen' or 'keyguard'")

    with SQLiteRepository(database) as repo:
        repo.ensure_schema()

        result = import_android_unlock_jsonl(jsonl, strategy=strategy) # type: ignore[arg-type]
        inserted = 0

        for event in result.events:
            inserted += int(repo.insert_event(event))

    skipped = len(result.events) - inserted
    typer.echo(f"Imported {inserted} android events using {result.strategy} strategy.")
    if result.ignored_events:
        typer.echo(f"Ignored {result.ignored_events} unrelated events.")
    if result.dropped_orphan_starts:
        typer.echo(f"Dropped {result.dropped_orphan_starts} orphan starts.")
    if skipped:
        typer.echo(f"Skipped {skipped} duplicates.")
