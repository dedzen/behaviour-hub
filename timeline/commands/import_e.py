from pathlib import Path
import urllib.error
import urllib.request

import typer

from timeline.ingest.android import import_android_unlock_jsonl
from timeline.ingest.embed import import_embed_csv
from timeline.storage.repository import SQLiteRepository

app = typer.Typer(help="Import data into the database")

ANDROID_UNLOCK_PATH = Path("data/android/unlock-events.jsonl")


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
        "active_screen",
        "--strategy",
        help="Interpret phone activity as 'active_screen', 'screen', or 'keyguard'.",
    ),
):
    """Import Android unlock/screen JSONL events."""

    if strategy not in {"active_screen", "screen", "keyguard"}:
        raise typer.BadParameter("strategy must be 'active_screen', 'screen', or 'keyguard'")

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
    if result.dropped_short_chunks:
        typer.echo(f"Dropped {result.dropped_short_chunks} chunks shorter than 20 seconds.")
    if result.anomalies:
        typer.echo(f"Reported {len(result.anomalies)} transition anomalies.")
    if result.unknown_time_seconds:
        typer.echo(f"Reported {result.unknown_time_seconds:.3f} seconds of unknown state.")
    if skipped:
        typer.echo(f"Skipped {skipped} duplicates.")


@app.command("android-download")
def download_android(
    address: str = typer.Argument(
        ...,
        help="Android device IP or host:port.",
    ),
    output: Path = typer.Option(
        ANDROID_UNLOCK_PATH,
        "--output",
        "-o",
        help="Where to save the downloaded JSONL file.",
    ),
):
    """Download Android unlock/screen JSONL events from the device."""

    data = _download_device_file(address, "/unlock-events.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    typer.echo(f"Downloaded {len(data)} bytes to {output}")


@app.command("android-clear")
def clear_android(
    address: str = typer.Argument(
        ...,
        help="Android device IP or host:port.",
    ),
):
    """Clear Android unlock/screen events on the device."""

    _delete_device_file(address, "/unlock-events.jsonl")
    typer.echo(f"Cleared Android unlock events on {address.strip()}")


def _download_device_file(address: str, path: str) -> bytes:
    address = address.strip()
    if not address:
        raise typer.BadParameter("address is required")

    url = f"http://{address}{path}"
    try:
        with urllib.request.urlopen(url, timeout=10.0) as response:
            return response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to download {path} from {address}: {exc}") from exc


def _delete_device_file(address: str, path: str) -> None:
    address = address.strip()
    if not address:
        raise typer.BadParameter("address is required")

    url = f"http://{address}{path}"
    request = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(request, timeout=10.0) as response:
            response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to clear {path} on {address}: {exc}") from exc
