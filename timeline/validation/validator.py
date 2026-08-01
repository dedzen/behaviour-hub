from timeline.storage.repository import SQLiteRepository
from timeline.validation.report import ValidationIssue, ValidationReport, Severity
from timeline.domain.enums import EventKind
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

        current_event = None

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
                if current_event is not None:
                    report.add(
                        ValidationIssue(
                            Severity.ERROR,
                            "events",
                            event.id,
                            (
                                f"Interval '{event.name}' started while "
                                f"'{current_event.name}' is still active."
                            ),
                        )
                    )
                current_event = event
            elif event.event_kind == EventKind.INTERVAL_END:
                if current_event is None:
                    report.add(
                        ValidationIssue(
                            Severity.ERROR,
                            "events",
                            event.id,
                            "Interval end without matching start.",
                        )
                    )
                    continue
                if event.category != current_event.category:
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
                    report.add(
                        ValidationIssue(
                            Severity.ERROR,
                            "events",
                            event.id,
                            "Interval ends before it starts.",
                        )
                    )
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
                        "is still open at end of log."
                    ),
                )
            )
    def _validate_chunks(self, report: ValidationReport):
        pass
    def _validate_points(self, report: ValidationReport):
        pass
    def _validate_annotations(self, report: ValidationReport):
        pass
    def _validate_context(self, report: ValidationReport):
        pass