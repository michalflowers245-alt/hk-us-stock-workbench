from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
import random

import pandas as pd

from ..config import DATA_REVISION, DEMO_SOURCE, MARKETS
from .calendar import latest_completed_session, session_dates


@dataclass(frozen=True)
class Bar:
    trading_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    turnover: float
    turnover_type: str = "synthetic_estimate"
    adjustment: str = "unadjusted"


@dataclass(frozen=True)
class Instrument:
    instrument_id: str
    market: str
    exchange: str
    provider_symbol: str
    display_symbol: str
    name: str
    currency: str
    instrument_type: str = "EQUITY"
    status: str = "ACTIVE"
    is_synthetic: bool = True


class DataProvider:
    """行情供应商契约。真实供应商适配器尚未启用。"""

    name = "provider-base"
    data_mode = "REAL"

    def instruments(self, market: str) -> list[Instrument]:
        raise NotImplementedError

    def bars(self, instrument: Instrument, start: date, end: date) -> list[Bar]:
        raise NotImplementedError


class DemoProvider(DataProvider):
    name = DEMO_SOURCE
    data_mode = "DEMO"

    def __init__(self, today: date | None = None):
        self.today = today or date.today()
        self.start = date(self.today.year - 2, 1, 1)

    def instruments(self, market: str) -> list[Instrument]:
        if market not in MARKETS:
            raise ValueError(f"不支持的市场：{market}")
        market_config = MARKETS[market]
        return [
            Instrument(
                instrument_id=f"DEMO-{market}-{index:03d}",
                market=market,
                exchange=market_config["exchange"],
                provider_symbol=f"SYNTH.{market}.{index:03d}",
                display_symbol=f"SYN-{market}-{index:03d}",
                name=f"合成{market_config['name']}样本 {index:02d}",
                currency=market_config["currency"],
            )
            for index in range(1, 16)
        ]

    def bars(self, instrument: Instrument, start: date | None = None, end: date | None = None) -> list[Bar]:
        start = start or self.start
        completed = latest_completed_session(instrument.market)
        end = min(end or self.today, completed)
        dates = session_dates(instrument.market, start, end)
        seed = sum(ord(char) for char in instrument.instrument_id)
        rng = random.Random(seed)
        sample = int(instrument.instrument_id[-3:])
        base = 14.0 + sample * (0.75 if instrument.market == "HK" else 2.2)
        close = base
        bars: list[Bar] = []
        for offset, day in enumerate(dates):
            regime = 0.00075 if sample % 5 == 0 else (0.0002 if sample % 3 == 0 else -0.00003)
            cycle = 0.0075 * math.sin((offset + seed % 13) / (5.2 + sample % 4))
            noise = rng.uniform(-0.0065, 0.0065)
            close *= 1 + regime + cycle + noise
            gap = rng.uniform(-0.006, 0.006)
            open_price = close * (1 + gap)
            high = max(open_price, close) * (1 + rng.uniform(0.001, 0.018))
            low = min(open_price, close) * (1 - rng.uniform(0.001, 0.018))
            volume = rng.randint(120_000, 3_800_000) * (1 + sample % 4)
            currency_factor = 1.0 if instrument.market == "HK" else 1.0
            turnover = close * volume * currency_factor
            bars.append(Bar(day, round(open_price, 4), round(high, 4), round(low, 4), round(close, 4), volume, round(turnover, 2)))
        return bars


def normalize_bars(rows: list[Bar], instrument: Instrument, source: str, revision: str) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "trading_date": row.trading_date.isoformat(),
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "volume": row.volume,
            "turnover": row.turnover,
            "turnover_type": row.turnover_type,
            "source": source,
            "adjustment": row.adjustment,
            "data_revision": revision,
        }
        for row in rows
    ])
