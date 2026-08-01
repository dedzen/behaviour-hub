from dataclasses import dataclass
from enum import Enum


class Severity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(slots=True)
class ValidationIssue:
    severity: Severity
    table: str
    object_id: int | None
    message: str