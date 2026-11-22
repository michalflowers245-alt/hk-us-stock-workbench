from __future__ import annotations

import os
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DATABASE_PATH = Path(os.getenv("HKUS_DATABASE", str(DATA_DIR / "market.sqlite3")))
if not DATABASE_PATH.is_absolute():
    DATABASE_PATH = (ROOT / DATABASE_PATH).resolve()
HOST = os.getenv("HKUS_HOST", "127.0.0.1")
PORT = int(os.getenv("HKUS_PORT", "8740"))
DATA_MODE = os.getenv("HKUS_DATA_MODE", "DEMO").upper()
RULE_CONFIG_PATH = ROOT / "config" / "strategy.json"
RULE_CONFIG = json.loads(RULE_CONFIG_PATH.read_text(encoding="utf-8"))
RULE_VERSION = str(RULE_CONFIG["version"])
DATA_REVISION = "demo-fixed-v1"
DEMO_SOURCE = "本机合成数据"

MARKETS = {
    "HK": {
        "name": "港股",
        "exchange": "XHKG",
        "exchange_name": "香港交易所",
        "timezone": "Asia/Hong_Kong",
        "currency": "HKD",
        "calendar": "XHKG",
        "rise_color": "#f06a71",
        "fall_color": "#55c6a4",
    },
    "US": {
        "name": "美股",
        "exchange": "XNYS",
        "exchange_name": "纽约证券交易所日历",
        "timezone": "America/New_York",
        "currency": "USD",
        "calendar": "XNYS",
        "rise_color": "#55c6a4",
        "fall_color": "#f06a71",
    },
}
