from __future__ import annotations

from datetime import date, datetime, timezone
from functools import lru_cache

import exchange_calendars as xcals
import pandas as pd

from ..config import MARKETS


@lru_cache(maxsize=2)
def get_calendar(market: str):
    if market not in MARKETS:
        raise ValueError(f"不支持的市场：{market}")
    return xcals.get_calendar(MARKETS[market]["calendar"])


def session_dates(market: str, start: date, end: date) -> list[date]:
    sessions = get_calendar(market).sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))
    return [pd.Timestamp(session).date() for session in sessions]


def session_schedule(market: str, start: date, end: date) -> list[dict]:
    timezone_name = MARKETS[market]["timezone"]
    calendar = get_calendar(market)
    schedule = calendar.schedule.loc[str(start):str(end)]
    result = []
    for session, row in schedule.iterrows():
        opened = pd.Timestamp(row["open"]).tz_convert(timezone_name)
        closed = pd.Timestamp(row["close"]).tz_convert(timezone_name)
        result.append({
            "date": pd.Timestamp(session).date().isoformat(),
            "open_local": opened.strftime("%H:%M"),
            "close_local": closed.strftime("%H:%M"),
            "open_utc": opened.tz_convert("UTC").isoformat(),
            "close_utc": closed.tz_convert("UTC").isoformat(),
            "is_half_day": (closed - opened).total_seconds() < 5 * 60 * 60,
        })
    return result


def latest_completed_session(market: str, now: datetime | None = None) -> date:
    calendar = get_calendar(market)
    now = now or datetime.now(timezone.utc)
    now_utc = pd.Timestamp(now).tz_convert("UTC") if pd.Timestamp(now).tzinfo else pd.Timestamp(now, tz="UTC")
    local_today = now_utc.tz_convert(MARKETS[market]["timezone"]).date()
    start = local_today - pd.Timedelta(days=14)
    schedule = calendar.schedule.loc[str(start):str(local_today)]
    if schedule.empty:
        return local_today
    closes = pd.to_datetime(schedule["close"], utc=True)
    complete = schedule.loc[closes <= now_utc]
    if complete.empty:
        prior = calendar.previous_session(pd.Timestamp(local_today))
        return pd.Timestamp(prior).date()
    return pd.Timestamp(complete.index[-1]).date()
