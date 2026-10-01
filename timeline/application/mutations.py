from __future__ import annotations

from dataclasses import dataclass
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
        return MutationResult(message, warnings)

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
        return MutationResult(", ".join(parts), warnings)
