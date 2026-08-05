from pathlib import Path
import typer


from timeline.commands.import_e import app as import_app
from timeline.commands.chunks import app as chunks_app
from timeline.commands.events_edit import app as events_app
from timeline.commands.export import app as export_app
from timeline.commands.validate import validate




app = typer.Typer(
    help="Behaviour Hub CLI"
)

app.add_typer(import_app, name="import")
app.add_typer(chunks_app, name="chunks")
app.add_typer(events_app, name="events")
app.add_typer(export_app, name="export")
app.command()(validate)
