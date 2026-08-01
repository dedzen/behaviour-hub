from dataclasses import dataclass, field
from timeline.validation.issue import ValidationIssue, Severity

@dataclass(slots=True)
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(i.severity == Severity.ERROR for i in self.issues)

    def add(self, issue: ValidationIssue):
        self.issues.append(issue)