from math import isfinite

def human_duration(seconds: float | int | None) -> str:
    """Format a duration in seconds as a human-readable string."""

    if seconds is None:
        return "—"

    if not isfinite(seconds):
        return "—"

    total = int(round(seconds))

    if total < 0:
        return "-" + human_duration(-total)

    days, rem = divmod(total, 86_400)
    hours, rem = divmod(rem, 3_600)
    minutes, seconds = divmod(rem, 60)

    parts: list[str] = []

    if days:
        parts.append(f"{days}d")

    if hours:
        parts.append(f"{hours}h")

    if minutes:
        parts.append(f"{minutes}m")

    if seconds or not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts)