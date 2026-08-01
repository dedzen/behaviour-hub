from pathlib import Path

import typer

from timeline.domain.interval_builder import IntervalBuilder
from timeline.storage.repository import SQLiteRepository

app = typer.Typer(help="Chunk operations")


@app.command("rebuild")
def rebuild_chunks(
    database: Path = Path("timeline.db"),
):
    """Rebuild all chunks from events."""

    with SQLiteRepository(database) as repo:
        events = repo.load_events()
        chunks, warnings = IntervalBuilder.build(events)
        repo.replace_chunks(chunks)
        
        for warning in warnings:
            typer.echo(f"WARNING: {warning}", err=True)

    typer.echo(f"Generated {len(chunks)} chunks.")