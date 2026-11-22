from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from typing import Any
from urllib.parse import urlencode
import uuid
from zoneinfo import ZoneInfo

import httpx
import keyring
from websockets.asyncio.client import connect

from ..config import DATA_DIR, MARKETS
from ..database import connect as connect_db


API_ROOT = "https://webapi.futunn.com"
QUOTE_WS = "wss://webapi-quote.futunn.com/ws"
KEYRING_SERVICE = "hk-us-stock-workbench.futu"
CLIENT_FILE = DATA_DIR / "futu-client.json"
PENDING_FILE = DATA_DIR / "futu-oauth-pending.json"
SOURCE_NAME = "Futu OpenAPI"
WATCH_SYMBOLS = (
    {"symbol": "HK.800000", "name": "恒生指数", "market": "HK", "currency": "HKD"},
    {"symbol": "HK.800700", "name": "恒生科技指数", "market": "HK", "currency": "HKD"},
    {"symbol": "HK.800100", "name": "恒生中国企业指数", "market": "HK", "currency": "HKD"},
    {"symbol": "HK.00700", "name": "腾讯控股", "market": "HK", "currency": "HKD"},
    {"symbol": "HK.09988", "name": "阿里巴巴-W", "market": "HK", "currency": "HKD"},
    {"symbol": "HK.01810", "name": "小米集团-W", "market": "HK", "currency": "HKD"},
    {"symbol": "HK.03690", "name": "美团-W", "market": "HK", "currency": "HKD"},
)
SYMBOLS = tuple(item["symbol"] for item in WATCH_SYMBOLS)
SYMBOL_INFO = {item["symbol"]: item for item in WATCH_SYMBOLS}


class FutuError(RuntimeError):
    pass


class FutuPermissionError(FutuError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat(timespec="milliseconds")


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _quote_time_ms(data: dict[str, Any]) -> int | None:
    value = data.get("data_time_ms", data.get("data_time"))
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


class FutuRealtime:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._status: dict[str, Any] = {
            "provider": SOURCE_NAME,
            "state": "authorization_required",
            "connected": False,
            "authorized": False,
            "updated_at": None,
            "last_message_at": None,
            "last_error": None,
            "unavailable_symbols": [],
            "scope": None,
            "last_quote_at": None,
            "last_snapshot_at": None,
        }

    def _tokens(self) -> dict[str, Any] | None:
        try:
            value = keyring.get_password(KEYRING_SERVICE, "oauth_tokens")
            result = json.loads(value) if value else None
            return result if isinstance(result, dict) else None
        except Exception:
            self._status.update(state="storage_error", connected=False, last_error="无法读取 macOS 系统钥匙串。")
            return None

    def _save_tokens(self, tokens: dict[str, Any]) -> None:
        try:
            keyring.set_password(KEYRING_SERVICE, "oauth_tokens", json.dumps(tokens, separators=(",", ":")))
        except Exception as exc:
            self._status.update(state="storage_error", connected=False, last_error="无法安全保存 OAuth 授权，请检查 macOS 钥匙串。")
            raise FutuError("无法安全保存行情授权。请检查 macOS 钥匙串并重新授权。") from exc

    def _clear_tokens(self) -> None:
        try:
            keyring.delete_password(KEYRING_SERVICE, "oauth_tokens")
        except keyring.errors.PasswordDeleteError:
            pass

    def public_status(self) -> dict[str, Any]:
        tokens = self._tokens()
        result = dict(self._status)
        result["authorized"] = bool(tokens and tokens.get("refresh_token"))
        result["market_session"] = "continuous" if self._is_regular_hk_session(_utc_now()) else "closed"
        if tokens:
            result["scope"] = tokens.get("scope")
            result["refresh_expires_at"] = tokens.get("refresh_expires_at")
        return result

    async def start(self) -> None:
        tokens = self._tokens()
        if tokens and tokens.get("refresh_token"):
            self._start_worker()
        elif self._status.get("state") != "storage_error":
            self._status.update(state="authorization_required", connected=False, authorized=False)

    async def stop(self) -> None:
        if self._stop_event:
            self._stop_event.set()
        task, self._task = self._task, None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def _start_worker(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_forever(), name="futu-realtime-quotes")

    async def begin_authorization(self) -> str:
        client = _read_json(CLIENT_FILE)
        redirect_uri = "http://127.0.0.1:8740/api/realtime/oauth/callback"
        if not client or not client.get("client_id") or client.get("redirect_uri") != redirect_uri:
            payload = {
                "redirect_uris": [redirect_uri],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "client_name": "港美股工作台本机只读行情",
            }
            try:
                async with httpx.AsyncClient(timeout=20) as http:
                    response = await http.post(f"{API_ROOT}/oauth2/register", json=payload)
            except httpx.HTTPError as exc:
                raise FutuError("无法连接富途 OAuth 服务，请检查网络后重试。") from exc
            if response.status_code >= 400:
                raise FutuError("富途未接受本机 OAuth 客户端注册。")
            try:
                body = response.json()
            except ValueError as exc:
                raise FutuError("富途 OAuth 注册响应无法解析。") from exc
            client_id = body.get("client_id")
            if not client_id:
                raise FutuError("富途 OAuth 注册没有返回 client_id。")
            client = {"client_id": client_id, "redirect_uri": redirect_uri}
            _write_private_json(CLIENT_FILE, client)

        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        _write_private_json(PENDING_FILE, {
            "state": state,
            "verifier": verifier,
            "client_id": client["client_id"],
            "redirect_uri": redirect_uri,
            "created_at": time.time(),
        })
        query = urlencode({
            "client_id": client["client_id"],
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "quote:read",
            "state": state,
        })
        return f"{API_ROOT}/oauth2/authorize/confirm?{query}"

    async def complete_authorization(self, code: str, state: str) -> None:
        pending = _read_json(PENDING_FILE)
        if not pending or not secrets.compare_digest(str(pending.get("state", "")), state):
            raise FutuError("OAuth state 校验失败，请重新发起授权。")
        if time.time() - float(pending.get("created_at", 0)) > 600:
            PENDING_FILE.unlink(missing_ok=True)
            raise FutuError("授权请求已过期，请重新发起。")
        PENDING_FILE.unlink(missing_ok=True)
        try:
            async with httpx.AsyncClient(timeout=20) as http:
                response = await http.post(
                    f"{API_ROOT}/oauth2/token",
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "client_id": pending["client_id"],
                        "redirect_uri": pending["redirect_uri"],
                        "code_verifier": pending["verifier"],
                    },
                )
        except httpx.HTTPError as exc:
            raise FutuError("富途令牌交换网络请求失败；请重新发起授权。") from exc
        if response.status_code >= 400:
            raise FutuError("富途授权码换取令牌失败，请重新授权。")
        try:
            body = response.json()
        except ValueError as exc:
            raise FutuError("富途令牌响应无法解析；请重新发起授权。") from exc
        granted = set(str(body.get("scope", "")).split())
        if granted != {"quote:read"}:
            raise FutuPermissionError("授权范围不是仅行情读取；令牌未保存。请重新选择 quote:read。")
        access_token = body.get("access_token")
        refresh_token = body.get("refresh_token")
        if not access_token or not refresh_token:
            raise FutuError("授权响应缺少令牌；令牌未保存。")
        expires_in = int(body.get("expires_in", 7200))
        self._save_tokens({
            "client_id": pending["client_id"],
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": time.time() + expires_in,
            "refresh_expires_at": body.get("refresh_expires_at"),
            "scope": "quote:read",
        })
        self._status.update(
            state="connecting", connected=False, authorized=True,
            scope="quote:read", last_error=None, updated_at=_iso_now(),
        )
        self._start_worker()

    async def _refresh_access_token(self, tokens: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=20) as http:
            response = await http.post(
                f"{API_ROOT}/oauth2/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": tokens["refresh_token"],
                    "client_id": tokens["client_id"],
                },
            )
        if response.status_code >= 400:
            self._status.update(
                state="reauthorization_required", connected=False, last_error="富途授权令牌需要重新授权。",
                updated_at=_iso_now(),
            )
            raise FutuPermissionError("富途授权令牌需要重新授权。")
        body = response.json()
        updated = dict(tokens)
        updated["access_token"] = body.get("access_token")
        updated["expires_at"] = time.time() + int(body.get("expires_in", 7200))
        updated["scope"] = str(body.get("scope", tokens.get("scope", "")))
        if updated.get("scope") != "quote:read":
            raise FutuPermissionError("刷新后的授权范围与 quote:read 不符。")
        self._save_tokens(updated)
        return updated

    async def _ensure_access_token(self) -> tuple[dict[str, Any], bool]:
        tokens = self._tokens()
        if not tokens:
            raise FutuPermissionError("尚未完成富途行情授权。")
        if float(tokens.get("expires_at", 0)) <= time.time() + 600:
            return await self._refresh_access_token(tokens), True
        return tokens, False

    async def _fetch_quotes(self, access_token: str) -> tuple[list[dict[str, Any]], list[str]]:
        async with httpx.AsyncClient(timeout=20) as http:
            headers = {"Authorization": f"Bearer {access_token}"}

            async def request(codes: list[str]) -> tuple[int, list[dict[str, Any]]]:
                response = await http.post(
                    f"{API_ROOT}/api/v1.0/quote/stock-quote",
                    headers=headers,
                    json={"code_list": codes},
                )
                if response.status_code == 401:
                    raise FutuPermissionError("富途行情授权失效，需要刷新或重新授权。")
                if response.status_code >= 500:
                    raise FutuError(f"富途行情快照请求失败（HTTP {response.status_code}）。")
                try:
                    body = response.json()
                except ValueError as exc:
                    raise FutuError("富途行情快照响应无法解析。") from exc
                code = int(body.get("ret_code", -1))
                rows = body.get("data", {}).get("quote_list", []) if code == 0 else []
                return code, [row for row in rows if row.get("code")]

            code, rows = await request(list(SYMBOLS))
            if code == 0:
                received = {str(row["code"]): row for row in rows}
                return list(received.values()), [symbol for symbol in SYMBOLS if symbol not in received]

            # A single unsupported index or permission gap should not hide the other six symbols.
            received: dict[str, dict[str, Any]] = {}
            missing: list[str] = []
            for symbol in SYMBOLS:
                item_code, item_rows = await request([symbol])
                if item_code == 0 and item_rows:
                    received[str(item_rows[0]["code"])] = item_rows[0]
                else:
                    missing.append(f"{symbol}（错误码 {item_code}）")
            return list(received.values()), missing

    def _store_quote(self, symbol: str, data: dict[str, Any]) -> bool:
        info = SYMBOL_INFO.get(symbol)
        quote_time = _quote_time_ms(data)
        if not info or not quote_time:
            return False
        price = _numeric(data.get("last_price"))
        if price is None or price <= 0:
            return False
        name = str(data.get("sc_name") or data.get("name") or info["name"])
        previous = _numeric(data.get("prev_close_price"))
        received = _iso_now()
        session = "REGULAR"
        if isinstance(data.get("pre_market"), dict) and _numeric(data["pre_market"].get("price")):
            session = "PREMARKET"
        elif isinstance(data.get("after_market"), dict) and _numeric(data["after_market"].get("price")):
            session = "AFTERHOURS"
        elif isinstance(data.get("overnight"), dict) and _numeric(data["overnight"].get("price")):
            session = "OVERNIGHT"
        values = (
            symbol, name, info["market"], info["currency"], price, previous,
            _numeric(data.get("open_price")), _numeric(data.get("high_price")), _numeric(data.get("low_price")),
            _numeric(data.get("volume")), _numeric(data.get("turnover")), quote_time, received, SOURCE_NAME, session,
        )
        with connect_db() as db:
            db.execute(
                "INSERT INTO realtime_quotes(symbol,name,market,currency,last_price,prev_close_price,open_price,high_price,low_price,volume,turnover,quote_time_ms,received_at,source,session) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET "
                "name=excluded.name,market=excluded.market,currency=excluded.currency,last_price=excluded.last_price,"
                "prev_close_price=excluded.prev_close_price,open_price=excluded.open_price,high_price=excluded.high_price,"
                "low_price=excluded.low_price,volume=excluded.volume,turnover=excluded.turnover,quote_time_ms=excluded.quote_time_ms,"
                "received_at=excluded.received_at,source=excluded.source,session=excluded.session",
                values,
            )
        self._status["last_quote_at"] = received
        return True

    def _minute_snapshot(self) -> None:
        minute = _utc_now().replace(second=0, microsecond=0).isoformat()
        with connect_db() as db:
            rows = db.execute("SELECT * FROM realtime_quotes").fetchall()
            db.executemany(
                "INSERT INTO realtime_snapshots(symbol,snapshot_minute,name,market,currency,last_price,prev_close_price,open_price,high_price,low_price,volume,turnover,quote_time_ms,received_at,source,session) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol,snapshot_minute) DO UPDATE SET "
                "name=excluded.name,last_price=excluded.last_price,prev_close_price=excluded.prev_close_price,"
                "open_price=excluded.open_price,high_price=excluded.high_price,low_price=excluded.low_price,"
                "volume=excluded.volume,turnover=excluded.turnover,quote_time_ms=excluded.quote_time_ms,"
                "received_at=excluded.received_at,source=excluded.source,session=excluded.session",
                [
                    (row["symbol"], minute, row["name"], row["market"], row["currency"], row["last_price"],
                     row["prev_close_price"], row["open_price"], row["high_price"], row["low_price"], row["volume"],
                     row["turnover"], row["quote_time_ms"], _iso_now(), row["source"], row["session"])
                    for row in rows
                ],
            )

    def _is_regular_hk_session(self, now: datetime) -> bool:
        local = now.astimezone(ZoneInfo("Asia/Hong_Kong"))
        minute = local.hour * 60 + local.minute
        if local.weekday() >= 5 or not (570 <= minute < 720 or 780 <= minute < 960):
            return False
        try:
            from .calendar import get_calendar
            return bool(get_calendar("HK").is_open_on_minute(local, ignore_breaks=False))
        except Exception:
            return False

    async def _sample_loop(self) -> None:
        while True:
            now = _utc_now()
            seconds = 60 - now.second - now.microsecond / 1_000_000
            await asyncio.sleep(max(1, seconds))
            sample_time = _utc_now()
            if self._is_regular_hk_session(sample_time):
                self._minute_snapshot()
                self._status["last_snapshot_at"] = sample_time.replace(second=0, microsecond=0).isoformat()

    async def _receive_auth(self, websocket) -> dict[str, Any]:
        raw = await asyncio.wait_for(websocket.recv(), timeout=15)
        try:
            result = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise FutuError("富途 WebSocket 返回了无法识别的认证响应。") from exc
        if result.get("session_id"):
            return result
        code = result.get("code", result.get("ret_code", "unknown"))
        raise FutuPermissionError(f"富途 WebSocket 认证失败（错误码 {code}）。")

    async def _receive_subscribe_ack(self, websocket, request_id: str) -> None:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            raw = await asyncio.wait_for(websocket.recv(), timeout=max(1, deadline - time.monotonic()))
            try:
                result = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if result.get("type") == "QUOTE":
                self._store_quote(str(result.get("symbol", "")), result.get("data") or {})
                continue
            if result.get("id") != request_id:
                continue
            if int(result.get("code", -1)) != 0:
                code = result.get("code")
                if str(code) in {"-9", "-12009"}:
                    raise FutuPermissionError(f"富途报价订阅权限不足（错误码 {code}）。")
                raise FutuError(f"富途报价订阅失败（错误码 {code}）。")
            return
        raise FutuError("富途没有确认报价订阅。")

    async def _session(self) -> None:
        tokens, refreshed = await self._ensure_access_token()
        access_token = str(tokens["access_token"])
        if refreshed:
            tokens = self._tokens() or tokens
        async with connect(QUOTE_WS, ping_interval=20, ping_timeout=20, close_timeout=5) as websocket:
            await websocket.send(json.dumps({
                "id": "auth-" + uuid.uuid4().hex[:12],
                "action": "auth",
                "data": {"auth_type": "oauth2", "authorization": f"Bearer {access_token}"},
            }))
            await self._receive_auth(websocket)

            rows, missing = await self._fetch_quotes(access_token)
            for row in rows:
                if row.get("code"):
                    self._store_quote(str(row["code"]), row)
            subscribed = [str(row["code"]) for row in rows if row.get("code") in SYMBOL_INFO]
            if not subscribed:
                raise FutuPermissionError("富途没有返回可用的指数或股票报价；请检查行情权限和代码。")
            request_id = "sub-" + uuid.uuid4().hex[:12]
            await websocket.send(json.dumps({"id": request_id, "action": "subscribe", "quote": subscribed}))
            await self._receive_subscribe_ack(websocket, request_id)
            self._status.update(
                state="connected" if not missing else "connected_partial",
                connected=True, authorized=True, updated_at=_iso_now(), last_error=None,
                unavailable_symbols=missing, subscribed_symbols=subscribed, scope="quote:read",
            )

            sampler = asyncio.create_task(self._sample_loop(), name="futu-minute-snapshots")
            try:
                refresh_at = asyncio.get_running_loop().time() + 300
                while not (self._stop_event and self._stop_event.is_set()):
                    try:
                        timeout = max(0.1, refresh_at - asyncio.get_running_loop().time())
                        raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                    except TimeoutError:
                        raw = None
                    if asyncio.get_running_loop().time() >= refresh_at:
                        current, _ = await self._ensure_access_token()
                        access_token = str(current["access_token"])
                        await websocket.send(json.dumps({
                            "id": "refresh-" + uuid.uuid4().hex[:12],
                            "action": "refresh",
                            "data": {"authorization": f"Bearer {access_token}"},
                        }))
                        refresh_at = asyncio.get_running_loop().time() + 300
                    if raw is None:
                        continue
                    self._status["last_message_at"] = _iso_now()
                    try:
                        message = json.loads(raw)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if message.get("type") == "QUOTE":
                        self._store_quote(str(message.get("symbol", "")), message.get("data") or {})
                    elif message.get("code") not in (None, 0):
                        self._status["last_error"] = f"富途推送返回错误（错误码 {message.get('code')}）。"
            finally:
                sampler.cancel()
                try:
                    await sampler
                except asyncio.CancelledError:
                    pass

    async def _run_forever(self) -> None:
        delay = 2
        while not (self._stop_event and self._stop_event.is_set()):
            self._status["state"] = "connecting"
            self._status["connected"] = False
            try:
                await self._session()
                delay = 2
            except asyncio.CancelledError:
                raise
            except FutuPermissionError as exc:
                detail = str(exc)
                needs_auth = "重新授权" in detail or "尚未完成" in detail
                self._status.update(
                    state="reauthorization_required" if needs_auth else "permission_error",
                    connected=False, authorized=bool(self._tokens()), last_error=detail, updated_at=_iso_now(),
                )
                delay = 900
            except Exception as exc:
                self._status.update(
                    state="reconnecting", connected=False, last_error=str(exc)[:240], updated_at=_iso_now(),
                )
                delay = min(300, delay * 2)
            if self._stop_event and not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                except TimeoutError:
                    pass

    def quotes(self) -> list[dict[str, Any]]:
        with connect_db() as db:
            rows = db.execute("SELECT * FROM realtime_quotes ORDER BY CASE market WHEN 'HK' THEN 0 ELSE 1 END,symbol").fetchall()
        now_ms = int(time.time() * 1000)
        output = []
        for row in rows:
            item = dict(row)
            previous = item.get("prev_close_price")
            item["change_pct"] = ((item["last_price"] / previous) - 1) * 100 if previous else None
            item["quote_age_seconds"] = max(0, (now_ms - int(item["quote_time_ms"])) / 1000)
            item["quote_at"] = datetime.fromtimestamp(int(item["quote_time_ms"]) / 1000, timezone.utc).isoformat()
            try:
                received = datetime.fromisoformat(item["received_at"])
                item["received_age_seconds"] = max(0, (datetime.now(timezone.utc) - received.astimezone(timezone.utc)).total_seconds())
            except (TypeError, ValueError):
                item["received_age_seconds"] = None
            item["freshness"] = "fresh" if item["quote_age_seconds"] <= 120 else "stale"
            output.append(item)
        return output

    def history(self, symbol: str | None = None, limit: int = 2000) -> list[dict[str, Any]]:
        with connect_db() as db:
            if symbol:
                rows = db.execute(
                    "SELECT * FROM realtime_snapshots WHERE symbol=? ORDER BY snapshot_minute DESC LIMIT ?",
                    (symbol, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM realtime_snapshots ORDER BY snapshot_minute DESC,symbol LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]


futu_realtime = FutuRealtime()
