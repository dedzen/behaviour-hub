import sqlite3
from contextlib import contextmanager
from pathlib import Path
from timeline.domain.models import Event, Chunk, Point, Annotation, Context, DayMarker
from datetime import date, datetime
from typing import TypeVar
from timeline.api.query import Query
from timeline.storage.errors import ConcurrentModificationError

T = TypeVar('T')


class SQLiteRepository:
    def __init__(self, database: Path):
        self.conn = sqlite3.connect(database, timeout=10.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 10000")
        self.conn.execute("PRAGMA journal_mode = WAL")

    def close(self):
        self.conn.close()

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    @contextmanager
    def transaction(self, *, immediate: bool = False):
        self.conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield self
        except Exception:
            self.rollback()
            raise
        else:
            self.commit()


    def insert_event(self, event: Event):
        existing = self.find_duplicate_event(event)
        if existing is not None:
            event.id = existing.id
            event.revision = existing.revision
            return False

        cursor = self.conn.execute(
            """
            INSERT INTO events(
                timestamp,
                device_source,
                event_kind,
                category,
                name
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            event.to_db_tuple(),
        )

        event.id = cursor.lastrowid
        event.revision = 1
        return True

    def load_events(self, query: Query | None = None) -> list[Event]:
        return self._load_table(
                    "events",
                    Event,
                    timestamp_column="timestamp",
                    source_column="device_source",
                    query=query,
                )
    def _insert_chunk(self, chunk: Chunk) -> Chunk:
        cursor = self.conn.execute(
            """
            INSERT INTO chunks (
                start_timestamp,
                end_timestamp,
                duration_seconds,
                source,
                category,
                name,
                start_event_id,
                end_event_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            chunk.to_db_tuple(),
        )

        chunk.id = cursor.lastrowid
        return chunk

    
    def replace_chunks(self, chunks: list[Chunk]):
        self._delete_chunks()
        for c in chunks:
            self._insert_chunk(c)

    def _delete_chunks(self):
        self.conn.execute("DELETE FROM chunks")

    def insert_point(self, point: Point) -> Point:
        cursor = self.conn.execute(
            """
            INSERT INTO points (
                timestamp,
                category,
                name,
                source,
                event_id
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            point.to_db_tuple(),
        )

        point.id = cursor.lastrowid
        return point

    def insert_annotation(self, annotation: Annotation) -> Annotation:
        cursor = self.conn.execute(
            """
            INSERT INTO annotations (
                timestamp,
                text,
                chunk_id,
                point_id
            )
            VALUES (?, ?, ?, ?)
            """,
            annotation.to_db_tuple(),
        )

        annotation.id = cursor.lastrowid
        return annotation

    def insert_context(self, context: Context) -> Context:
        cursor = self.conn.execute(
            """
            INSERT INTO context (
                timestamp,
                key,
                value,
                source
            )
            VALUES (?, ?, ?, ?)
            """,
            context.to_db_tuple(),
        )

        context.id = cursor.lastrowid
        return context

    def get_day_marker(self, day: date | str) -> DayMarker | None:
        selected_day = self._day_value(day)
        row = self.conn.execute(
            "SELECT * FROM day_markers WHERE day = ?",
            (selected_day.isoformat(),),
        ).fetchone()

        return None if row is None else DayMarker.from_row(row)

    def upsert_day_marker(
        self,
        marker: DayMarker,
        *,
        expected_revision: int | None = None,
    ) -> DayMarker:
        if expected_revision is not None:
            return self._upsert_day_marker_if_current(marker, expected_revision)

        cursor = self.conn.execute(
            """
            INSERT INTO day_markers (
                day,
                habits_json,
                people_json,
                quick_note_markdown,
                mood
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(day) DO UPDATE SET
                habits_json = excluded.habits_json,
                people_json = excluded.people_json,
                quick_note_markdown = excluded.quick_note_markdown,
                mood = excluded.mood,
                revision = day_markers.revision + 1
            RETURNING id, revision
            """,
            marker.to_db_tuple(),
        )
        row = cursor.fetchone()
        marker.id = row["id"]
        marker.revision = row["revision"]
        return marker

    def _upsert_day_marker_if_current(
        self,
        marker: DayMarker,
        expected_revision: int,
    ) -> DayMarker:
        if expected_revision == 0:
            try:
                cursor = self.conn.execute(
                    """
                    INSERT INTO day_markers (
                        day, habits_json, people_json, quick_note_markdown, mood
                    ) VALUES (?, ?, ?, ?, ?)
                    RETURNING id, revision
                    """,
                    marker.to_db_tuple(),
                )
            except sqlite3.IntegrityError as exc:
                raise ConcurrentModificationError("day marker", marker.day) from exc
        else:
            cursor = self.conn.execute(
                """
                UPDATE day_markers
                SET habits_json = ?,
                    people_json = ?,
                    quick_note_markdown = ?,
                    mood = ?,
                    revision = revision + 1
                WHERE day = ? AND revision = ?
                RETURNING id, revision
                """,
                (
                    marker.to_db_tuple()[1],
                    marker.to_db_tuple()[2],
                    marker.quick_note_markdown,
                    marker.mood,
                    marker.day.isoformat(),
                    expected_revision,
                ),
            )

        row = cursor.fetchone()
        if row is None:
            raise ConcurrentModificationError("day marker", marker.day)
        marker.id = row["id"]
        marker.revision = row["revision"]
        return marker

    def load_day_markers(
        self,
        *,
        start: date | str | None = None,
        end: date | str | None = None,
    ) -> list[DayMarker]:
        where: list[str] = []
        params: list[str] = []

        if start is not None:
            where.append("day >= ?")
            params.append(self._day_value(start).isoformat())
        if end is not None:
            where.append("day <= ?")
            params.append(self._day_value(end).isoformat())

        sql = "SELECT * FROM day_markers"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY day"

        return [DayMarker.from_row(row) for row in self.conn.execute(sql, params)]

    def delete_day_marker(self, day_or_id: date | str | int) -> None:
        if isinstance(day_or_id, int):
            self.conn.execute("DELETE FROM day_markers WHERE id = ?", (day_or_id,))
            return

        selected_day = self._day_value(day_or_id)
        self.conn.execute("DELETE FROM day_markers WHERE day = ?", (selected_day.isoformat(),))

    def _select_sql(
        self,
        table: str,
        *,
        timestamp_column: str = "timestamp",
        source_column: str = "source",
        query: Query | None = None,
    ) -> tuple[str, list]:
        query = query or Query()

        where, params = query.where_clause(
            timestamp_column=timestamp_column,
            source_column=source_column,
        )

        sql = f"""
            SELECT *
            FROM {table}
            {where}
            ORDER BY {timestamp_column}
        """

        return sql, params
    def _load_table(
        self,
        table: str,
        model: type[T],
        *,
        timestamp_column: str = "timestamp",
        source_column: str = "source",
        query: Query | None = None,
    ) -> list[T]:

        sql, params = self._select_sql(
            table,
            timestamp_column=timestamp_column,
            source_column=source_column,
            query=query,
        )

        return self._load(sql, params, model)

    def _load(
        self,
        sql: str,
        params: list,
        model,
    ):
        rows = self.conn.execute(sql, params)
        return [model.from_row(row) for row in rows]

    def load_chunks(self, query: Query | None = None) -> list[Chunk]:
        return self._load_table(
            "chunks",
            Chunk,
            timestamp_column="start_timestamp",
            query=query,
        )

    def load_points(self, query: Query | None = None) -> list[Point]:
        return self._load_table(
            "points",
            Point,
            query=query,
        )

    def load_context(self, query: Query | None = None) -> list[Context]:
            return self._load_table(
                "context",
                Context,
                query=query,
        )

    def load_annotations(self, query: Query | None = None) -> list[Annotation]:
                return self._load_table(
                    "annotations",
                    Annotation,
                    query=query,
            )

    def update(self, obj, *, expected_revision: int | None = None) -> None:
        if isinstance(obj, Event):
            if expected_revision is not None:
                self._assert_revision(Event, obj.id, expected_revision)
            duplicate = self.find_duplicate_event(obj, exclude_id=obj.id)
            if duplicate is not None:
                self._merge_events(duplicate.id, obj.id) # type: ignore[arg-type]
                obj.id = duplicate.id
                obj.revision = duplicate.revision
                return

            if expected_revision is not None:
                cursor = self.conn.execute(
                    """
                    UPDATE events
                    SET timestamp = ?, device_source = ?, event_kind = ?,
                        category = ?, name = ?, revision = revision + 1
                    WHERE id = ? AND revision = ?
                    """,
                    obj.to_db_tuple() + (obj.id, expected_revision),
                )
                if cursor.rowcount != 1:
                    raise ConcurrentModificationError("event", obj.id)
                obj.revision = expected_revision + 1
                return

        self.conn.execute(
            obj.UPDATE_SQL,
            obj.to_db_tuple() + (obj.id,),
        )
        if isinstance(obj, (Event, DayMarker)):
            obj.revision += 1

    def get(self, model, id: int):
        row = self.conn.execute(
            f"SELECT * FROM {model.TABLE} WHERE id = ?",
            (id,),
        ).fetchone()

        return None if row is None else model.from_row(row)

    def delete(self, model, id: int, *, expected_revision: int | None = None):
        if expected_revision is None:
            self.conn.execute(
                f"DELETE FROM {model.TABLE} WHERE id = ?",
                (id,),
            )
            return

        cursor = self.conn.execute(
            f"DELETE FROM {model.TABLE} WHERE id = ? AND revision = ?",
            (id, expected_revision),
        )
        if cursor.rowcount != 1:
            raise ConcurrentModificationError(model.__name__.lower(), id)

    def _assert_revision(self, model, id: int | None, expected_revision: int) -> None:
        row = self.conn.execute(
            f"SELECT revision FROM {model.TABLE} WHERE id = ?",
            (id,),
        ).fetchone()
        if row is None or row["revision"] != expected_revision:
            raise ConcurrentModificationError(model.__name__.lower(), id)

    def find_duplicate_event(
        self,
        event: Event,
        *,
        exclude_id: int | None = None,
    ) -> Event | None:
        row = self.conn.execute(
            """
            SELECT *
            FROM events
            WHERE timestamp = ?
              AND event_kind = ?
              AND IFNULL(category, '') = IFNULL(?, '')
              AND IFNULL(name, '') = IFNULL(?, '')
              AND (? IS NULL OR id != ?)
            ORDER BY id
            LIMIT 1
            """,
            (
                event.timestamp.isoformat(sep=" "),
                event.event_kind.value,
                event.category,
                event.name,
                exclude_id,
                exclude_id,
            ),
        ).fetchone()

        return None if row is None else Event.from_row(row)

    def deduplicate_events(self) -> int:
        duplicate_groups = self.conn.execute(
            """
            SELECT
                timestamp,
                event_kind,
                IFNULL(category, '') AS category_key,
                IFNULL(name, '') AS name_key
            FROM events
            GROUP BY
                timestamp,
                event_kind,
                category_key,
                name_key
            HAVING COUNT(*) > 1
            """
        ).fetchall()

        removed = 0

        for group in duplicate_groups:
            rows = self.conn.execute(
                """
                SELECT id
                FROM events
                WHERE timestamp = ?
                  AND event_kind = ?
                  AND IFNULL(category, '') = ?
                  AND IFNULL(name, '') = ?
                ORDER BY id
                """,
                (
                    group["timestamp"],
                    group["event_kind"],
                    group["category_key"],
                    group["name_key"],
                ),
            ).fetchall()

            keep_id = rows[0]["id"]
            for row in rows[1:]:
                self._merge_events(keep_id, row["id"])
                removed += 1

        return removed

    def _merge_events(self, keep_id: int, drop_id: int) -> None:
        if keep_id == drop_id:
            return

        self.conn.execute(
            "UPDATE points SET event_id = ? WHERE event_id = ?",
            (keep_id, drop_id),
        )
        self.conn.execute(
            "UPDATE chunks SET start_event_id = ? WHERE start_event_id = ?",
            (keep_id, drop_id),
        )
        self.conn.execute(
            "UPDATE chunks SET end_event_id = ? WHERE end_event_id = ?",
            (keep_id, drop_id),
        )
        self.conn.execute(
            "DELETE FROM events WHERE id = ?",
            (drop_id,),
        )

    def distinct(
        self,
        table: str,
        column: str,
        *,
        query: Query | None = None,
        timestamp_column: str = "start_timestamp",
    ) -> list:
        query = query or Query()

        where, params = query.where_clause(
            timestamp_column=timestamp_column,
        )

        sql = f"""
            SELECT DISTINCT {column}
            FROM {table}
            {where}
            ORDER BY {column}
        """

        return [
            row[0]
            for row in self.conn.execute(sql, params).fetchall()
            if row[0] is not None
        ]

    def date_range(
        self,
        table: str,
        *,
        start_column: str = "start_timestamp",
        end_column: str = "end_timestamp",
        query: Query | None = None,
    ) -> tuple[datetime | None, datetime | None]:

        query = query or Query()

        where, params = query.where_clause(
            timestamp_column=start_column,
        )

        sql = f"""
            SELECT
                MIN({start_column}),
                MAX({end_column})
            FROM {table}
            {where}
        """

        row = self.conn.execute(sql, params).fetchone()

        if row is None or row[0] is None:
            return None, None

        return (
            datetime.fromisoformat(row[0]),
            datetime.fromisoformat(row[1]),
        )

    def activity_tree(
        self,
        *,
        query: Query | None = None,
    ) -> dict[str, list[str]]:

        query = query or Query()

        where, params = query.where_clause(
            timestamp_column="start_timestamp",
        )

        sql = f"""
            SELECT DISTINCT
                category,
                name
            FROM chunks
            {where}
            ORDER BY
                category,
                name
        """

        tree: dict[str, list[str]] = {}

        for category, name in self.conn.execute(sql, params):
            tree.setdefault(category, []).append(name)

        return tree
    def ensure_schema(self):
        schema_path = Path(__file__).with_name("schema.sql")

        with schema_path.open("r", encoding="utf-8") as f:
            self.conn.executescript(f.read())
        self._ensure_column("events", "revision", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column("day_markers", "revision", "INTEGER NOT NULL DEFAULT 1")
        user_version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if user_version < 1:
            self.conn.execute("PRAGMA user_version = 1")

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in self.conn.execute(f"PRAGMA table_info({table})")
        }
        if column not in columns:
            try:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise

    @staticmethod
    def _day_value(value: date | str) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(value)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is None:
            self.commit()
        else:
            self.rollback()
        self.close()
