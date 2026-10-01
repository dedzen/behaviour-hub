from pathlib import Path
import urllib.error
import urllib.request

import typer

from timeline.application.mutations import TimelineMutationService

app = typer.Typer(help="Import data into the database")

ANDROID_UNLOCK_PATH = Path("data/android/unlock-events.jsonl")


@app.command("embed")
def import_embed(
    csv: Path,
    database: Path = Path("timeline.db"),
):
    """Import an embed CSV log."""

    result = TimelineMutationService(database).import_embed(csv)
    typer.echo(result.message + ".")


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

    result = TimelineMutationService(database).import_android(jsonl, strategy)
    typer.echo(result.message + ".")


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
