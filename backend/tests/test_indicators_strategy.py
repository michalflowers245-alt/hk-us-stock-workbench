import pandas as pd

from app.services.indicators import add_indicators
from app.services.strategy import evaluate


def bars_with_close(values):
    dates = pd.bdate_range("2025-01-02", periods=len(values))
    return pd.DataFrame([
        {"trading_date": dates[index].date().isoformat(), "open": value - 0.1, "high": value + 0.1,
         "low": value - 0.2, "close": value, "volume": 1000, "turnover": value * 1000}
        for index, value in enumerate(values)
    ])


def test_previous_20_high_excludes_current_bar_and_mas_have_warmup():
    bars = bars_with_close([50 + index * 0.1 for index in range(80)])
    bars.loc[79, "high"] = 10_000
    frame = add_indicators(bars)
    last = frame.iloc[-1]
    assert last["high20"] == frame.iloc[-21:-1]["high"].max()
    assert last["high20"] != frame.iloc[-20:]["high"].max()
    assert pd.isna(frame.iloc[53]["ma55"])
    assert not pd.isna(frame.iloc[54]["ma55"])
    assert not pd.isna(frame.iloc[-1]["ma21"])


def test_breakout_signal_fills_no_earlier_than_next_session_open():
    values = [50 + index * 0.18 for index in range(95)]
    frame = bars_with_close(values)
    prepared, signals, trades = evaluate(frame)
    assert signals
    first = signals[0]
    index = prepared.index[prepared["trading_date"] == first.decision_date][0]
    matching = next(trade for trade in trades if trade.entry_signal_date == first.decision_date)
    assert matching.entry_date == prepared.iloc[index + 1]["trading_date"]
    assert matching.entry_date != first.decision_date


def test_equal_to_prior_high_does_not_create_breakout():
    values = [50 + index * 0.1 for index in range(80)]
    frame = bars_with_close(values)
    equality_close = values[78]
    frame.loc[58:77, "high"] = equality_close
    prepared = add_indicators(frame)
    assert prepared.iloc[78]["close"] == prepared.iloc[78]["high20"]
    assert prepared.iloc[78]["ma21"] > prepared.iloc[78]["ma55"]
    _, signals, _ = evaluate(frame)
    assert all(signal.decision_date != prepared.iloc[78]["trading_date"] for signal in signals)


def test_final_day_entry_stays_pending_instead_of_being_filled_same_day():
    frame = bars_with_close([50.0] * 75 + [60.0])
    prepared, signals, trades = evaluate(frame)
    final_day = str(prepared.iloc[-1]["trading_date"])
    final_signal = next(signal for signal in signals if signal.decision_date == final_day)
    pending_trade = next(trade for trade in trades if trade.entry_signal_date == final_day)
    assert final_signal.signal_type == "突破观察"
    assert pending_trade.status == "pending"
    assert pending_trade.entry_date is None


def test_future_bars_do_not_change_prior_signal_history():
    values = [50.0] * 75 + [60.0, 48.0, 70.0, 30.0]
    complete = bars_with_close(values)
    cutoff = 75
    _, prefix_signals, _ = evaluate(complete.iloc[:cutoff + 1].copy())
    _, full_signals, _ = evaluate(complete)
    prefix = [signal for signal in prefix_signals if signal.decision_date <= complete.iloc[cutoff]["trading_date"]]
    full = [signal for signal in full_signals if signal.decision_date <= complete.iloc[cutoff]["trading_date"]]
    assert [(signal.decision_date, signal.signal_type) for signal in prefix] == [(signal.decision_date, signal.signal_type) for signal in full]
