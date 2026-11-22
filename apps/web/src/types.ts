export type Market = 'HK' | 'US';
export type Page = 'overview' | 'opportunities' | 'instrument' | 'watchlist' | 'replay' | 'realtime';

export interface MarketStatus {
  market: Market;
  market_name: string;
  timezone: string;
  currency: string;
  expected_latest_session: string;
  latest_data_date: string | null;
  data_mode: 'DEMO';
  source: string;
  coverage_total: number;
  coverage_success: number;
  coverage_failed: number;
  is_current: boolean;
  snapshot: {
    snapshot_id: string;
    trading_date: string;
    created_at: string;
    status: string;
    rule_version: string;
  } | null;
}

export interface Instrument {
  instrument_id: string;
  market: Market;
  exchange: string;
  provider_symbol: string;
  display_symbol: string;
  name: string;
  currency: string;
  instrument_type: string;
  status: string;
  is_synthetic: boolean;
}

export interface Opportunity extends Instrument {
  trading_date: string;
  close: number;
  ma21: number | null;
  ma55: number | null;
  high20: number | null;
  low10: number | null;
  average_turnover20: number | null;
  turnover_type: string;
  signal: string | null;
  reason: string | null;
  change_pct: number | null;
  is_watched: number;
}

export interface ChartBar {
  trading_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  turnover: number;
  average_turnover20?: number | null;
  turnover_type: string;
  adjustment: string;
  ma5: number | null;
  ma13: number | null;
  ma21: number | null;
  ma34: number | null;
  ma55: number | null;
}

export interface ChartData {
  instrument: Instrument;
  bars: ChartBar[];
  signals: Array<{
    decision_date: string;
    confirmed_at: string;
    signal_type: string;
    reason: string;
    rule_version: string;
    simulated_status: string;
    thresholds: Record<string, number>;
  }>;
  history_count: number;
  as_of_date: string;
  date_basis: string;
  warnings: string[];
}

export interface WatchItem extends Instrument {
  note: string;
  added_at: string;
  close: number | null;
  change_pct: number | null;
  signal: string | null;
  trading_date: string | null;
}

export interface SimulationResult {
  simulation_id: string;
  instrument: Instrument;
  market: Market;
  currency: string;
  start_date: string;
  end_date: string;
  data_mode: 'DEMO';
  closed_trade_count: number;
  open_or_pending_count: number;
  win_rate_pct: number | null;
  total_return_pct: number;
  max_drawdown_pct: number;
  drawdown_basis: string;
  assumptions: string[];
  trades: Array<{
    entry_signal_date: string;
    entry_date: string | null;
    entry_price: number | null;
    exit_signal_date: string | null;
    exit_date: string | null;
    exit_price: number | null;
    return_pct: number | null;
    cost_pct: number;
    status: string;
    skip_reason: string | null;
  }>;
  equity_curve: Array<{ date: string; equity: number }>;
}
