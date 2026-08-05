from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
import re
from string import Formatter
from typing import Any


DEFAULT_TEMPLATE_PATH = Path(__file__).with_name("daily_note_template.md")
MISSING_VALUE = "Not available"
EMPTY_SECTION = "_None._"


@dataclass(frozen=True, slots=True)
class DailyNoteData:
    date: date | datetime | str
    tracked_time: str | None = None
    active_screen_time: str | None = None
    top_activity: str | None = None
    important_activities: Any = None
    screen_time_intersections: Any = None
    validation_status: str | None = None
    extras: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MarkdownRenderOptions:
    template_path: Path = DEFAULT_TEMPLATE_PATH
    missing_value: str = MISSING_VALUE
    empty_section: str = EMPTY_SECTION
    bullet: str = "-"
    date_format: str = "%Y-%m-%d"
    value_formatters: Mapping[str, Any] = field(default_factory=dict)


def render_daily_note_markdown(
    data: DailyNoteData | Mapping[str, Any],
    *,
    options: MarkdownRenderOptions | None = None,
    template: str | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> str:
    """Render a daily note Markdown document from template placeholders."""

    options = options or MarkdownRenderOptions()
    values = daily_note_values(data, options=options)
    values.update(overrides or {})

    if template is None:
        template = options.template_path.read_text(encoding="utf-8")

    rendered_values = {
        key: _format_placeholder_value(key, value, options)
        for key, value in values.items()
    }
    return _render_template(template, rendered_values, options.missing_value)


def daily_note_values(
    data: DailyNoteData | Mapping[str, Any],
    *,
    options: MarkdownRenderOptions | None = None,
) -> dict[str, Any]:
    options = options or MarkdownRenderOptions()
    raw = _data_to_dict(data)
    extras = raw.pop("extras", None) or {}
    raw_date = raw.get("date")

    values = {
        "date": _format_date(raw_date, options.date_format),
        "iso_date": _format_iso_date(raw_date),
        "iso_week": _format_iso_week(raw_date),
        "tracked_time": raw.get("tracked_time"),
        "active_screen_time": raw.get("active_screen_time"),
        "top_activity": raw.get("top_activity"),
        "important_activities": raw.get("important_activities"),
        "screen_time_intersections": raw.get("screen_time_intersections"),
        "validation_status": raw.get("validation_status"),
    }
    values.update(extras)
    return values


def _data_to_dict(data: DailyNoteData | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(data, DailyNoteData):
        return {
            "date": data.date,
            "tracked_time": data.tracked_time,
            "active_screen_time": data.active_screen_time,
            "top_activity": data.top_activity,
            "important_activities": data.important_activities,
            "screen_time_intersections": data.screen_time_intersections,
            "validation_status": data.validation_status,
            "extras": data.extras,
        }
    return dict(data)


def _render_template(
    template: str,
    values: Mapping[str, str],
    missing_value: str,
) -> str:
    normalized_template = _double_brace_template_to_format(template)
    placeholders = {
        field_name
        for _, field_name, _, _ in Formatter().parse(normalized_template)
        if field_name
    }
    filled_values = {
        placeholder: values.get(placeholder, missing_value)
        for placeholder in placeholders
    }
    return normalized_template.format_map(_SafeFormatMap(filled_values, missing_value)).rstrip() + "\n"


def _double_brace_template_to_format(template: str) -> str:
    return re.sub(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}", r"{\1}", template)


def _format_placeholder_value(
    key: str,
    value: Any,
    options: MarkdownRenderOptions,
) -> str:
    formatter = options.value_formatters.get(key)
    if formatter is not None:
        return str(formatter(value))

    if value is None or value == "":
        return options.missing_value if _is_inline_placeholder(key) else options.empty_section

    if isinstance(value, str):
        return value

    if isinstance(value, Mapping):
        return _format_mapping(value, options)

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return _format_sequence(value, options)

    return str(value)


def _format_mapping(value: Mapping[str, Any], options: MarkdownRenderOptions) -> str:
    if not value:
        return options.empty_section

    return "\n".join(
        f"{options.bullet} {key}: {_inline(value)}"
        for key, value in value.items()
    )


def _format_sequence(value: Sequence[Any], options: MarkdownRenderOptions) -> str:
    if not value:
        return options.empty_section

    lines = []
    for item in value:
        if isinstance(item, Mapping):
            label = _mapping_label(item)
            details = {
                key: value
                for key, value in item.items()
                if key not in {"label", "title", "name", "activity"}
            }
            if details:
                lines.append(f"{options.bullet} {label}: {_inline(details)}")
            else:
                lines.append(f"{options.bullet} {label}")
        else:
            lines.append(f"{options.bullet} {_inline(item)}")

    return "\n".join(lines)


def _mapping_label(item: Mapping[str, Any]) -> str:
    for key in ("label", "title", "activity", "name"):
        value = item.get(key)
        if value:
            return str(value)
    return "Item"


def _inline(value: Any) -> str:
    if isinstance(value, Mapping):
        return ", ".join(f"{key}: {value}" for key, value in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return ", ".join(str(item) for item in value)
    return str(value)


def _format_date(value: Any, date_format: str) -> str:
    if isinstance(value, datetime):
        return value.strftime(date_format)
    if isinstance(value, date):
        return value.strftime(date_format)
    if value is None:
        return MISSING_VALUE
    return str(value)


def _format_iso_date(value: Any) -> str | None:
    parsed = _date_value(value)
    if parsed is None:
        return None
    return parsed.isoformat()


def _format_iso_week(value: Any) -> str | None:
    parsed = _date_value(value)
    if parsed is None:
        return None
    iso = parsed.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _is_inline_placeholder(key: str) -> bool:
    return key in {
        "date",
        "tracked_time",
        "active_screen_time",
        "top_activity",
        "validation_status",
    }


class _SafeFormatMap(dict):
    def __init__(self, values: Mapping[str, str], missing_value: str):
        super().__init__(values)
        self.missing_value = missing_value

    def __missing__(self, key):
        return self.missing_value
