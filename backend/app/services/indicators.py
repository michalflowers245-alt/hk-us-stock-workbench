from __future__ import annotations

import pandas as pd
from ..config import RULE_CONFIG


def add_indicators(bars: pd.DataFrame) -> pd.DataFrame:
    frame = bars.sort_values("trading_date").reset_index(drop=True).copy()
    for window in RULE_CONFIG["moving_average_windows"]:
        frame[f"ma{window}"] = frame["close"].rolling(window=window, min_periods=window).mean()
    entry_window = RULE_CONFIG["entry"]["prior_high_window"]
    exit_window = RULE_CONFIG["exit"]["prior_low_window"]
    frame[f"high{entry_window}"] = frame["high"].shift(1).rolling(window=entry_window, min_periods=entry_window).max()
    frame[f"low{exit_window}"] = frame["low"].shift(1).rolling(window=exit_window, min_periods=exit_window).min()
    frame["average_turnover20"] = frame["turnover"].rolling(window=20, min_periods=20).mean()
    frame["previous_close"] = frame["close"].shift(1)
    frame["change_pct"] = (frame["close"] / frame["previous_close"] - 1) * 100
    return frame
