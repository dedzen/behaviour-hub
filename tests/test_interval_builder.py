from datetime import datetime
import unittest

from timeline.domain.enums import DeviceSource, EventKind
from timeline.domain.interval_builder import IntervalBuilder
from timeline.domain.models import Event


def event(
    source: DeviceSource,
    kind: EventKind,
    hour: int,
    name: str,
    event_id: int,
) -> Event:
    return Event(
        id=event_id,
        timestamp=datetime(2026, 8, 1, hour),
        device_source=source,
        event_kind=kind,
        category="Activity",
        name=name,
    )


class IntervalBuilderTest(unittest.TestCase):
    def test_builds_overlapping_chunks_from_different_sources(self):
        chunks, warnings = IntervalBuilder.build(
            [
                event(DeviceSource.PC, EventKind.INTERVAL_START, 9, "Code", 1),
                event(DeviceSource.PHONE, EventKind.INTERVAL_START, 9, "Walk", 2),
                event(DeviceSource.PC, EventKind.INTERVAL_END, 10, "Code", 3),
                event(DeviceSource.PHONE, EventKind.INTERVAL_END, 10, "Walk", 4),
            ]
        )

        self.assertEqual(warnings, [])
        self.assertEqual(len(chunks), 2)
        self.assertEqual({chunk.source for chunk in chunks}, {DeviceSource.PC, DeviceSource.PHONE})

    def test_rejects_overlapping_intervals_from_same_source(self):
        chunks, warnings = IntervalBuilder.build(
            [
                event(DeviceSource.PC, EventKind.INTERVAL_START, 9, "Code", 1),
                event(DeviceSource.PC, EventKind.INTERVAL_START, 10, "Meeting", 2),
                event(DeviceSource.PC, EventKind.INTERVAL_END, 11, "Code", 3),
            ]
        )

        self.assertEqual(len(chunks), 1)
        self.assertIn("Duplicate start on pc", warnings[0])

    def test_rejects_end_that_does_not_match_active_interval_on_source(self):
        chunks, warnings = IntervalBuilder.build(
            [
                event(DeviceSource.PC, EventKind.INTERVAL_START, 9, "Code", 1),
                event(DeviceSource.PC, EventKind.INTERVAL_END, 10, "Meeting", 2),
                event(DeviceSource.PC, EventKind.INTERVAL_END, 11, "Code", 3),
            ]
        )

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].name, "Code")
        self.assertIn("End does not match active start on pc", warnings[0])


if __name__ == "__main__":
    unittest.main()
