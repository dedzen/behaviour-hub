# AGENTS.md

Repository-specific instructions for coding agents working on Behaviour Hub.

## Operating Rules

- Use `uv` for project commands. The project targets Python 3.13.
- Prefer `rg` and `rg --files` for repository inspection.
- Do not overwrite or revert existing user changes. This project may have a
  dirty worktree.
- Use `apply_patch` for manual edits.
- Run `uv run python -m unittest discover -s tests` after behavior changes when feasible.
- Keep docs and examples aligned with actual CLI names and module paths.

## Core Architecture

Behaviour Hub is event-first. Raw imported observations live in `events`; derived
closed intervals live in `chunks`; point observations, annotations, and context
add extra timeline detail.

Important modules:

- `timeline/domain/models.py`: dataclasses for `Event`, `Chunk`, `Point`,
  `Annotation`, and `Context`.
- `timeline/domain/enums.py`: `DeviceSource` and `EventKind` values.
- `timeline/domain/interval_builder.py`: rules for turning events into chunks.
- `timeline/storage/schema.sql`: SQLite schema.
- `timeline/storage/repository.py`: repository methods and SQL query loading.
- `timeline/api/query.py`: immutable filter state and SQL WHERE construction.
- `timeline/api/timeline.py`: public query API, Polars exports, suites.
- `timeline/statistics/` and `timeline/analytics/`: aggregate behavior.
- `nice_ui/app.py` and `nice_ui/pages/`: NiceGUI dashboard.
- `timeline/commands/`: Typer CLI entry points.

## Data Invariants

- Events are the source of truth. Rebuild chunks after importing, editing, or
  deleting events.
- Intervals are scoped by `DeviceSource`. Different sources may overlap.
- A single source must not have two active intervals at once.
- An interval end must match the active start's source, category, and name.
- `EventKind.POINT` does not create a chunk.
- Chunks store `start_event_id` and `end_event_id` links back to events.
- Dashboard/statistics semantics use clipped chunks for selected time windows.
  `Timeline.to_polars()` keeps persisted chunk durations; `Timeline.to_clipped_polars()`
  trims overlapping chunks to the query range.

## Commands

Install/sync dependencies:

```bash
uv sync
```

Run tests:

```bash
uv run python -m unittest discover -s tests
```

Run the app:

```bash
uv run python -m nice_ui.app
```

Run the app on a specific port:

```bash
NICEGUI_PORT=8081 uv run python -m nice_ui.app
```

Import Embed CSV:

```bash
uv run behaviour-hub import embed path/to/log.csv --database timeline.db
```

Import Android JSONL:

```bash
uv run behaviour-hub import android-download 192.168.3.55:8080 --output data/android/unlock-events.jsonl
uv run behaviour-hub import android data/android/unlock-events.jsonl --database timeline.db --strategy active_screen
uv run behaviour-hub import android-clear 192.168.3.55:8080
```

Rebuild chunks:

```bash
uv run behaviour-hub chunks rebuild --database timeline.db
```

Validate database:

```bash
uv run behaviour-hub validate --db timeline.db
```

List events:

```bash
uv run behaviour-hub events list --db timeline.db --day 2026-08-01
```

Export a daily markdown note:

```bash
uv run behaviour-hub export markdown 2026-08-01 --database timeline.db --output daily.md
```

## Testing Guidance

Use focused tests when touching these areas:

- Interval state machine: `uv run python -m unittest tests.test_interval_builder`
- Query-range clipping and period splitting:
  `uv run python -m unittest tests.test_clipped_timeline`
- Database validation: `uv run python -m unittest tests.test_validator`
- Event viewer editing helpers: `uv run python -m unittest tests.test_events_view`
- Day timeline rendering helpers:
  `uv run python -m unittest tests.test_day_timeline_view`

Add or update tests when changing interval rules, query filtering, clipping,
analytics aggregation, persistence, or UI helper behavior.

## Implementation Notes

- Repository methods do not automatically create schema except through explicit
  `ensure_schema()` calls. Call it in import/setup paths that create databases.
- The CLI uses the `behaviour-hub` script from `pyproject.toml`.
- The NiceGUI app uses `timeline.db` in the project root and stores downloaded
  Embed logs at `data/embed/incoming.csv`.
- `Timeline` filter methods return a new `Timeline`; do not mutate query state
  in place.
- Be careful with date boundary semantics. Existing code has both start-based
  selection and overlapping/clipped selection; choose intentionally.
- If schema fields change, update `schema.sql`, dataclasses, `from_row`,
  `to_db_tuple`, repository insert/update SQL, and tests together.
