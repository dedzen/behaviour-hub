from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from timeline.domain.enums import DeviceSource


class GoalPeriod(StrEnum):
    DAY = "day"
    WEEK = "week"


class GoalSchedule(StrEnum):
    RECURRING = "recurring"
    ONE_OFF = "one_off"


class GoalStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class GoalOperator(StrEnum):
    AT_LEAST = "at_least"
    AT_MOST = "at_most"


class ProgressStatus(StrEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    ON_TRACK = "on_track"
    MET = "met"
    MISSED = "missed"


@dataclass(frozen=True, slots=True)
class ActivityDurationRule:
    source: DeviceSource
    category: str
    activity: str
    operator: GoalOperator
    target_seconds: int

    RULE_TYPE = "activity_duration"

    def __post_init__(self) -> None:
        if not self.category.strip():
            raise ValueError("Category is required")
        if not self.activity.strip():
            raise ValueError("Activity is required")
        if self.target_seconds <= 0:
            raise ValueError("Target duration must be positive")

    def to_config(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "category": self.category,
            "activity": self.activity,
            "operator": self.operator.value,
            "target_seconds": self.target_seconds,
        }

    @classmethod
    def from_config(cls, value: dict[str, Any]) -> "ActivityDurationRule":
        return cls(
            source=DeviceSource(value["source"]),
            category=str(value["category"]),
            activity=str(value["activity"]),
            operator=GoalOperator(value["operator"]),
            target_seconds=int(value["target_seconds"]),
        )


@dataclass(frozen=True, slots=True)
class GoalSeries:
    id: int
    revision: int
    schedule: GoalSchedule
    period: GoalPeriod
    start_period: date
    end_period_exclusive: date | None
    status: GoalStatus
    created_at: datetime
    archived_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class GoalVersion:
    id: int
    series_id: int
    effective_from: date
    title: str
    rule_type: str
    rule_config: dict[str, Any]
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("Goal title is required")


@dataclass(frozen=True, slots=True)
class GoalDefinition:
    series: GoalSeries
    version: GoalVersion

    @property
    def rule(self) -> ActivityDurationRule:
        if self.version.rule_type != ActivityDurationRule.RULE_TYPE:
            raise ValueError(f"Unsupported goal rule: {self.version.rule_type}")
        return ActivityDurationRule.from_config(self.version.rule_config)


@dataclass(frozen=True, slots=True)
class GoalProgress:
    definition: GoalDefinition
    period_start: date
    period_end_exclusive: date
    actual_seconds: int
    target_seconds: int
    status: ProgressStatus

    @property
    def ratio(self) -> float:
        return self.actual_seconds / self.target_seconds if self.target_seconds else 0.0
