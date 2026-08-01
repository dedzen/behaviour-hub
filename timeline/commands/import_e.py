from pathlib import Path

import typer

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

        for event in events:
            repo.insert_event(event)

    typer.echo(f"Imported {len(events)} events.")