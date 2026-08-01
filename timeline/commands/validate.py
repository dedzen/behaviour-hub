import typer
from pathlib import Path

from timeline.storage.repository import SQLiteRepository
from timeline.validation.validator import Validator
from timeline.validation.issue import Severity




def validate(
    db: str = typer.Option(
        "timeline.db",
        "--db",
        help="SQLite database path.",
    ),
):
    repo = SQLiteRepository(Path(db))

    validator = Validator(repo)
    report = validator.validate()

    if report.valid:
        typer.secho("✓ Database is valid.", fg=typer.colors.GREEN)
    else:
        typer.secho("✗ Validation failed.", fg=typer.colors.RED)

    if not report.issues:
        typer.echo("No issues found.")
        raise typer.Exit()

    typer.echo()

    for issue in report.issues:
        color = {
            Severity.INFO: typer.colors.BLUE,
            Severity.WARNING: typer.colors.YELLOW,
            Severity.ERROR: typer.colors.RED,
        }[issue.severity]

        typer.secho(
            f"[{issue.severity.value.upper():7}] "
            f"{issue.table}",
            fg=color,
            nl=False,
        )

        if issue.object_id is not None:
            typer.echo(f" #{issue.object_id}: ", nl=False)
        else:
            typer.echo(": ", nl=False)

        typer.echo(issue.message)

    errors = sum(
        i.severity == Severity.ERROR
        for i in report.issues
    )

    warnings = sum(
        i.severity == Severity.WARNING
        for i in report.issues
    )

    typer.echo()
    typer.echo(f"Errors:   {errors}")
    typer.echo(f"Warnings: {warnings}")

    if errors:
        raise typer.Exit(code=1)