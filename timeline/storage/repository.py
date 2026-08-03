import sqlite3
from pathlib import Path
from timeline.domain.models import Event, Chunk, Point, Annotation, Context
from datetime import datetime
from typing import TypeVar
from timeline.api.query import Query

T = TypeVar('T')


class SQLiteRepository:
    def __init__(self, database: Path):
        self.conn = sqlite3.connect(database)
        self.conn.row_factory = sqlite3.Row

    def close(self):
        self.conn.close()

    def commit(self):
        self.conn.commit()


    def insert_event(self, event: Event):
        existing = self.find_duplicate_event(event)
        if existing is not None:
            event.id = existing.id
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

    def update(self, obj) -> None:
        if isinstance(obj, Event):
            duplicate = self.find_duplicate_event(obj, exclude_id=obj.id)
            if duplicate is not None:
                self._merge_events(duplicate.id, obj.id) # type: ignore[arg-type]
                obj.id = duplicate.id
                return

        self.conn.execute(
            obj.UPDATE_SQL,
            obj.to_db_tuple() + (obj.id,),
        )

    def get(self, model, id: int):
        row = self.conn.execute(
            f"SELECT * FROM {model.TABLE} WHERE id = ?",
            (id,),
        ).fetchone()

        return None if row is None else model.from_row(row)

    def delete(self, model, id: int):
        self.conn.execute(
            f"DELETE FROM {model.TABLE} WHERE id = ?",
            (id,),
        )

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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is None:
            self.commit()
        self.close()
