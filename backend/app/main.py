from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
import csv
import json
from io import StringIO
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import DATA_MODE, DATA_REVISION, DEMO_SOURCE, HOST, MARKETS, PORT, RULE_VERSION
from .database import connect
from .services.calendar import latest_completed_session, session_schedule
from .services.indicators import add_indicators
from .services.market import _load_bars, initialize_demo, latest_snapshots, market_status, refresh_market, utc_now
from .services.simulation import get_simulation, run_simulation


ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "dist"
ALLOWED_ORIGINS = {f"http://127.0.0.1:{PORT}", "http://127.0.0.1:5173"}


class WatchBody(BaseModel):
    instrument_id: str
    note: str = Field(default="", max_length=300)


class RefreshBody(BaseModel):
    market: str = "ALL"


class SimulationBody(BaseModel):
    instrument_id: str
    start_date: date
    end_date: date | None = None
    fee_bps: float = Field(default=5, ge=0, le=500)
    slippage_bps: float = Field(default=5, ge=0, le=500)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if DATA_MODE != "DEMO":
        raise RuntimeError("当前版本只实现了 DEMO 合成数据模式。")
    initialize_demo()
    yield


app = FastAPI(
    title="港美股日终研究工作台",
    description="仅本机运行的港美股日终研究工具；默认 DEMO 合成数据，不提供交易功能。",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(ALLOWED_ORIGINS),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def local_only(request: Request, call_next):
    hostname = request.url.hostname
    if hostname not in {"127.0.0.1", "localhost", "testserver"}:
        return JSONResponse(status_code=400, content={"detail": "此工作台只接受本机连接。"})
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and origin not in ALLOWED_ORIGINS:
            return JSONResponse(status_code=403, content={"detail": "跨来源写入请求已拒绝。"})
    return await call_next(request)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "app": "hk-us-stock-workbench", "data_mode": DATA_MODE, "host": HOST, "port": PORT}


@app.get("/api/status")
def status() -> dict:
    markets = [market_status(market) for market in MARKETS]
    total = sum(item["coverage_total"] for item in markets)
    success = sum(item["coverage_success"] for item in markets)
    return {
        "application": "hk-us-stock-workbench",
        "data_mode": "DEMO",
        "source": DEMO_SOURCE,
        "rule_version": RULE_VERSION,
        "data_revision": DATA_REVISION,
        "adjustment": "未复权合成价格",
        "markets": markets,
        "coverage": {"total": total, "success": success, "failed": total - success},
        "watchlist_count": _watch_count(),
        "warnings": ["所有行情、证券名称与收益结果均为固定规则生成的合成演示数据。", "交易信号是研究观察标签，不是买卖指令。"],
    }


@app.get("/api/instruments")
def instruments(q: str = "", market: str | None = None) -> dict:
    if market and market not in MARKETS:
        raise HTTPException(400, "market 只支持 HK 或 US。")
    text = f"%{q.strip()}%"
    params: list[object] = [text, text]
    query = "SELECT * FROM instruments WHERE (display_symbol LIKE ? OR name LIKE ?)"
    if market:
        query += " AND market=?"
        params.append(market)
    query += " ORDER BY market, display_symbol LIMIT 100"
    with connect() as db:
        rows = db.execute(query, params).fetchall()
    items = [dict(row) for row in rows]
    return {"items": items, "count": len(items), **_metadata()}


@app.get("/api/snapshots/latest")
def snapshots_latest(market: str | None = None) -> dict:
    if market and market not in MARKETS:
        raise HTTPException(400, "market 只支持 HK 或 US。")
    snapshots = latest_snapshots(market)
    return {"items": snapshots, "count": len(snapshots), **_metadata(snapshots[0] if snapshots else None)}


@app.get("/api/opportunities")
def opportunities(
    market: str = "HK",
    snapshot_id: str | None = None,
    q: str = "",
    signal: str | None = None,
    sort: str = "signal",
    order: str = "desc",
) -> dict:
    if market not in MARKETS:
        raise HTTPException(400, "market 只支持 HK 或 US。")
    allowed_sort = {"signal", "change_pct", "average_turnover20", "display_symbol", "close"}
    if sort not in allowed_sort or order not in {"asc", "desc"}:
        raise HTTPException(400, "排序参数无效。")
    with connect() as db:
        if not snapshot_id:
            snapshot = db.execute("SELECT * FROM snapshots WHERE market=? ORDER BY created_at DESC LIMIT 1", (market,)).fetchone()
            snapshot_id = snapshot["snapshot_id"] if snapshot else None
        if not snapshot_id:
            return {"items": [], "count": 0, "snapshot_id": None, **_metadata()}
        rows = db.execute(
            "SELECT i.*, s.trading_date, s.created_at, s.data_mode, s.source, s.rule_version, s.data_revision, s.warnings_json, x.close, x.ma21, x.ma55, x.high20, x.low10, x.average_turnover20, x.turnover_type, x.signal, x.reason, x.change_pct, CASE WHEN w.instrument_id IS NULL THEN 0 ELSE 1 END AS is_watched FROM snapshot_items x JOIN snapshots s USING(snapshot_id) JOIN instruments i USING(instrument_id) LEFT JOIN watches w USING(instrument_id) WHERE s.snapshot_id=? AND s.market=?",
            (snapshot_id, market),
        ).fetchall()
    items = [dict(row) for row in rows]
    if q.strip():
        needle = q.strip().lower()
        items = [item for item in items if needle in item["display_symbol"].lower() or needle in item["name"].lower()]
    if signal:
        items = [item for item in items if item["signal"] == signal]
    if sort == "signal":
        rank = {"突破观察": 0, "退出观察": 1, None: 2}
        items.sort(key=lambda item: (rank.get(item["signal"], 3), item["change_pct"] or 0), reverse=(order == "asc"))
    else:
        items.sort(key=lambda item: (item[sort] is None, item[sort] or 0), reverse=(order == "desc"))
    meta_item = items[0] if items else None
    return {"items": items, "count": len(items), "snapshot_id": snapshot_id, **_metadata(meta_item)}


@app.get("/api/export/opportunities.csv")
def export_opportunities_csv(market: str = "HK") -> Response:
    if market not in MARKETS:
        raise HTTPException(400, "market 只支持 HK 或 US。")
    with connect() as db:
        snapshot = db.execute("SELECT * FROM snapshots WHERE market=? ORDER BY created_at DESC LIMIT 1", (market,)).fetchone()
        rows = db.execute(
            "SELECT i.display_symbol, i.name, i.market, i.currency, s.trading_date, x.close, x.average_turnover20, x.turnover_type, x.signal, x.reason, CASE WHEN w.instrument_id IS NULL THEN 0 ELSE 1 END AS is_watched, s.data_mode, s.source, s.rule_version, s.data_revision, s.input_fingerprint "
            "FROM snapshots s JOIN snapshot_items x USING(snapshot_id) JOIN instruments i USING(instrument_id) LEFT JOIN watches w USING(instrument_id) "
            "WHERE s.snapshot_id=? ORDER BY i.display_symbol",
            (snapshot["snapshot_id"],),
        ).fetchall() if snapshot else []
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["证券代码", "证券名称", "市场", "币种", "交易日", "收盘价", "20日平均成交额", "成交额口径", "规则信号", "信号理由", "自选", "数据模式", "来源", "规则版本", "数据修订", "输入指纹"])
    for row in rows:
        writer.writerow([
            row["display_symbol"], row["name"], row["market"], row["currency"], row["trading_date"], row["close"],
            row["average_turnover20"], row["turnover_type"], row["signal"] or "", row["reason"] or "",
            "是" if row["is_watched"] else "否", row["data_mode"], row["source"], row["rule_version"], row["data_revision"], row["input_fingerprint"],
        ])
    content = output.getvalue().encode("utf-8-sig")
    return Response(content, media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="opportunities-{market}.csv"',
        "X-Data-Mode": "DEMO",
        "X-Data-Warnings": "DEMO synthetic data; not real market quotes",
    })


@app.get("/api/instruments/{instrument_id}/chart")
def instrument_chart(
    instrument_id: str,
    as_of: date | None = None,
    limit: int = Query(default=250, ge=20, le=1000),
) -> dict:
    with connect() as db:
        instrument = db.execute("SELECT * FROM instruments WHERE instrument_id=?", (instrument_id,)).fetchone()
        if not instrument:
            raise HTTPException(404, "找不到该证券。")
        bars = _load_bars(db, instrument_id, end_date=as_of.isoformat() if as_of else None)
        if bars.empty:
            raise HTTPException(404, "该日期之前没有可用日线。")
        frame = add_indicators(bars).tail(limit).copy()
        cutoff = str(frame.iloc[-1]["trading_date"])
        signals = db.execute(
            "SELECT decision_date, confirmed_at, signal_type, reason, rule_version, data_revision, simulated_status, threshold_json FROM signals WHERE instrument_id=? AND decision_date<=? ORDER BY decision_date",
            (instrument_id, cutoff),
        ).fetchall()
    bars_out = []
    for _, row in frame.iterrows():
        item = {}
        for field in ("trading_date", "open", "high", "low", "close", "volume", "turnover", "turnover_type", "adjustment", "average_turnover20"):
            value = row.get(field)
            item[field] = None if pd.isna(value) else (str(value) if field == "trading_date" else value.item() if hasattr(value, "item") else value)
        for window in (5, 13, 21, 34, 55):
            value = row.get(f"ma{window}")
            item[f"ma{window}"] = None if pd.isna(value) else float(value)
        bars_out.append(item)
    signal_items = [dict(row, thresholds=json.loads(row["threshold_json"])) for row in signals]
    latest = bars_out[-1]
    metadata = _metadata({"trading_date": latest["trading_date"]})
    return {
        "instrument": dict(instrument),
        "bars": bars_out,
        "signals": signal_items,
        "history_count": len(bars),
        "as_of_date": latest["trading_date"],
        "date_basis": f"{MARKETS[instrument['market']]['timezone']} 市场交易日",
        **metadata,
        "warnings": ["演示数据，不代表真实行情。", "价格口径：未复权合成价格；图表与规则使用同一口径。"],
    }


@app.get("/api/watchlist")
def watchlist(market: str | None = None) -> dict:
    if market and market not in MARKETS:
        raise HTTPException(400, "market 只支持 HK 或 US。")
    query = "SELECT i.*, w.note, w.added_at, x.close, x.change_pct, x.signal, s.trading_date FROM watches w JOIN instruments i USING(instrument_id) LEFT JOIN snapshots s ON s.snapshot_id=(SELECT snapshot_id FROM snapshots s2 WHERE s2.market=i.market ORDER BY s2.created_at DESC LIMIT 1) LEFT JOIN snapshot_items x ON x.snapshot_id=s.snapshot_id AND x.instrument_id=i.instrument_id"
    params: tuple[object, ...] = ()
    if market:
        query += " WHERE i.market=?"
        params = (market,)
    query += " ORDER BY i.market, i.display_symbol"
    with connect() as db:
        rows = db.execute(query, params).fetchall()
    return {"items": [dict(row) for row in rows], "count": len(rows), **_metadata(rows[0] if rows else None)}


@app.post("/api/watchlist", status_code=201)
def add_watch(body: WatchBody) -> dict:
    with connect() as db:
        instrument = db.execute("SELECT instrument_id FROM instruments WHERE instrument_id=?", (body.instrument_id,)).fetchone()
        if not instrument:
            raise HTTPException(404, "请先从本工作台的证券目录选择标的。")
        db.execute("INSERT INTO watches(instrument_id, note, added_at) VALUES (?, ?, ?) ON CONFLICT(instrument_id) DO UPDATE SET note=excluded.note",
                   (body.instrument_id, body.note.strip(), utc_now()))
    return {"ok": True, "instrument_id": body.instrument_id}


@app.delete("/api/watchlist/{instrument_id}")
def remove_watch(instrument_id: str) -> dict:
    with connect() as db:
        cursor = db.execute("DELETE FROM watches WHERE instrument_id=?", (instrument_id,))
    if not cursor.rowcount:
        raise HTTPException(404, "该标的当前不在自选中。")
    return {"ok": True, "instrument_id": instrument_id}


@app.post("/api/refresh")
def refresh(body: RefreshBody) -> dict:
    markets = list(MARKETS) if body.market == "ALL" else [body.market]
    if any(market not in MARKETS for market in markets):
        raise HTTPException(400, "market 只支持 HK、US 或 ALL。")
    try:
        runs = [refresh_market(market) for market in markets]
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"本机演示数据刷新失败：{exc}") from exc
    return {"items": runs, "count": len(runs), "data_mode": "DEMO", "source": DEMO_SOURCE, "warnings": ["相同输入会沿用既有快照；刷新不会生成新的真实行情。"]}


@app.get("/api/trading-calendar")
def trading_calendar(market: str, start: date, end: date) -> dict:
    if market not in MARKETS:
        raise HTTPException(400, "market 只支持 HK 或 US。")
    if end < start or (end - start).days > 550:
        raise HTTPException(400, "日期范围无效，最多查询连续550天。")
    sessions = session_schedule(market, start, end)
    return {"market": market, "timezone": MARKETS[market]["timezone"], "sessions": sessions, "count": len(sessions), "calendar_source": "exchange_calendars 4.13.3"}


@app.post("/api/simulations", status_code=201)
def create_simulation(body: SimulationBody) -> dict:
    with connect() as db:
        instrument = db.execute("SELECT * FROM instruments WHERE instrument_id=?", (body.instrument_id,)).fetchone()
    if not instrument:
        raise HTTPException(404, "找不到该证券。")
    end_date = body.end_date or date.fromisoformat(market_status(instrument["market"])["latest_data_date"])
    if body.start_date >= end_date:
        raise HTTPException(400, "回放开始日必须早于结束日。")
    try:
        return run_simulation(body.instrument_id, body.start_date, end_date, body.fee_bps, body.slippage_bps)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/simulations/{simulation_id}")
def simulation(simulation_id: str) -> dict:
    result = get_simulation(simulation_id)
    if not result:
        raise HTTPException(404, "找不到该回放记录。")
    return result


@app.get("/api/overview")
def overview() -> dict:
    statuses = [market_status(market) for market in MARKETS]
    snapshots = latest_snapshots()
    with connect() as db:
        latest_items = []
        for snapshot in snapshots:
            rows = db.execute(
                "SELECT i.instrument_id, i.market, i.display_symbol, i.name, i.currency, x.close, x.change_pct, x.signal, x.reason, x.average_turnover20, x.turnover_type FROM snapshot_items x JOIN instruments i USING(instrument_id) WHERE x.snapshot_id=? ORDER BY CASE x.signal WHEN '突破观察' THEN 0 WHEN '退出观察' THEN 1 ELSE 2 END, ABS(COALESCE(x.change_pct, 0)) DESC LIMIT 5",
                (snapshot["snapshot_id"],),
            ).fetchall()
            latest_items.extend(dict(row) for row in rows)
    return {
        "markets": statuses,
        "snapshots": snapshots,
        "opportunities": latest_items,
        "watchlist_count": _watch_count(),
        "source_status": "DEMO",
        "data_mode": "DEMO",
        "source": DEMO_SOURCE,
        "rule_version": RULE_VERSION,
        "warnings": ["港股与美股样本均为合成数据，信号、成交额及回放收益仅用于功能演示。"],
    }


def _watch_count() -> int:
    with connect() as db:
        return db.execute("SELECT COUNT(*) AS n FROM watches").fetchone()["n"]


def _metadata(item=None) -> dict:
    trading_date = item.get("trading_date") if item and hasattr(item, "get") else None
    created_at = item.get("created_at") if item and hasattr(item, "get") else None
    warnings_json = item.get("warnings_json") if item and hasattr(item, "get") else None
    return {
        "data_mode": "DEMO",
        "source": item.get("source") if item and hasattr(item, "get") and item.get("source") else DEMO_SOURCE,
        "as_of_date": trading_date,
        "fetched_at": created_at or utc_now(),
        "rule_version": RULE_VERSION,
        "data_revision": item.get("data_revision") if item and hasattr(item, "get") and item.get("data_revision") else DATA_REVISION,
        "adjustment": "未复权合成价格",
        "warnings": json.loads(warnings_json) if warnings_json else ["所有数据均为合成演示数据。"],
    }


if DIST.exists() and (DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
else:
    @app.get("/")
    def dev_index():
        return JSONResponse({"message": "前端尚未构建。开发时请运行 npm run dev；发布启动前运行 npm run build。", "api": "/api/docs"})
