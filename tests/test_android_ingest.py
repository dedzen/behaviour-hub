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

    def test_import_android_unlock_jsonl_uses_active_screen_events_by_default(self):
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

            self.assertEqual(result.strategy, "active_screen")
            self.assertEqual(result.ignored_events, 0)
            self.assertEqual(len(result.events), 2)
            self.assertEqual(result.events[0].device_source, DeviceSource.PHONE)
            self.assertEqual(result.events[0].event_kind, EventKind.INTERVAL_START)
            self.assertEqual(result.events[0].category, "Screen")
            self.assertEqual(result.events[0].name, "Screen on")
            self.assertIsNone(result.events[0].timestamp.tzinfo)
            self.assertEqual(result.events[1].event_kind, EventKind.INTERVAL_END)
            self.assertEqual(str(result.events[0].timestamp), "2026-08-01 09:00:01")
            self.assertEqual(str(result.events[1].timestamp), "2026-08-01 09:30:00")
            self.assertEqual(len(result.anomalies), 1)

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

            result = import_android_unlock_jsonl(path, strategy="keyguard")

            self.assertEqual(result.dropped_orphan_starts, 1)
            self.assertEqual(len(result.events), 2)
            self.assertEqual(str(result.events[0].timestamp), "2026-08-01 11:00:00")
            self.assertEqual(result.events[0].event_kind, EventKind.INTERVAL_START)
            self.assertEqual(result.events[1].event_kind, EventKind.INTERVAL_END)

    def test_active_screen_stops_at_first_screen_or_keyguard_end(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unlock-events.jsonl"
            path.write_text(
                "\n".join(
                    [
                        '{"timestamp":"2026-08-01T09:00:00+03:00","event":"SCREEN_INTERACTIVE"}',
                        '{"timestamp":"2026-08-01T09:00:05+03:00","event":"KEYGUARD_HIDDEN"}',
                        '{"timestamp":"2026-08-01T09:10:00+03:00","event":"SCREEN_NON_INTERACTIVE"}',
                        '{"timestamp":"2026-08-01T09:10:05+03:00","event":"KEYGUARD_SHOWN"}',
                    ]
                ),
                encoding="utf-8",
            )

            result = import_android_unlock_jsonl(path)

            self.assertEqual([event.event_kind for event in result.events], [
                EventKind.INTERVAL_START,
                EventKind.INTERVAL_END,
            ])
            self.assertEqual(str(result.events[0].timestamp), "2026-08-01 09:00:05")
            self.assertEqual(str(result.events[1].timestamp), "2026-08-01 09:10:00")

    def test_active_screen_suppresses_activity_between_shutdown_and_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unlock-events.jsonl"
            path.write_text(
                "\n".join(
                    [
                        '{"timestamp":"2026-08-01T09:00:00+03:00","event":"SCREEN_INTERACTIVE"}',
                        '{"timestamp":"2026-08-01T09:00:05+03:00","event":"KEYGUARD_HIDDEN"}',
                        '{"timestamp":"2026-08-01T09:02:00+03:00","event":"DEVICE_SHUTDOWN"}',
                        '{"timestamp":"2026-08-01T09:20:00+03:00","event":"SCREEN_INTERACTIVE"}',
                        '{"timestamp":"2026-08-01T09:20:00+03:00","event":"KEYGUARD_HIDDEN"}',
                        '{"timestamp":"2026-08-01T09:30:00+03:00","event":"DEVICE_STARTUP"}',
                        '{"timestamp":"2026-08-01T09:35:00+03:00","event":"KEYGUARD_SHOWN"}',
                    ]
                ),
                encoding="utf-8",
            )

            result = import_android_unlock_jsonl(path)

            self.assertEqual([event.event_kind for event in result.events], [
                EventKind.INTERVAL_START,
                EventKind.INTERVAL_END,
                EventKind.INTERVAL_START,
                EventKind.INTERVAL_END,
            ])
            self.assertEqual(str(result.events[0].timestamp), "2026-08-01 09:00:05")
            self.assertEqual(str(result.events[1].timestamp), "2026-08-01 09:02:00")
            self.assertEqual(str(result.events[2].timestamp), "2026-08-01 09:30:00")
            self.assertEqual(str(result.events[3].timestamp), "2026-08-01 09:35:00")

    def test_active_screen_treats_repeated_events_as_idempotent_anomalies(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unlock-events.jsonl"
            path.write_text(
                "\n".join(
                    [
                        '{"timestamp":"2026-08-01T09:00:00+03:00","event":"SCREEN_INTERACTIVE"}',
                        '{"timestamp":"2026-08-01T09:00:01+03:00","event":"SCREEN_INTERACTIVE"}',
                        '{"timestamp":"2026-08-01T09:00:02+03:00","event":"KEYGUARD_HIDDEN"}',
                        '{"timestamp":"2026-08-01T09:10:00+03:00","event":"KEYGUARD_SHOWN"}',
                    ]
                ),
                encoding="utf-8",
            )

            result = import_android_unlock_jsonl(path)

            self.assertEqual(len(result.events), 2)
            self.assertEqual(str(result.events[0].timestamp), "2026-08-01 09:00:02")
            self.assertEqual(str(result.events[1].timestamp), "2026-08-01 09:10:00")
            self.assertEqual(len(result.anomalies), 1)
            self.assertIn("repeated_screen_interactive", result.anomalies[0])

    def test_active_screen_drops_events_for_chunks_shorter_than_20_seconds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unlock-events.jsonl"
            path.write_text(
                "\n".join(
                    [
                        '{"timestamp":"2026-08-01T09:00:00+03:00","event":"SCREEN_INTERACTIVE"}',
                        '{"timestamp":"2026-08-01T09:00:01+03:00","event":"KEYGUARD_HIDDEN"}',
                        '{"timestamp":"2026-08-01T09:00:20+03:00","event":"SCREEN_NON_INTERACTIVE"}',
                        '{"timestamp":"2026-08-01T09:01:00+03:00","event":"SCREEN_INTERACTIVE"}',
                        '{"timestamp":"2026-08-01T09:01:01+03:00","event":"KEYGUARD_HIDDEN"}',
                        '{"timestamp":"2026-08-01T09:01:21+03:00","event":"SCREEN_NON_INTERACTIVE"}',
                    ]
                ),
                encoding="utf-8",
            )

            result = import_android_unlock_jsonl(path)

            self.assertEqual(result.dropped_short_chunks, 1)
            self.assertEqual(len(result.events), 2)
            self.assertEqual(str(result.events[0].timestamp), "2026-08-01 09:01:00")
            self.assertEqual(str(result.events[1].timestamp), "2026-08-01 09:01:21")

    def test_legacy_keyguard_strategy_also_drops_short_chunks_after_deciding_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unlock-events.jsonl"
            path.write_text(
                "\n".join(
                    [
                        '{"timestamp":"2026-08-01T09:00:00+03:00","event":"KEYGUARD_HIDDEN"}',
                        '{"timestamp":"2026-08-01T09:00:19+03:00","event":"KEYGUARD_SHOWN"}',
                        '{"timestamp":"2026-08-01T09:01:00+03:00","event":"KEYGUARD_HIDDEN"}',
                        '{"timestamp":"2026-08-01T09:01:20+03:00","event":"KEYGUARD_SHOWN"}',
                    ]
                ),
                encoding="utf-8",
            )

            result = import_android_unlock_jsonl(path, strategy="keyguard")

            self.assertEqual(result.dropped_short_chunks, 1)
            self.assertEqual(len(result.events), 2)
            self.assertEqual(str(result.events[0].timestamp), "2026-08-01 09:01:00")
            self.assertEqual(str(result.events[1].timestamp), "2026-08-01 09:01:20")

    def test_real_android_log_has_more_screen_than_keyguard_pairs(self):
        path = Path("data/android/unlock-events.jsonl")

        screen = import_android_unlock_jsonl(path, strategy="screen")
        keyguard = import_android_unlock_jsonl(path, strategy="keyguard")
        active_screen = import_android_unlock_jsonl(path)

        self.assertGreater(len(screen.events), len(keyguard.events))
        self.assertEqual(len(screen.events), 852)
        self.assertEqual(len(keyguard.events), 844)
        self.assertEqual(len(active_screen.events), 826)
        self.assertEqual(screen.dropped_orphan_starts, 2)
        self.assertEqual(keyguard.dropped_orphan_starts, 0)
        self.assertEqual(active_screen.dropped_orphan_starts, 0)
        self.assertEqual(screen.dropped_short_chunks, 333)
        self.assertEqual(keyguard.dropped_short_chunks, 214)
        self.assertEqual(active_screen.dropped_short_chunks, 232)
        self.assertEqual(len(active_screen.anomalies), 6)
        self.assertAlmostEqual(active_screen.unknown_time_seconds, 0.57)


if __name__ == "__main__":
    unittest.main()
