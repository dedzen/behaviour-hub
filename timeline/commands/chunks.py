from pathlib import Path

import typer

from timeline.application.mutations import TimelineMutationService

app = typer.Typer(help="Chunk operations")


@app.command("rebuild")
def rebuild_chunks(
    database: Path = Path("timeline.db"),
):
    """Rebuild all chunks from events."""

    result = TimelineMutationService(database).rebuild_chunks()
    for warning in result.warnings:
        typer.echo(f"WARNING: {warning}", err=True)
    typer.echo(result.message + ".")
