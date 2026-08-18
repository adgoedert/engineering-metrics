"""Elapsed-time helpers that ignore weekends."""

from datetime import datetime, timedelta

SATURDAY = 5


def business_days_between(start: datetime, end: datetime) -> float:
    """
    Fractional business days between two instants, counting only Mon-Fri.

    Walks the range one calendar day at a time and keeps the portion of each
    day that falls on a weekday, so partial first/last days stay accurate:
    a ticket opened Friday 18:00 and closed Monday 06:00 counts 0.5 days,
    not 3.
    """
    if end <= start:
        return 0.0

    total = 0.0
    cursor = start
    while cursor < end:
        next_midnight = (cursor + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        segment_end = min(next_midnight, end)
        if cursor.weekday() < SATURDAY:
            total += (segment_end - cursor).total_seconds() / 86400
        cursor = segment_end

    return total


def business_days_overlap(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> float:
    """Business days in the intersection of two intervals. 0 when disjoint."""
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    return business_days_between(start, end)
