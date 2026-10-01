from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from timeline.domain.interval_builder import IntervalBuilder
from timeline.domain.models import DayMarker, Event
from timeline.ingest.android import import_android_unlock_jsonl
from timeline.ingest.embed import import_embed_csv
from timeline.storage.repository import SQLiteRepository


@dataclass(frozen=True, slots=True)
class MutationResult:
    message: str
    warnings: tuple[str, ...] = ()
    import_summary: ImportSummary | None = None


@dataclass(frozen=True, slots=True)
class ImportSummary:
    source: str
    total_events: int
    new_events: int
    duplicate_events: int
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    ignored_events: int = 0
    dropped_orphan_starts: int = 0
    dropped_short_chunks: int = 0
    anomaly_count: int = 0
    unknown_time_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class ImportPreview:
    summary: ImportSummary
    warnings: tuple[str, ...] = ()


class TimelineMutationService:
    """Perform source-data mutations as complete SQLite transactions."""

    def __init__(self, database: Path):
        self.database = database

    def initialize(self) -> None:
        with SQLiteRepository(self.database) as repo:
            repo.ensure_schema()

    @staticmethod
    def _rebuild(repo: SQLiteRepository) -> tuple[int, tuple[str, ...]]:
        events = repo.load_events()
        chunks, warnings = IntervalBuilder.build(events)
        repo.replace_chunks(chunks)
        return len(chunks), tuple(warnings)

    @staticmethod
    def _event_key(event: Event) -> tuple:
        # Match SQLiteRepository.find_duplicate_event semantics.
        return (event.timestamp, event.event_kind, event.category or "", event.name or "")

    def _preview_events(
        self,
        source: str,
        events: list[Event],
        **source_counts,
    ) -> ImportPreview:
        with SQLiteRepository(self.database) as repo:
            repo.ensure_schema()
            existing = repo.load_events()
            known = {self._event_key(event) for event in existing}
            unique: list[Event] = []
            duplicates = 0
            for event in events:
                key = self._event_key(event)
                if key in known:
                    duplicates += 1
                    continue
                known.add(key)
                unique.append(event)
            _, warnings = IntervalBuilder.build(
                sorted([*existing, *unique], key=lambda event: event.timestamp)
            )
        timestamps = [event.timestamp for event in events]
        return ImportPreview(
            ImportSummary(
                source=source,
                total_events=len(events),
                new_events=len(unique),
                duplicate_events=duplicates,
                first_timestamp=min(timestamps) if timestamps else None,
                last_timestamp=max(timestamps) if timestamps else None,
                **source_counts,
            ),
            tuple(warnings),
        )

    def preview_embed(self, filename: Path) -> ImportPreview:
        if not filename.exists():
            raise FileNotFoundError(f"No downloaded log at {filename}")
        return self._preview_events("Embed", import_embed_csv(filename))

    def preview_android(self, filename: Path, strategy: str) -> ImportPreview:
        if not filename.exists():
            raise FileNotFoundError(f"No Android log at {filename}")
        result = import_android_unlock_jsonl(filename, strategy=strategy)  # type: ignore[arg-type]
        return self._preview_events(
            "Phone",
            result.events,
            ignored_events=result.ignored_events,
            dropped_orphan_starts=result.dropped_orphan_starts,
            dropped_short_chunks=result.dropped_short_chunks,
            anomaly_count=len(result.anomalies),
            unknown_time_seconds=result.unknown_time_seconds,
        )

    def rebuild_chunks(self) -> MutationResult:
        with SQLiteRepository(self.database) as repo:
            repo.ensure_schema()
            with repo.transaction(immediate=True):
                count, warnings = self._rebuild(repo)
        suffix = f" with {len(warnings)} warnings" if warnings else ""
        return MutationResult(f"Generated {count} chunks{suffix}", warnings)

    def update_event(self, event: Event, expected_revision: int) -> MutationResult:
        with SQLiteRepository(self.database) as repo:
            repo.ensure_schema()
            with repo.transaction(immediate=True):
                repo.update(event, expected_revision=expected_revision)
                _, warnings = self._rebuild(repo)
        return MutationResult("Event updated", warnings)

    def delete_event(self, event_id: int, expected_revision: int) -> MutationResult:
        with SQLiteRepository(self.database) as repo:
            repo.ensure_schema()
            with repo.transaction(immediate=True):
                repo.delete(Event, event_id, expected_revision=expected_revision)
                _, warnings = self._rebuild(repo)
        return MutationResult("Event deleted", warnings)

    def delete_events(self, event_revisions: dict[int, int]) -> MutationResult:
        with SQLiteRepository(self.database) as repo:
            repo.ensure_schema()
            with repo.transaction(immediate=True):
                for event_id, revision in event_revisions.items():
                    repo.delete(Event, event_id, expected_revision=revision)
                _, warnings = self._rebuild(repo)
        return MutationResult("Chunk source events deleted", warnings)

    def save_day_marker(
        self,
        marker: DayMarker,
        expected_revision: int,
    ) -> MutationResult:
        with SQLiteRepository(self.database) as repo:
            repo.ensure_schema()
            with repo.transaction(immediate=True):
                repo.upsert_day_marker(marker, expected_revision=expected_revision)
        return MutationResult("Day marker saved")

    def import_embed(self, filename: Path) -> MutationResult:
        if not filename.exists():
            raise FileNotFoundError(f"No downloaded log at {filename}")
        events = import_embed_csv(filename)
        with SQLiteRepository(self.database) as repo:
            repo.ensure_schema()
            with repo.transaction(immediate=True):
                inserted = sum(int(repo.insert_event(event)) for event in events)
                count, warnings = self._rebuild(repo)
        skipped = len(events) - inserted
        message = f"Imported {inserted} embed events"
        if skipped:
            message += f" and skipped {skipped} duplicates"
        message += f". Generated {count} chunks"
        if warnings:
            message += f" with {len(warnings)} warnings"
        timestamps = [event.timestamp for event in events]
        summary = ImportSummary(
            source="Embed",
            total_events=len(events),
            new_events=inserted,
            duplicate_events=skipped,
            first_timestamp=min(timestamps) if timestamps else None,
            last_timestamp=max(timestamps) if timestamps else None,
        )
        return MutationResult(message, warnings, summary)

    def import_android(self, filename: Path, strategy: str) -> MutationResult:
        if not filename.exists():
            raise FileNotFoundError(f"No Android log at {filename}")
        result = import_android_unlock_jsonl(filename, strategy=strategy)  # type: ignore[arg-type]
        with SQLiteRepository(self.database) as repo:
            repo.ensure_schema()
            with repo.transaction(immediate=True):
                inserted = sum(int(repo.insert_event(event)) for event in result.events)
                count, warnings = self._rebuild(repo)

        skipped = len(result.events) - inserted
        parts = [f"Imported {inserted} android events using {result.strategy} strategy"]
        if result.ignored_events:
            parts.append(f"ignored {result.ignored_events} unrelated events")
        if result.dropped_orphan_starts:
            parts.append(f"dropped {result.dropped_orphan_starts} orphan starts")
        if result.dropped_short_chunks:
            parts.append(f"dropped {result.dropped_short_chunks} chunks shorter than 20s")
        if result.anomalies:
            parts.append(f"reported {len(result.anomalies)} transition anomalies")
        if result.unknown_time_seconds:
            parts.append(f"reported {result.unknown_time_seconds:.3f}s unknown state")
        if skipped:
            parts.append(f"skipped {skipped} duplicates")
        parts.append(f"generated {count} chunks")
        if warnings:
            parts.append(f"{len(warnings)} chunk warnings")
        timestamps = [event.timestamp for event in result.events]
        summary = ImportSummary(
            source="Phone",
            total_events=len(result.events),
            new_events=inserted,
            duplicate_events=skipped,
            first_timestamp=min(timestamps) if timestamps else None,
            last_timestamp=max(timestamps) if timestamps else None,
            ignored_events=result.ignored_events,
            dropped_orphan_starts=result.dropped_orphan_starts,
            dropped_short_chunks=result.dropped_short_chunks,
            anomaly_count=len(result.anomalies),
            unknown_time_seconds=result.unknown_time_seconds,
        )
        return MutationResult(", ".join(parts), warnings, summary)
