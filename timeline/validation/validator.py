from timeline.storage.repository import SQLiteRepository
from timeline.validation.report import ValidationIssue, ValidationReport, Severity
from timeline.domain.enums import DeviceSource, EventKind
from collections import defaultdict
from datetime import date
import json

from timeline.domain.models import Chunk, Event


class Validator:

    def __init__(self, repo: SQLiteRepository):
        self.repo = repo

    def validate(self) -> ValidationReport:
        report = ValidationReport()

        self._validate_events(report)
        self._validate_chunks(report)
        self._validate_points(report)
        self._validate_annotations(report)
        self._validate_context(report)
        self._validate_day_markers(report)

        return report

    def _validate_events(self, report: ValidationReport) -> None:
        events = self.repo.load_events()

        for event in events:
            self._validate_event_fields(report, event)

        for source_events in self._group_events_by_source(events).values():
            self._validate_event_source_state(report, source_events)

    @staticmethod
    def _group_events_by_source(events: list[Event]) -> dict[DeviceSource, list[Event]]:
        grouped: dict[DeviceSource, list[Event]] = defaultdict(list)
        for event in events:
            grouped[event.device_source].append(event)
        return grouped

    @staticmethod
    def _validate_event_fields(report: ValidationReport, event: Event) -> None:
        if not event.category:
            report.add(
                ValidationIssue(
                    Severity.ERROR,
                    "events",
                    event.id,
                    "Missing category.",
                )
            )
        if not event.name:
            report.add(
                ValidationIssue(
                    Severity.ERROR,
                    "events",
                    event.id,
                    "Missing activity name.",
                )
            )

    @staticmethod
    def _validate_event_source_state(
        report: ValidationReport,
        events: list[Event],
    ) -> None:
        current_event: Event | None = None

        for event in events:
            if event.event_kind == EventKind.INTERVAL_START:
                if current_event is not None:
                    report.add(
                        ValidationIssue(
                            Severity.ERROR,
                            "events",
                            event.id,
                            (
                                f"Interval '{event.name}' started while "
                                f"'{current_event.name}' is still active "
                                f"on {event.device_source.value}."
                            ),
                        )
                    )
                    continue
                current_event = event
            elif event.event_kind == EventKind.INTERVAL_END:
                if current_event is None:
                    report.add(
                        ValidationIssue(
                            Severity.ERROR,
                            "events",
                            event.id,
                            (
                                "Interval end without matching start "
                                f"on {event.device_source.value}."
                            ),
                        )
                    )
                    continue
                matches_current_event = True
                if event.category != current_event.category:
                    matches_current_event = False
                    report.add(
                        ValidationIssue(
                            Severity.ERROR,
                            "events",
                            event.id,
                            (
                                f"Category mismatch: "
                                f"expected '{current_event.category}', "
                                f"got '{event.category}'."
                            ),
                        )
                    )
                if event.name != current_event.name:
                    matches_current_event = False
                    report.add(
                        ValidationIssue(
                            Severity.ERROR,
                            "events",
                            event.id,
                            (
                                f"Activity mismatch: "
                                f"expected '{current_event.name}', "
                                f"got '{event.name}'."
                            ),
                        )
                    )
                if event.timestamp < current_event.timestamp:
                    matches_current_event = False
                    report.add(
                        ValidationIssue(
                            Severity.ERROR,
                            "events",
                            event.id,
                            "Interval ends before it starts.",
                        )
                    )
                if matches_current_event:
                    current_event = None
            elif event.event_kind == EventKind.POINT:
                #
                # Points don't affect interval state.
                #
                pass
        #
        # EOF
        #
        if current_event is not None:
            report.add(
                ValidationIssue(
                    Severity.WARNING,
                    "events",
                    current_event.id,
                    (
                        f"Interval '{current_event.name}' "
                        f"is still open on {current_event.device_source.value} "
                        "at end of log."
                    ),
                )
            )
    def _validate_chunks(self, report: ValidationReport):
        chunks = self.repo.load_chunks()

        for source_chunks in self._group_chunks_by_source(chunks).values():
            self._validate_chunk_source(report, source_chunks)

    @staticmethod
    def _group_chunks_by_source(chunks: list[Chunk]) -> dict[DeviceSource, list[Chunk]]:
        grouped: dict[DeviceSource, list[Chunk]] = defaultdict(list)
        for chunk in chunks:
            grouped[chunk.source].append(chunk)
        return grouped

    @staticmethod
    def _validate_chunk_source(
        report: ValidationReport,
        chunks: list[Chunk],
    ) -> None:
        previous: Chunk | None = None

        for chunk in chunks:
            if chunk.end_timestamp < chunk.start_timestamp:
                report.add(
                    ValidationIssue(
                        Severity.ERROR,
                        "chunks",
                        chunk.id,
                        "Chunk ends before it starts.",
                    )
                )

            if previous is not None and chunk.start_timestamp < previous.end_timestamp:
                report.add(
                    ValidationIssue(
                        Severity.ERROR,
                        "chunks",
                        chunk.id,
                        (
                            "Chunk overlaps previous chunk "
                            f"on {chunk.source.value}."
                        ),
                    )
                )

            previous = chunk
    def _validate_points(self, report: ValidationReport):
        pass
    def _validate_annotations(self, report: ValidationReport):
        pass
    def _validate_context(self, report: ValidationReport):
        pass
    def _validate_day_markers(self, report: ValidationReport):
        if not self._table_exists("day_markers"):
            report.add(
                ValidationIssue(
                    Severity.WARNING,
                    "day_markers",
                    None,
                    "day_markers table is missing.",
                )
            )
            return

        rows = self.repo.conn.execute(
            """
            SELECT
                id,
                day,
                habits_json,
                people_json,
                quick_note_markdown,
                mood
            FROM day_markers
            ORDER BY day
            """
        ).fetchall()

        seen_days: set[str] = set()
        for row in rows:
            marker_id = row["id"]
            marker_day = row["day"]

            try:
                date.fromisoformat(marker_day)
            except (TypeError, ValueError):
                report.add(
                    ValidationIssue(
                        Severity.ERROR,
                        "day_markers",
                        marker_id,
                        "Day marker has invalid ISO date.",
                    )
                )

            if marker_day in seen_days:
                report.add(
                    ValidationIssue(
                        Severity.ERROR,
                        "day_markers",
                        marker_id,
                        "Duplicate day marker.",
                    )
                )
            seen_days.add(marker_day)

            habits = self._json_value(
                report,
                marker_id,
                row["habits_json"],
                "habits_json",
            )
            if habits is not None:
                if not isinstance(habits, dict) or not all(isinstance(value, bool) for value in habits.values()):
                    report.add(
                        ValidationIssue(
                            Severity.ERROR,
                            "day_markers",
                            marker_id,
                            "habits_json must be an object with boolean values.",
                        )
                    )

            people = self._json_value(
                report,
                marker_id,
                row["people_json"],
                "people_json",
            )
            if people is not None:
                if not isinstance(people, list) or not all(isinstance(value, str) for value in people):
                    report.add(
                        ValidationIssue(
                            Severity.ERROR,
                            "day_markers",
                            marker_id,
                            "people_json must be a list of strings.",
                        )
                    )

            if row["quick_note_markdown"] is None:
                report.add(
                    ValidationIssue(
                        Severity.ERROR,
                        "day_markers",
                        marker_id,
                        "quick_note_markdown must not be null.",
                    )
                )

            mood = row["mood"]
            if mood is not None and not isinstance(mood, (int, float)):
                report.add(
                    ValidationIssue(
                        Severity.ERROR,
                        "day_markers",
                        marker_id,
                        "mood must be numeric or null.",
                    )
                )

    @staticmethod
    def _json_value(
        report: ValidationReport,
        marker_id: int,
        raw: str,
        column: str,
    ):
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            report.add(
                ValidationIssue(
                    Severity.ERROR,
                    "day_markers",
                    marker_id,
                    f"{column} must contain valid JSON.",
                )
            )
            return None

    def _table_exists(self, table: str) -> bool:
        row = self.repo.conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = ?
            """,
            (table,),
        ).fetchone()
        return row is not None
