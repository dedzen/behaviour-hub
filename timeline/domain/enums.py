from enum import StrEnum


class DeviceSource(StrEnum):
    EMBED = "embed"
    PC = "pc"
    PHONE = "phone"


class EventKind(StrEnum):
    INTERVAL_START = "interval_start"
    INTERVAL_END = "interval_end"
    POINT = "point"
