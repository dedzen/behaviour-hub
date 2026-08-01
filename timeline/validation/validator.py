from timeline.storage.repository import SQLiteRepository
from timeline.validation.report import ValidationIssue, ValidationReport, Severity
from timeline.domain.enums import DeviceSource, EventKind
from timeline.domain.models import Event


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

        return report

    def _validate_events(self, report: ValidationReport) -> None:
        events = self.repo.load_events()

        current_events: dict[DeviceSource, Event] = {}

        for event in events:
            #
            # Basic checks
            #
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
            #
            # State machine
            #
            if event.event_kind == EventKind.INTERVAL_START:
                current_event = current_events.get(event.device_source)
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
                current_events[event.device_source] = event
            elif event.event_kind == EventKind.INTERVAL_END:
                current_event = current_events.get(event.device_source)
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
                    current_events.pop(event.device_source, None)
            elif event.event_kind == EventKind.POINT:
                #
                # Points don't affect interval state.
                #
                pass
        #
        # EOF
        #
        for current_event in current_events.values():
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
        previous_by_source = {}

        for chunk in self.repo.load_chunks():
            previous = previous_by_source.get(chunk.source)

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

            previous_by_source[chunk.source] = chunk
    def _validate_points(self, report: ValidationReport):
        pass
    def _validate_annotations(self, report: ValidationReport):
        pass
    def _validate_context(self, report: ValidationReport):
        pass
