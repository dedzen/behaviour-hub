from pathlib import Path
import tempfile
import unittest

from timeline.domain.enums import DeviceSource, EventKind
from timeline.ingest.android import import_android_unlock_jsonl, parse_android_timestamp


class AndroidIngestTest(unittest.TestCase):
    def test_parse_android_timestamp_returns_naive_local_datetime(self):
        parsed = parse_android_timestamp("2026-08-01T09:00:00+03:00")

        self.assertEqual(str(parsed), "2026-08-01 09:00:00")
        self.assertIsNone(parsed.tzinfo)

    def test_import_android_unlock_jsonl_uses_keyguard_events_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unlock-events.jsonl"
            path.write_text(
                "\n".join(
                    [
                        '{"timestamp":"2026-08-01T09:00:00+03:00","event":"SCREEN_INTERACTIVE"}',
                        '{"timestamp":"2026-08-01T09:00:01+03:00","event":"KEYGUARD_HIDDEN"}',
                        '{"timestamp":"2026-08-01T09:30:00+03:00","event":"SCREEN_NON_INTERACTIVE"}',
                        '{"timestamp":"2026-08-01T09:30:01+03:00","event":"KEYGUARD_SHOWN"}',
                        '{"timestamp":"2026-08-01T09:30:02+03:00","event":"DEVICE_STARTUP"}',
                    ]
                ),
                encoding="utf-8",
            )

            result = import_android_unlock_jsonl(path)

            self.assertEqual(result.strategy, "keyguard")
            self.assertEqual(result.ignored_events, 3)
            self.assertEqual(len(result.events), 2)
            self.assertEqual(result.events[0].device_source, DeviceSource.PHONE)
            self.assertEqual(result.events[0].event_kind, EventKind.INTERVAL_START)
            self.assertEqual(result.events[0].category, "Screen")
            self.assertEqual(result.events[0].name, "Screen on")
            self.assertIsNone(result.events[0].timestamp.tzinfo)
            self.assertEqual(result.events[1].event_kind, EventKind.INTERVAL_END)

    def test_import_android_unlock_jsonl_can_use_keyguard_strategy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unlock-events.jsonl"
            path.write_text(
                "\n".join(
                    [
                        '{"timestamp":"2026-08-01T09:00:00+03:00","event":"SCREEN_INTERACTIVE"}',
                        '{"timestamp":"2026-08-01T09:00:01+03:00","event":"KEYGUARD_HIDDEN"}',
                        '{"timestamp":"2026-08-01T09:30:01+03:00","event":"KEYGUARD_SHOWN"}',
                    ]
                ),
                encoding="utf-8",
            )

            result = import_android_unlock_jsonl(path, strategy="keyguard")

            self.assertEqual(result.ignored_events, 1)
            self.assertEqual([event.event_kind for event in result.events], [
                EventKind.INTERVAL_START,
                EventKind.INTERVAL_END,
            ])
            self.assertTrue(all(event.category == "Screen" for event in result.events))
            self.assertTrue(all(event.name == "Screen on" for event in result.events))

    def test_import_android_unlock_jsonl_replaces_orphan_start_on_repeated_start(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unlock-events.jsonl"
            path.write_text(
                "\n".join(
                    [
                        '{"timestamp":"2026-08-01T09:00:00+03:00","event":"KEYGUARD_HIDDEN"}',
                        '{"timestamp":"2026-08-01T11:00:00+03:00","event":"KEYGUARD_HIDDEN"}',
                        '{"timestamp":"2026-08-01T11:05:00+03:00","event":"KEYGUARD_SHOWN"}',
                    ]
                ),
                encoding="utf-8",
            )

            result = import_android_unlock_jsonl(path)

            self.assertEqual(result.dropped_orphan_starts, 1)
            self.assertEqual(len(result.events), 2)
            self.assertEqual(str(result.events[0].timestamp), "2026-08-01 11:00:00")
            self.assertEqual(result.events[0].event_kind, EventKind.INTERVAL_START)
            self.assertEqual(result.events[1].event_kind, EventKind.INTERVAL_END)

    def test_real_android_log_has_more_screen_than_keyguard_pairs(self):
        path = Path("data/android/unlock-events.jsonl")

        screen = import_android_unlock_jsonl(path, strategy="screen")
        keyguard = import_android_unlock_jsonl(path, strategy="keyguard")

        self.assertGreater(len(screen.events), len(keyguard.events))
        self.assertEqual(len(screen.events), 1518)
        self.assertEqual(len(keyguard.events), 1272)
        self.assertEqual(screen.dropped_orphan_starts, 2)
        self.assertEqual(keyguard.dropped_orphan_starts, 0)


if __name__ == "__main__":
    unittest.main()
