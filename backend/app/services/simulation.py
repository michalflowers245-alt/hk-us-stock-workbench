from __future__ import annotations

from dataclasses import asdict
from datetime import date
import json
import uuid

import pandas as pd

from ..config import RULE_CONFIG, RULE_VERSION
from .market import _load_bars, connect, utc_now
from .strategy import evaluate


def run_simulation(
    instrument_id: str,
    start_date: date,
    end_date: date,
    fee_bps: float = 5,
    slippage_bps: float = 5,
) -> dict:
    with connect() as db:
        instrument = db.execute("SELECT * FROM instruments WHERE instrument_id=?", (instrument_id,)).fetchone()
        if not instrument:
            raise LookupError("找不到该证券。")
        action = db.execute(
            "SELECT action_type, effective_date FROM corporate_actions WHERE instrument_id=? AND effective_date BETWEEN ? AND ? LIMIT 1",
            (instrument_id, start_date.isoformat(), end_date.isoformat()),
        ).fetchone()
        if action:
            raise ValueError(f"区间内存在未处理公司行动（{action['action_type']}，{action['effective_date']}），本次回放已阻断。")
        bars = _load_bars(db, instrument_id, end_date=end_date.isoformat())

    if bars.empty:
        raise ValueError("该证券没有可用日线。")
    warmup_bars = int(RULE_CONFIG["warmup_bars"])
    if bars["trading_date"].lt(start_date.isoformat()).sum() < warmup_bars:
        raise ValueError(f"策略预热不足：开始日期前至少需要{warmup_bars}根有效日线。")

    frame, signals, trades = evaluate(
        bars,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        start_date=start_date.isoformat(),
    )
    frame = frame[frame["trading_date"] >= start_date.isoformat()].copy()
    trades = [trade for trade in trades if trade.entry_signal_date >= start_date.isoformat()]
    fee_rate = fee_bps / 10_000
    slip_rate = slippage_bps / 10_000
    cash = 1.0
    shares = 0.0
    equity_curve = []
    entry_dates = {trade.entry_date: trade for trade in trades if trade.entry_date}
    exit_dates = {trade.exit_date: trade for trade in trades if trade.exit_date}

    for _, bar in frame.iterrows():
        day = str(bar["trading_date"])
        if day in entry_dates and cash > 0:
            buy_price = float(bar["open"]) * (1 + slip_rate) * (1 + fee_rate)
            shares = cash / buy_price
            cash = 0.0
        if shares > 0 and day in exit_dates:
            cash = shares * float(bar["open"]) * (1 - slip_rate) * (1 - fee_rate)
            shares = 0.0
            equity = cash
        elif shares > 0:
            equity = shares * float(bar["close"])
        else:
            equity = cash
        equity_curve.append({"date": day, "equity": equity})

    equity_values = pd.Series([point["equity"] for point in equity_curve], dtype="float64")
    if equity_values.empty:
        raise ValueError("所选日期范围没有可回放的交易日。")
    running_peak = equity_values.cummax()
    drawdowns = (equity_values / running_peak - 1) * 100
    closed = [trade for trade in trades if trade.status == "closed"]
    signal_rows = [asdict(signal) for signal in signals if signal.decision_date >= start_date.isoformat()]
    simulation_id = str(uuid.uuid4())
    result = {
        "simulation_id": simulation_id,
        "instrument": dict(instrument),
        "market": instrument["market"],
        "currency": instrument["currency"],
        "start_date": start_date.isoformat(),
        "end_date": min(end_date.isoformat(), str(frame.iloc[-1]["trading_date"])),
        "rule_version": RULE_VERSION,
        "data_revision": "demo-fixed-v1",
        "data_mode": "DEMO",
        "fee_bps": fee_bps,
        "slippage_bps": slippage_bps,
        "assumptions": [
            "单标的、满仓复利的简化模拟，不代表组合收益。",
            "信号在收盘后确认，最早在下一交易日开盘执行。",
            "模拟成交以开盘价为基准，按假设费用与滑点扣减。",
            "回撤按逐日收盘估值；未包含日内路径、税费及未提供的公司行动。",
            "数据为合成演示数据，模拟收益不代表真实表现。",
        ],
        "closed_trade_count": len(closed),
        "open_or_pending_count": sum(trade.status in {"open", "pending", "pending_exit"} for trade in trades),
        "win_rate_pct": (sum((trade.return_pct or 0) > 0 for trade in closed) / len(closed) * 100) if closed else None,
        "total_return_pct": (float(equity_values.iloc[-1]) - 1) * 100,
        "max_drawdown_pct": float(drawdowns.min()),
        "drawdown_basis": "逐日收盘估值，开仓与平仓日按模拟执行价格和成本处理",
        "trades": [asdict(trade) for trade in trades],
        "signals": signal_rows,
        "equity_curve": equity_curve,
    }
    with connect() as db:
        db.execute(
            "INSERT INTO simulation_runs(simulation_id, instrument_id, market, start_date, end_date, rule_version, data_revision, fee_bps, slippage_bps, created_at, status, result_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'success', ?)",
            (simulation_id, instrument_id, instrument["market"], result["start_date"], result["end_date"], result["rule_version"],
             result["data_revision"], fee_bps, slippage_bps, utc_now(), json.dumps(result, ensure_ascii=False, allow_nan=False)),
        )
        for trade in trades:
            db.execute(
                "INSERT INTO trades(trade_id, simulation_id, instrument_id, entry_signal_date, entry_date, entry_price, exit_signal_date, exit_date, exit_price, return_pct, cost_pct, status, skip_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), simulation_id, instrument_id, trade.entry_signal_date, trade.entry_date, trade.entry_price,
                 trade.exit_signal_date, trade.exit_date, trade.exit_price, trade.return_pct, trade.cost_pct, trade.status, trade.skip_reason),
            )
    return result


def get_simulation(simulation_id: str) -> dict | None:
    with connect() as db:
        row = db.execute("SELECT result_json FROM simulation_runs WHERE simulation_id=?", (simulation_id,)).fetchone()
    return json.loads(row["result_json"]) if row else None
