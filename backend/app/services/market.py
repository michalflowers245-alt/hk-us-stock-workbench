from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import threading
import time
import uuid

import pandas as pd

from ..config import DATA_MODE, DATA_REVISION, DEMO_SOURCE, MARKETS, RULE_CONFIG, RULE_VERSION
from ..database import connect, initialize
from .calendar import latest_completed_session
from .provider import DemoProvider
from .strategy import evaluate, signal_to_record


REFRESH_LOCK = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def initialize_demo() -> None:
    if DATA_MODE != "DEMO":
        raise RuntimeError("当前只实现了 DEMO 合成数据源；真实行情未获授权，不能切换为真实模式。")
    initialize()
    provider = DemoProvider()
    with connect() as db:
        for market in MARKETS:
            for instrument in provider.instruments(market):
                db.execute(
                    "INSERT OR IGNORE INTO instruments(instrument_id, market, exchange, provider_symbol, display_symbol, name, currency, instrument_type, status, is_synthetic) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                    (instrument.instrument_id, instrument.market, instrument.exchange, instrument.provider_symbol,
                     instrument.display_symbol, instrument.name, instrument.currency, instrument.instrument_type, instrument.status),
                )
                found = db.execute("SELECT COUNT(*) AS n FROM bars_raw WHERE instrument_id=? AND data_revision=?", (instrument.instrument_id, DATA_REVISION)).fetchone()["n"]
                if found:
                    continue
                bars = provider.bars(instrument)
                db.executemany(
                    "INSERT OR IGNORE INTO bars_raw(instrument_id, trading_date, open, high, low, close, volume, turnover, turnover_type, source, adjustment, data_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [(instrument.instrument_id, row.trading_date.isoformat(), row.open, row.high, row.low, row.close, row.volume,
                      row.turnover, row.turnover_type, DEMO_SOURCE, row.adjustment, DATA_REVISION) for row in bars],
                )
    for market in MARKETS:
        with connect() as db:
            exists = db.execute("SELECT 1 FROM snapshots WHERE market=? LIMIT 1", (market,)).fetchone()
        if not exists:
            refresh_market(market)


def _load_bars(db, instrument_id: str, end_date: str | None = None, start_date: str | None = None) -> pd.DataFrame:
    clauses = ["instrument_id=?", "data_revision=?", "valid=1"]
    params: list[object] = [instrument_id, DATA_REVISION]
    if end_date:
        clauses.append("trading_date<=?")
        params.append(end_date)
    if start_date:
        clauses.append("trading_date>=?")
        params.append(start_date)
    rows = db.execute(
        f"SELECT trading_date, open, high, low, close, volume, turnover, turnover_type, source, adjustment, data_revision FROM bars_raw WHERE {' AND '.join(clauses)} ORDER BY trading_date",
        params,
    ).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def refresh_market(market: str) -> dict:
    if market not in MARKETS:
        raise ValueError(f"不支持的市场：{market}")
    if not REFRESH_LOCK.acquire(blocking=False):
        raise RuntimeError("刷新任务正在运行，请等待当前任务结束。")
    started = time.perf_counter()
    run_id = str(uuid.uuid4())
    now = utc_now()
    try:
        with connect() as db:
            instruments = db.execute("SELECT * FROM instruments WHERE market=? ORDER BY display_symbol", (market,)).fetchall()
            fingerprint_rows = db.execute(
                "SELECT b.instrument_id, b.trading_date, b.open, b.high, b.low, b.close, b.volume, b.turnover, b.turnover_type, b.adjustment, b.valid, b.data_revision "
                "FROM bars_raw b JOIN instruments i USING(instrument_id) WHERE i.market=? AND b.data_revision=? "
                "ORDER BY b.instrument_id, b.trading_date",
                (market, DATA_REVISION),
            ).fetchall()
            fingerprint = hashlib.sha256(_json([tuple(row) for row in fingerprint_rows]).encode()).hexdigest()
            trading_date = max((row["trading_date"] for row in fingerprint_rows), default=latest_completed_session(market).isoformat())
            previous_run = db.execute(
                "SELECT run_id FROM runs WHERE market=? AND trading_date=? AND rule_version=? AND data_revision=? AND input_fingerprint=? AND status='success' ORDER BY started_at DESC LIMIT 1",
                (market, trading_date, RULE_VERSION, DATA_REVISION, fingerprint),
            ).fetchone()
            previous_snapshot = db.execute(
                "SELECT snapshot_id, status, coverage_success, coverage_total FROM snapshots WHERE market=? AND trading_date=? AND rule_version=? AND data_revision=? AND input_fingerprint=? AND status='success' ORDER BY created_at DESC LIMIT 1",
                (market, trading_date, RULE_VERSION, DATA_REVISION, fingerprint),
            ).fetchone()
        if previous_run and previous_snapshot:
            return {"run_id": previous_run["run_id"], "snapshot_id": previous_snapshot["snapshot_id"], "market": market,
                    "status": "unchanged", "covered": previous_snapshot["coverage_success"], "total": previous_snapshot["coverage_total"],
                    "trading_date": trading_date, "elapsed_ms": int((time.perf_counter() - started) * 1000)}

        with connect() as db:
            db.execute(
                "INSERT INTO runs(run_id, market, trading_date, rule_version, data_revision, requested_at, started_at, status, input_fingerprint) VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?)",
                (run_id, market, trading_date, RULE_VERSION, DATA_REVISION, now, now, fingerprint),
            )

        with connect() as db:
            instruments = db.execute("SELECT * FROM instruments WHERE market=? ORDER BY display_symbol", (market,)).fetchall()
            prepared = []
            for instrument in instruments:
                bars = _load_bars(db, instrument["instrument_id"])
                if len(bars) < int(RULE_CONFIG["warmup_bars"]):
                    continue
                frame, signals, _ = evaluate(bars)
                latest = frame.iloc[-1]
                signals_by_day = {signal.decision_date: signal for signal in signals}
                for signal in signals:
                    record = signal_to_record(signal, instrument["instrument_id"], RULE_VERSION, DATA_REVISION, now)
                    db.execute(
                        "INSERT OR IGNORE INTO signals(signal_id, instrument_id, decision_date, confirmed_at, signal_type, reason, rule_version, data_revision, simulated_status, threshold_json) VALUES (:signal_id, :instrument_id, :decision_date, :confirmed_at, :signal_type, :reason, :rule_version, :data_revision, :simulated_status, :threshold_json)",
                        record,
                    )
                latest_signal = signals_by_day.get(str(latest["trading_date"]))
                prior_close = latest.get("previous_close")
                prepared.append((instrument, latest, latest_signal, None if pd.isna(prior_close) else (float(latest["close"]) / float(prior_close) - 1) * 100))

            successful = len(prepared)
            snapshot_id = str(uuid.uuid4())
            status = "success" if successful == len(instruments) else ("partial" if successful else "failed")
            warnings = ["DEMO 合成行情，仅用于功能演示，不代表真实证券、历史行情或实际收益。", "成交额为收盘价×成交量估算值。"]
            db.execute(
                "INSERT INTO snapshots(snapshot_id, market, trading_date, created_at, status, rule_version, data_revision, input_fingerprint, data_mode, source, warnings_json, coverage_total, coverage_success, coverage_failed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (snapshot_id, market, trading_date, now, status, RULE_VERSION, DATA_REVISION, fingerprint, "DEMO", DEMO_SOURCE, _json(warnings), len(instruments), successful, len(instruments) - successful),
            )
            for instrument, latest, signal, change_pct in prepared:
                db.execute(
                    "INSERT INTO snapshot_items(snapshot_id, instrument_id, close, ma21, ma55, high20, low10, average_turnover20, turnover_type, signal, reason, change_pct) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (snapshot_id, instrument["instrument_id"], float(latest["close"]), _nullable_float(latest.get("ma21")),
                     _nullable_float(latest.get("ma55")), _nullable_float(latest.get("high20")), _nullable_float(latest.get("low10")),
                     _nullable_float(latest.get("average_turnover20")), str(latest.get("turnover_type", "synthetic_estimate")),
                     signal.signal_type if signal else None, signal.reason if signal else None, change_pct),
                )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            db.execute("UPDATE runs SET finished_at=?, status=?, elapsed_ms=?, error=? WHERE run_id=?",
                       (utc_now(), status, elapsed_ms, None if status == "success" else "部分证券历史不足", run_id))
        return {"run_id": run_id, "snapshot_id": snapshot_id, "market": market, "status": status,
                "covered": successful, "total": len(instruments), "trading_date": trading_date, "elapsed_ms": elapsed_ms}
    except Exception as exc:
        with connect() as db:
            db.execute("UPDATE runs SET finished_at=?, status='failed', error=?, elapsed_ms=? WHERE run_id=?",
                       (utc_now(), str(exc)[:500], int((time.perf_counter() - started) * 1000), run_id))
        raise
    finally:
        REFRESH_LOCK.release()


def _nullable_float(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def market_status(market: str) -> dict:
    with connect() as db:
        snapshot = db.execute("SELECT * FROM snapshots WHERE market=? ORDER BY created_at DESC LIMIT 1", (market,)).fetchone()
        instruments = db.execute("SELECT COUNT(*) AS n FROM instruments WHERE market=?", (market,)).fetchone()["n"]
        latest_data = db.execute("SELECT MAX(b.trading_date) AS d FROM bars_raw b JOIN instruments i USING(instrument_id) WHERE i.market=? AND b.data_revision=?", (market, DATA_REVISION)).fetchone()["d"]
    expected = latest_completed_session(market).isoformat()
    return {
        "market": market,
        "market_name": MARKETS[market]["name"],
        "timezone": MARKETS[market]["timezone"],
        "currency": MARKETS[market]["currency"],
        "expected_latest_session": expected,
        "latest_data_date": latest_data,
        "data_mode": "DEMO",
        "source": DEMO_SOURCE,
        "coverage_total": instruments,
        "coverage_success": snapshot["coverage_success"] if snapshot else 0,
        "coverage_failed": snapshot["coverage_failed"] if snapshot else instruments,
        "snapshot": _row_dict(snapshot) if snapshot else None,
        "is_current": bool(latest_data and latest_data >= expected),
    }


def _row_dict(row) -> dict | None:
    return dict(row) if row else None


def _snapshot_metadata(snapshot) -> dict:
    result = dict(snapshot)
    result["warnings"] = json.loads(result.pop("warnings_json", "[]"))
    result["as_of_date"] = result["trading_date"]
    result["fetched_at"] = result["created_at"]
    result["adjustment"] = "unadjusted synthetic prices"
    result["rule_version"] = RULE_VERSION
    return result


def latest_snapshots(market: str | None = None) -> list[dict]:
    with connect() as db:
        if market:
            row = db.execute("SELECT * FROM snapshots WHERE market=? ORDER BY created_at DESC LIMIT 1", (market,)).fetchone()
            rows = [row] if row else []
        else:
            rows = []
            for code in MARKETS:
                row = db.execute("SELECT * FROM snapshots WHERE market=? ORDER BY created_at DESC LIMIT 1", (code,)).fetchone()
                if row:
                    rows.append(row)
    return [_snapshot_metadata(row) for row in rows]
