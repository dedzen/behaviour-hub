from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from timeline.api.timeline import Timeline
from timeline.goals.models import (
    ActivityDurationRule,
    GoalDefinition,
    GoalOperator,
    GoalProgress,
    ProgressStatus,
)
from timeline.goals.periods import PeriodWindow, period_is_closed, period_is_future


Evaluator = Callable[[GoalDefinition, Timeline, PeriodWindow, datetime | None], GoalProgress]


class GoalEvaluatorRegistry:
    def __init__(self):
        self._evaluators: dict[str, Evaluator] = {}

    def register(self, rule_type: str, evaluator: Evaluator) -> None:
        self._evaluators[rule_type] = evaluator

    def evaluate(
        self,
        definition: GoalDefinition,
        timeline: Timeline,
        window: PeriodWindow,
        now: datetime | None = None,
    ) -> GoalProgress:
        try:
            evaluator = self._evaluators[definition.version.rule_type]
        except KeyError as exc:
            raise ValueError(f"Unsupported goal rule: {definition.version.rule_type}") from exc
        return evaluator(definition, timeline, window, now)


def evaluate_activity_duration(
    definition: GoalDefinition,
    timeline: Timeline,
    window: PeriodWindow,
    now: datetime | None = None,
) -> GoalProgress:
    rule = definition.rule
    goal_timeline = (
        Timeline(timeline.repo)
        .between(window.start_datetime, window.end_datetime)
        .source(rule.source)
        .category(rule.category)
        .activity(rule.activity)
    )
    actual = goal_timeline.statistics.chunks.total_seconds

    if period_is_future(window, now):
        status = ProgressStatus.SCHEDULED
    elif rule.operator == GoalOperator.AT_LEAST:
        if actual >= rule.target_seconds:
            status = ProgressStatus.MET
        else:
            status = (
                ProgressStatus.MISSED if period_is_closed(window, now)
                else ProgressStatus.IN_PROGRESS
            )
    elif actual > rule.target_seconds:
        status = ProgressStatus.MISSED
    else:
        status = (
            ProgressStatus.MET if period_is_closed(window, now)
            else ProgressStatus.ON_TRACK
        )

    return GoalProgress(
        definition=definition,
        period_start=window.start,
        period_end_exclusive=window.end_exclusive,
        actual_seconds=actual,
        target_seconds=rule.target_seconds,
        status=status,
    )


DEFAULT_EVALUATORS = GoalEvaluatorRegistry()
DEFAULT_EVALUATORS.register(ActivityDurationRule.RULE_TYPE, evaluate_activity_duration)
