from datetime import date


def test_demo_status_and_markets_are_explicit(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["data_mode"] == "DEMO"
    assert {market["market"] for market in data["markets"]} == {"HK", "US"}
    assert data["coverage"] == {"total": 30, "success": 30, "failed": 0}
    assert "合成" in data["warnings"][0]


def test_search_chart_and_snapshot_metadata(client):
    search = client.get("/api/instruments", params={"q": "SYN-HK-001", "market": "HK"}).json()
    instrument = search["items"][0]
    chart_response = client.get(f"/api/instruments/{instrument['instrument_id']}/chart", params={"limit": 250})
    assert chart_response.status_code == 200
    chart = chart_response.json()
    assert len(chart["bars"]) == 250
    assert chart["as_of_date"] == chart["bars"][-1]["trading_date"]
    assert all(signal["decision_date"] <= chart["as_of_date"] for signal in chart["signals"])
    assert chart["data_mode"] == "DEMO"
    assert chart["adjustment"] == "未复权合成价格"


def test_as_of_chart_has_no_future_bars_or_signals(client):
    instrument_id = "DEMO-US-001"
    cutoff = date(2025, 6, 30)
    response = client.get(f"/api/instruments/{instrument_id}/chart", params={"as_of": cutoff.isoformat(), "limit": 1000})
    assert response.status_code == 200
    data = response.json()
    assert all(bar["trading_date"] <= cutoff.isoformat() for bar in data["bars"])
    assert all(signal["decision_date"] <= cutoff.isoformat() for signal in data["signals"])


def test_watchlist_persists_deduplicates_and_removes(client):
    instrument_id = "DEMO-HK-002"
    first = client.post("/api/watchlist", json={"instrument_id": instrument_id, "note": "观察波动"})
    second = client.post("/api/watchlist", json={"instrument_id": instrument_id, "note": "留意成交额"})
    assert first.status_code == 201 and second.status_code == 201
    items = client.get("/api/watchlist", params={"market": "HK"}).json()["items"]
    matches = [item for item in items if item["instrument_id"] == instrument_id]
    assert len(matches) == 1
    assert matches[0]["note"] == "留意成交额"
    assert client.delete(f"/api/watchlist/{instrument_id}").status_code == 200


def test_cross_origin_write_is_rejected(client):
    response = client.post("/api/watchlist", json={"instrument_id": "DEMO-HK-003"}, headers={"Origin": "https://other.example"})
    assert response.status_code == 403


def test_non_loopback_host_is_rejected(client):
    response = client.get("http://192.0.2.10/api/status")
    assert response.status_code == 400


def test_refresh_is_idempotent_for_unchanged_input(client, db_path):
    import sqlite3
    before = client.get("/api/snapshots/latest", params={"market": "HK"}).json()["items"][0]["snapshot_id"]
    connection = sqlite3.connect(db_path)
    counts_before = connection.execute("SELECT (SELECT COUNT(*) FROM runs), (SELECT COUNT(*) FROM signals), (SELECT COUNT(*) FROM snapshots)").fetchone()
    connection.close()
    result = client.post("/api/refresh", json={"market": "HK"})
    assert result.status_code == 200
    assert result.json()["items"][0]["status"] == "unchanged"
    assert result.json()["data_mode"] == "DEMO"
    after = client.get("/api/snapshots/latest", params={"market": "HK"}).json()["items"][0]["snapshot_id"]
    assert before == after
    connection = sqlite3.connect(db_path)
    counts_after = connection.execute("SELECT (SELECT COUNT(*) FROM runs), (SELECT COUNT(*) FROM signals), (SELECT COUNT(*) FROM snapshots)").fetchone()
    connection.close()
    assert counts_before == counts_after


def test_hong_kong_display_symbol_preserves_leading_zero(client, db_path):
    import sqlite3
    connection = sqlite3.connect(db_path)
    connection.execute(
        "INSERT INTO instruments(instrument_id, market, exchange, provider_symbol, display_symbol, name, currency, instrument_type, status, is_synthetic) VALUES (?, 'HK', 'XHKG', ?, ?, ?, 'HKD', 'EQUITY', 'ACTIVE', 1)",
        ("DEMO-HK-ZERO", "00005.HK", "00005", "前导零演示证券"),
    )
    connection.commit()
    connection.close()
    response = client.get("/api/instruments", params={"q": "00005", "market": "HK"})
    assert response.status_code == 200
    assert response.json()["items"][0]["display_symbol"] == "00005"


def test_csv_export_marks_demo_mode_and_source(client):
    response = client.get("/api/export/opportunities.csv", params={"market": "HK"})
    assert response.status_code == 200
    assert response.headers["x-data-mode"] == "DEMO"
    assert "text/csv" in response.headers["content-type"]
    content = response.content.decode("utf-8-sig")
    assert "证券代码" in content.splitlines()[0]
    assert "DEMO" in content
    assert "本机合成数据" in content


def test_simulation_is_single_security_and_persists_result(client):
    result = client.post("/api/simulations", json={
        "instrument_id": "DEMO-HK-001", "start_date": "2025-01-06", "fee_bps": 5, "slippage_bps": 5,
    })
    assert result.status_code == 201, result.text
    data = result.json()
    assert data["market"] == "HK"
    assert data["data_mode"] == "DEMO"
    assert "不代表组合收益" in data["assumptions"][0]
    fetched = client.get(f"/api/simulations/{data['simulation_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["simulation_id"] == data["simulation_id"]


def test_company_action_blocks_affected_simulation(client, db_path):
    import sqlite3
    connection = sqlite3.connect(db_path)
    connection.execute(
        "INSERT INTO corporate_actions(action_id, instrument_id, action_type, effective_date, known_at, value_json, source, data_revision) VALUES ('test-action', 'DEMO-US-002', 'split', '2025-06-01', '2025-05-01T00:00:00Z', '{}', 'test', 'test-v1')"
    )
    connection.commit()
    connection.close()
    response = client.post("/api/simulations", json={"instrument_id": "DEMO-US-002", "start_date": "2025-01-06", "end_date": "2025-08-01"})
    assert response.status_code == 422
    assert "公司行动" in response.json()["detail"]


def test_trading_calendar_has_holidays_early_close_and_local_times(client):
    us = client.get("/api/trading-calendar", params={"market": "US", "start": "2026-11-26", "end": "2026-11-27"}).json()
    assert [item["date"] for item in us["sessions"]] == ["2026-11-27"]
    assert us["sessions"][0]["close_local"] == "13:00"
    assert us["sessions"][0]["is_half_day"] is True
    hk = client.get("/api/trading-calendar", params={"market": "HK", "start": "2026-12-24", "end": "2026-12-24"}).json()
    assert hk["sessions"][0]["close_local"] == "12:00"
    assert hk["sessions"][0]["is_half_day"] is True
