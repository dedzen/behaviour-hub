from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from timeline.application.mutations import TimelineMutationService
from timeline.storage.repository import SQLiteRepository


class ImportPreviewTest(unittest.TestCase):
    def test_embed_preview_is_read_only_and_reports_duplicates(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "timeline.db"
            csv = root / "events.csv"
            csv.write_text(
                "timestamp,event,task\n"
                "2026-08-01T09:00:00,start,Work: Focus\n"
                "2026-08-01T10:00:00,end,Work: Focus\n",
                encoding="utf-8",
            )
            service = TimelineMutationService(database)
            service.initialize()

            preview = service.preview_embed(csv)

            self.assertEqual(preview.summary.total_events, 2)
            self.assertEqual(preview.summary.new_events, 2)
            self.assertEqual(preview.summary.duplicate_events, 0)
            self.assertEqual(preview.summary.first_timestamp, datetime(2026, 8, 1, 9))
            with SQLiteRepository(database) as repo:
                self.assertEqual(repo.load_events(), [])

            result = service.import_embed(csv)
            self.assertIsNotNone(result.import_summary)
            self.assertEqual(result.import_summary.new_events, 2)  # type: ignore[union-attr]

            duplicate_preview = service.preview_embed(csv)
            self.assertEqual(duplicate_preview.summary.new_events, 0)
            self.assertEqual(duplicate_preview.summary.duplicate_events, 2)

    def test_preview_reports_parse_line_without_mutating_database(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "timeline.db"
            csv = root / "events.csv"
            csv.write_text(
                "timestamp,event,task\nnot-a-date,start,Work: Focus\n",
                encoding="utf-8",
            )
            service = TimelineMutationService(database)
            service.initialize()

            with self.assertRaisesRegex(ValueError, "line 2"):
                service.preview_embed(csv)
            with SQLiteRepository(database) as repo:
                self.assertEqual(repo.load_events(), [])


if __name__ == "__main__":
    unittest.main()
