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

    def load_events(self, query: Query | None = None) -> list[Event]:
        return self._load_table(
                    "events",
                    Event,
                    timestamp_column="timestamp",
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
        query: Query | None = None,
    ) -> tuple[str, list]:
        query = query or Query()

        where, params = query.where_clause(
            timestamp_column=timestamp_column,
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
        query: Query | None = None,
    ) -> list[T]:

        sql, params = self._select_sql(
            table,
            timestamp_column=timestamp_column,
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
