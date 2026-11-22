from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
import uuid

import pandas as pd

from ..config import RULE_CONFIG
from .indicators import add_indicators


@dataclass
class Signal:
    decision_date: str
    signal_type: str
    reason: str
    close: float
    high20: float
    low10: float
    ma21: float
    ma55: float


@dataclass
class Trade:
    entry_signal_date: str
    entry_date: str | None = None
    entry_price: float | None = None
    exit_signal_date: str | None = None
    exit_date: str | None = None
    exit_price: float | None = None
    return_pct: float | None = None
    cost_pct: float = 0.0
    status: str = "pending"
    skip_reason: str | None = None


def evaluate(
    bars: pd.DataFrame,
    fee_bps: float = 0,
    slippage_bps: float = 0,
    start_date: str | None = None,
) -> tuple[pd.DataFrame, list[Signal], list[Trade]]:
    frame = add_indicators(bars)
    entry_rule = RULE_CONFIG["entry"]
    exit_rule = RULE_CONFIG["exit"]
    fast_ma = int(entry_rule["fast_average"])
    slow_ma = int(entry_rule["slow_average"])
    entry_high_field = f"high{int(entry_rule['prior_high_window'])}"
    exit_low_field = f"low{int(exit_rule['prior_low_window'])}"
    signals: list[Signal] = []
    trades: list[Trade] = []
    holding = False
    pending: dict[str, Any] | None = None
    active_trade: Trade | None = None

    for index, row in frame.iterrows():
        day = str(row["trading_date"])
        if start_date and day < start_date:
            continue
        if pending is not None and index == pending["execute_index"]:
            open_price = row.get("open")
            if pd.isna(open_price) or open_price is None:
                pending["trade"].status = "skipped"
                pending["trade"].skip_reason = "下一交易日无有效开盘价"
                trades.append(pending["trade"])
            elif pending["type"] == "entry":
                pending["trade"].entry_date = day
                pending["trade"].entry_price = float(open_price)
                pending["trade"].status = "holding"
                active_trade = pending["trade"]
                holding = True
            else:
                trade = pending["trade"]
                trade.exit_date = day
                trade.exit_price = float(open_price)
                fee_rate = fee_bps / 10_000
                slip_rate = slippage_bps / 10_000
                buy = trade.entry_price * (1 + slip_rate) * (1 + fee_rate)
                sell = trade.exit_price * (1 - slip_rate) * (1 - fee_rate)
                trade.return_pct = (sell / buy - 1) * 100
                trade.cost_pct = (1 - ((1 - slip_rate) * (1 - fee_rate)) / ((1 + slip_rate) * (1 + fee_rate))) * 100
                trade.status = "closed"
                trades.append(trade)
                active_trade = None
                holding = False
            pending = None

        high_threshold = row.get(entry_high_field)
        low_threshold = row.get(exit_low_field)
        fast_value = row.get(f"ma{fast_ma}")
        slow_value = row.get(f"ma{slow_ma}")
        values = (high_threshold, low_threshold, fast_value, slow_value)
        if index + 1 < int(RULE_CONFIG["warmup_bars"]) or any(pd.isna(value) for value in values):
            continue

        close = float(row["close"])
        high20 = float(high_threshold)
        low10 = float(low_threshold)
        ma21 = float(fast_value)
        ma55 = float(slow_value)
        next_index = index + 1
        if holding and active_trade is not None and pending is None:
            below_low = _compare(close, exit_rule["close_comparison"], low10)
            below_average = _compare(ma21, exit_rule["average_comparison"], ma55)
            if below_low or below_average:
                reason = f"收盘低于此前{exit_rule['prior_low_window']}日最低价" if below_low else f"MA{fast_ma} 低于 MA{slow_ma}"
                signal = Signal(day, "退出观察", reason, close, high20, low10, ma21, ma55)
                signals.append(signal)
                active_trade.exit_signal_date = day
                pending = {"type": "exit", "execute_index": next_index, "trade": active_trade}
        elif not holding and pending is None:
            if _compare(close, entry_rule["close_comparison"], high20) and _compare(ma21, entry_rule["average_comparison"], ma55):
                reason = f"收盘突破此前{entry_rule['prior_high_window']}日最高价且 MA{fast_ma} 高于 MA{slow_ma}"
                signal = Signal(day, "突破观察", reason, close, high20, low10, ma21, ma55)
                signals.append(signal)
                active_trade = Trade(entry_signal_date=day)
                pending = {"type": "entry", "execute_index": next_index, "trade": active_trade}

    if pending is not None and pending["type"] == "entry":
        pending["trade"].status = "pending"
        trades.append(pending["trade"])
    elif holding and active_trade is not None:
        active_trade.status = "open"
        if active_trade not in trades:
            trades.append(active_trade)
    elif pending is not None and pending["type"] == "exit":
        pending["trade"].status = "pending_exit"
        if pending["trade"] not in trades:
            trades.append(pending["trade"])

    return frame, signals, trades


def _compare(left: float, operator: str, right: float) -> bool:
    if operator == ">":
        return left > right
    if operator == "<":
        return left < right
    if operator == ">=":
        return left >= right
    if operator == "<=":
        return left <= right
    raise ValueError(f"不支持的策略比较符：{operator}")


def signal_to_record(signal: Signal, instrument_id: str, rule_version: str, revision: str, confirmed_at: str) -> dict[str, Any]:
    return {
        "signal_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{instrument_id}:{signal.decision_date}:{signal.signal_type}:{rule_version}:{revision}")),
        "instrument_id": instrument_id,
        "decision_date": signal.decision_date,
        "confirmed_at": confirmed_at,
        "signal_type": signal.signal_type,
        "reason": signal.reason,
        "rule_version": rule_version,
        "data_revision": revision,
        "simulated_status": "pending",
        "threshold_json": __import__("json").dumps({"close": signal.close, "high20": signal.high20, "low10": signal.low10, "ma21": signal.ma21, "ma55": signal.ma55}, ensure_ascii=False),
    }
