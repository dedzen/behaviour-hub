# Behaviour Hub

Behaviour Hub is a local-first time-tracking and behaviour analytics project. It
imports time signals from external sources, stores them in a normalized SQLite
model, rebuilds interval sessions from raw events, and exposes the data through a
Python API, CLI commands, analytical/statistical suites, plots, and a NiceGUI web
dashboard.

The project is built around one core idea: keep raw observations available, then
derive higher-level timeline views from them. Raw `events` represent interval
starts, interval ends, and point observations. Generated `chunks` represent
closed intervals. `points`, `annotations`, and `context` add extra timeline
detail without replacing the source log.

## Features

- Import Embed CSV logs into the canonical `events` table.
- Import Android screen/unlock JSONL logs into the canonical `events` table.
- Rebuild duration chunks from start/end events with per-device interval state.
- Query timelines by day, week, month, year, relative ranges, category, activity,
  source, duration, weekday, and text search.
- Export queried chunk data to Polars DataFrames for notebooks and analysis.
- Compute chunk statistics such as total time, sessions, averages, medians,
  extrema, daily aggregates, activity aggregates, and activity share.
- Run analytics such as period summaries, rolling trends, pivots, transitions,
  and comparisons between slices.
- Use a NiceGUI dashboard for filters, statistics, analytics tables, ECharts
  plots, day-lane timelines, and raw event editing.
- Validate database consistency for malformed events and overlapping chunks.

## Project Layout

```text
timeline/
  api/          Immutable timeline query API, metadata, and Polars exports.
  commands/     Typer CLI commands for import, chunk rebuilds, validation, edits.
  domain/       Dataclasses, enums, and interval-building rules.
  ingest/       Source-specific importers.
  statistics/   Summary and aggregate statistics over chunk data.
  analytics/    Higher-level time-series, share, transition, and compare tools.
  storage/      SQLite schema and repository.
  validation/   Database validation reports and checks.
nice_ui/
  app.py        NiceGUI application entry point.
  pages/        Dashboard views, filters, plots, events, and day timeline.
notebooks/      Exploratory import and repository-view notebooks.
scripts/        Small helper scripts for Embed logs.
tests/          Unit tests for interval logic, validation, UI helpers, clipping.
```

## Requirements

- Python 3.13 or newer
- `uv`
- SQLite, provided by Python's standard library

Project dependencies are declared in `pyproject.toml` and locked in `uv.lock`.
The main runtime stack is Typer, NiceGUI, Pandas, and Polars.

## Setup

Install dependencies:

```bash
uv sync
```

Run the test suite:

```bash
uv run python -m unittest discover -s tests
```

Start the web dashboard:

```bash
uv run python -m nice_ui.app
```

By default the UI listens on port `8080`. Override it with `NICEGUI_PORT`:

```bash
NICEGUI_PORT=8081 uv run python -m nice_ui.app
```

The application expects `timeline.db` in the project root unless a CLI command
is given a different database path.

## Data Model

Behaviour Hub uses SQLite tables defined in `timeline/storage/schema.sql`.

- `events`: raw imported or edited observations. Each event has a timestamp,
  device source, kind, category, and name.
- `chunks`: generated closed intervals with start/end timestamps, duration,
  source, category/name, and links to the start/end events that produced them.
- `points`: point-in-time observations that do not create chunks.
- `annotations`: free text attached to a chunk or point.
- `context`: timestamped key/value metadata from a source.

Current device sources are `embed`, `pc`, and `phone`. Current event kinds are
`interval_start`, `interval_end`, and `point`.

Intervals are source-scoped. Different sources may overlap, but one source may
only have one active interval at a time. A valid interval end must match the
active start's source, category, and name.

## Import And Rebuild Workflow

Import an Embed CSV log:

```bash
uv run behaviour-hub import embed path/to/log.csv --database timeline.db
```

Import an Android unlock/screen JSONL log:

```bash
uv run behaviour-hub import android-download 192.168.3.55:8080 --output data/android/unlock-events.jsonl
uv run behaviour-hub import android data/android/unlock-events.jsonl --database timeline.db --strategy active_screen
uv run behaviour-hub import android-clear 192.168.3.55:8080
```

Embed CSV rows are expected to include:

- `timestamp`: ISO-compatible datetime
- `event`: `start`, `end`, or `point`
- `task`: either `Category: Activity` or a bare activity name

Rebuild generated chunks after importing or editing events:

```bash
uv run behaviour-hub chunks rebuild --database timeline.db
```

Validate the database:

```bash
uv run behaviour-hub validate --db timeline.db
```

List, edit, or delete raw events:

```bash
uv run behaviour-hub events list --db timeline.db --day 2026-08-01
uv run behaviour-hub events edit 123 --db timeline.db
uv run behaviour-hub events delete 123 --db timeline.db
uv run behaviour-hub export markdown 2026-08-01 --database timeline.db --output daily.md
```

The NiceGUI Import/Export page can also download an Embed log from
`http://<ip>/log.csv`, clear the remote log with `DELETE`, import the downloaded
file from `data/embed/incoming.csv`, import Android logs from
`data/android/unlock-events.jsonl` using the active-screen strategy, and rebuild chunks.
The CLI can download and clear Android logs through
`http://<ip-or-host:port>/unlock-events.jsonl`.

## Python API

Use `SQLiteRepository` and `Timeline` for programmatic access:

```python
from pathlib import Path

from timeline.api.timeline import Timeline
from timeline.storage.repository import SQLiteRepository

repo = SQLiteRepository(Path("timeline.db"))
timeline = Timeline(repo)

today = timeline.day("2026-08-01")
chunks = today.chunks()
events = today.events()

df = today.to_clipped_polars()
summary = today.statistics.chunks.summary()
share = today.analytics.chunks.share()

repo.close()
```

Timeline filters are immutable: each filter returns a new `Timeline` with an
updated query. Common filters include:

```python
timeline.day("2026-08-01")
timeline.week("2026-31")
timeline.month("2026-08")
timeline.year(2026)
timeline.last(days=7)
timeline.category("Work")
timeline.activity(["Focus", "Meeting"])
timeline.source(DeviceSource.PC)
timeline.duration(minimum=15 * 60, maximum=4 * 3600)
```

Use `to_polars()` when you want persisted chunk rows selected by their start
timestamp. Use `to_clipped_polars()` for dashboard/statistical semantics where
chunks overlapping a query range are clipped to the selected window before
duration is calculated.

## Dashboard

The NiceGUI dashboard includes:

- Sidebar filters for time presets, devices, activities, and duration range.
- Statistics tab with summary, by-activity, and by-day tables.
- Analytics tab with time share, daily mix, rolling daily time, and short-gap
  transitions.
- Plots tab with ECharts views for activity share, total tracked time,
  composition, and trends by day/week/month/year.
- Day tab with per-source lanes for chunks and point markers.
- Event Viewer tab with search, event editing, deletion, and automatic chunk
  rebuilds.

## Development

Run tests before changing core timeline behavior:

```bash
uv run python -m unittest discover -s tests
```

Useful focused tests:

```bash
uv run python -m unittest tests.test_interval_builder
uv run python -m unittest tests.test_clipped_timeline
uv run python -m unittest tests.test_validator
```

There is no separate migration framework yet. Schema changes should be made in
`timeline/storage/schema.sql`, reflected in `timeline/domain/models.py` and
`timeline/storage/repository.py`, and covered by tests.
