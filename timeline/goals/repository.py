from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
import json
from pathlib import Path
import sqlite3

from timeline.goals.models import (
    ActivityDurationRule,
    GoalDefinition,
    GoalPeriod,
    GoalSchedule,
    GoalSeries,
    GoalStatus,
    GoalVersion,
)
from timeline.storage.errors import ConcurrentModificationError


class GoalRepository:
    def __init__(self, database: Path):
        self.database = database
        self.conn = sqlite3.connect(database, timeout=10.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 10000")
        self.conn.execute("PRAGMA journal_mode = WAL")

    def __enter__(self) -> "GoalRepository":
        return self

    def __exit__(self, *_):
        self.close()

    def close(self) -> None:
        self.conn.close()

    def ensure_schema(self) -> None:
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        self.conn.executescript(schema)
        self.conn.commit()

    @contextmanager
    def transaction(self, *, immediate: bool = False):
        self.conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield self
        except Exception:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

    @staticmethod
    def _series(row: sqlite3.Row) -> GoalSeries:
        return GoalSeries(
            id=row["id"],
            revision=row["revision"],
            schedule=GoalSchedule(row["schedule"]),
            period=GoalPeriod(row["period"]),
            start_period=date.fromisoformat(row["start_period"]),
            end_period_exclusive=(
                date.fromisoformat(row["end_period_exclusive"])
                if row["end_period_exclusive"] else None
            ),
            status=GoalStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            archived_at=(datetime.fromisoformat(row["archived_at"]) if row["archived_at"] else None),
        )

    @staticmethod
    def _version(row: sqlite3.Row) -> GoalVersion:
        return GoalVersion(
            id=row["id"],
            series_id=row["series_id"],
            effective_from=date.fromisoformat(row["effective_from"]),
            title=row["title"],
            rule_type=row["rule_type"],
            rule_config=json.loads(row["rule_config_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def create(
        self,
        *,
        schedule: GoalSchedule,
        period: GoalPeriod,
        start_period: date,
        end_period_exclusive: date | None,
        title: str,
        rule: ActivityDurationRule,
    ) -> GoalDefinition:
        now = datetime.now().isoformat(sep=" ")
        cursor = self.conn.execute(
            """
            INSERT INTO goal_series(
                schedule, period, start_period, end_period_exclusive, status, created_at
            ) VALUES (?, ?, ?, ?, 'active', ?)
            """,
            (
                schedule.value,
                period.value,
                start_period.isoformat(),
                end_period_exclusive.isoformat() if end_period_exclusive else None,
                now,
            ),
        )
        series_id = int(cursor.lastrowid)
        self.conn.execute(
            """
            INSERT INTO goal_versions(
                series_id, effective_from, title, rule_type, rule_config_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                series_id,
                start_period.isoformat(),
                title.strip(),
                rule.RULE_TYPE,
                json.dumps(rule.to_config(), sort_keys=True),
                now,
            ),
        )
        return self.definition(series_id, start_period)  # type: ignore[return-value]

    def get_series(self, series_id: int) -> GoalSeries | None:
        row = self.conn.execute(
            "SELECT * FROM goal_series WHERE id = ?", (series_id,)
        ).fetchone()
        return self._series(row) if row else None

    def list_series(self) -> list[GoalSeries]:
        return [
            self._series(row)
            for row in self.conn.execute(
                "SELECT * FROM goal_series ORDER BY status, created_at DESC"
            ).fetchall()
        ]

    def list_versions(self, series_id: int) -> list[GoalVersion]:
        return [
            self._version(row)
            for row in self.conn.execute(
                """
                SELECT * FROM goal_versions
                WHERE series_id = ? ORDER BY effective_from, id
                """,
                (series_id,),
            ).fetchall()
        ]

    def definition(self, series_id: int, selected_period: date) -> GoalDefinition | None:
        series = self.get_series(series_id)
        if series is None:
            return None
        row = self.conn.execute(
            """
            SELECT * FROM goal_versions
            WHERE series_id = ? AND effective_from <= ?
            ORDER BY effective_from DESC, id DESC LIMIT 1
            """,
            (series_id, selected_period.isoformat()),
        ).fetchone()
        return GoalDefinition(series, self._version(row)) if row else None

    def definitions_for_period(
        self,
        period: GoalPeriod,
        selected_period: date,
    ) -> list[GoalDefinition]:
        rows = self.conn.execute(
            """
            SELECT * FROM goal_series
            WHERE period = ?
              AND start_period <= ?
              AND (end_period_exclusive IS NULL OR ? < end_period_exclusive)
            ORDER BY created_at, id
            """,
            (period.value, selected_period.isoformat(), selected_period.isoformat()),
        ).fetchall()
        definitions = [
            definition
            for row in rows
            if (definition := self.definition(row["id"], selected_period)) is not None
        ]
        return definitions

    def revise(
        self,
        series_id: int,
        expected_revision: int,
        *,
        effective_from: date,
        title: str,
        rule: ActivityDurationRule,
    ) -> GoalDefinition:
        self._assert_revision(series_id, expected_revision)
        now = datetime.now().isoformat(sep=" ")
        self.conn.execute(
            """
            INSERT INTO goal_versions(
                series_id, effective_from, title, rule_type, rule_config_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(series_id, effective_from) DO UPDATE SET
                title = excluded.title,
                rule_type = excluded.rule_type,
                rule_config_json = excluded.rule_config_json,
                created_at = excluded.created_at
            """,
            (
                series_id,
                effective_from.isoformat(),
                title.strip(),
                rule.RULE_TYPE,
                json.dumps(rule.to_config(), sort_keys=True),
                now,
            ),
        )
        self._increment_revision(series_id, expected_revision)
        return self.definition(series_id, effective_from)  # type: ignore[return-value]

    def archive(
        self,
        series_id: int,
        expected_revision: int,
        *,
        end_period_exclusive: date,
    ) -> GoalSeries:
        cursor = self.conn.execute(
            """
            UPDATE goal_series SET
                status = 'archived',
                archived_at = ?,
                end_period_exclusive = ?,
                revision = revision + 1
            WHERE id = ? AND revision = ?
            """,
            (
                datetime.now().isoformat(sep=" "),
                end_period_exclusive.isoformat(),
                series_id,
                expected_revision,
            ),
        )
        if cursor.rowcount != 1:
            raise ConcurrentModificationError("goal", series_id)
        return self.get_series(series_id)  # type: ignore[return-value]

    def delete(self, series_id: int, expected_revision: int) -> None:
        cursor = self.conn.execute(
            "DELETE FROM goal_series WHERE id = ? AND revision = ?",
            (series_id, expected_revision),
        )
        if cursor.rowcount != 1:
            raise ConcurrentModificationError("goal", series_id)

    def _assert_revision(self, series_id: int, expected_revision: int) -> None:
        row = self.conn.execute(
            "SELECT revision FROM goal_series WHERE id = ?", (series_id,)
        ).fetchone()
        if row is None or row["revision"] != expected_revision:
            raise ConcurrentModificationError("goal", series_id)

    def _increment_revision(self, series_id: int, expected_revision: int) -> None:
        cursor = self.conn.execute(
            """
            UPDATE goal_series SET revision = revision + 1
            WHERE id = ? AND revision = ?
            """,
            (series_id, expected_revision),
        )
        if cursor.rowcount != 1:
            raise ConcurrentModificationError("goal", series_id)
