"""Pure formatting for the stats embed's Uptime field."""

MINUTE = 60
HOUR = 3600
DAY = 86400
WEEK = 7 * DAY
MONTH = 30 * DAY


def format_uptime(seconds: int) -> str:
    months, weeks, days, hours, minutes = (
        seconds // MONTH,
        seconds // WEEK,
        seconds // DAY,
        seconds // HOUR,
        seconds // MINUTE,
    )

    if months >= 1:
        remainder = days - months * 30
        return f"{months}mo {remainder}d" if remainder else f"{months}mo"
    if weeks >= 1:
        remainder = days - weeks * 7
        return f"{weeks}w {remainder}d" if remainder else f"{weeks}w"
    if days >= 1:
        remainder = hours - days * 24
        return f"{days}d {remainder}h" if remainder else f"{days}d"
    if hours >= 1:
        remainder = minutes - hours * 60
        return f"{hours}h {remainder}m" if remainder else f"{hours}h"
    if minutes >= 1:
        remainder = seconds - minutes * 60
        return f"{minutes}m {remainder}s" if remainder else f"{minutes}m"
    return f"{seconds}s"
