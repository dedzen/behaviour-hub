import typer
from timeline.storage.repository import SQLiteRepository
from timeline.api.timeline import Timeline
from timeline.domain.enums import DeviceSource
from pathlib import Path
from timeline.domain.models import Event
from datetime import datetime

app = typer.Typer(help="Manage raw events.")
@app.command("list")
def list_events(
    db: str = typer.Option("timeline.db"),

    day: str | None = typer.Option(None),
    week: str | None = typer.Option(None),
    month: str | None = typer.Option(None),
    year: str | None = typer.Option(None),

    category: str | None = typer.Option(None),
    activity: str | None = typer.Option(None),
    source: DeviceSource | None = typer.Option(None),
):
    repo = SQLiteRepository(Path(db))
    timeline = Timeline(repo)

    

    #
    # Time filter
    #

    if day:
        timeline = timeline.day(day)

    elif week:
        timeline = timeline.week(week)

    elif month:
        timeline = timeline.month(month)

    elif year:
        timeline = timeline.year(year)

    #
    # Attribute filters
    #

    if category:
        timeline = timeline.category(category)

    if activity:
        timeline = timeline.activity(activity)

    if source:
        timeline = timeline.source(source)

    events = timeline.events()

    typer.echo(
        f"{'ID':>4} {'Timestamp':19} {'Kind':16} {'Category':15} Name"
    )
    typer.echo("-" * 75)

    for event in events:
        typer.echo(
            f"{event.id:4} "
            f"{event.timestamp:%Y-%m-%d %H:%M:%S} "
            f"{event.event_kind.value:16} "
            f"{(event.category or ''):15} "
            f"{event.name}"
        )
@app.command("delete")
def delete_event(
    id: int,
    db: str = typer.Option("timeline.db"),
):
    repo = SQLiteRepository(Path(db))

    event = repo.get(Event, id)

    if event is None:
        typer.echo("Event not found.")
        raise typer.Exit(1)

    typer.echo(event)

    if not typer.confirm("Delete event?"):
        raise typer.Exit()

    repo.delete(Event, id)
    repo.commit()
    repo.close()

    typer.echo("Deleted.")

@app.command("edit")
def edit_event(
    id: int,
    db: str = typer.Option("timeline.db"),
):

    repo = SQLiteRepository(Path(db))

    event = repo.get(Event, id)

    if event is None:
        typer.echo("Event not found.")
        raise typer.Exit(1)

    event.timestamp = datetime.fromisoformat(typer.prompt(
        "Timestamp",
        default=str(event.timestamp),
    ))

    event.category = typer.prompt(
        "Category",
        default=event.category,
    )

    event.name = typer.prompt(
        "Name",
        default=event.name,
    )

    repo.update(event)
    repo.commit()
    repo.close()

    typer.echo("Updated.")