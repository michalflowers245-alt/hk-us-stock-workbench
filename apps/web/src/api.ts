import type { ChartData, Instrument, Market, Opportunity, SimulationResult, WatchItem } from './types';

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `请求失败 (${response.status})`);
  return data as T;
}

export const api = {
  overview: () => request<any>('/api/overview'),
  status: () => request<any>('/api/status'),
  instruments: (q = '', market?: Market) => request<{ items: Instrument[] }>(`/api/instruments?q=${encodeURIComponent(q)}${market ? `&market=${market}` : ''}`),
  opportunities: (market: Market, q = '', signal?: string, sort = 'signal') => request<{ items: Opportunity[] }>(`/api/opportunities?market=${market}&q=${encodeURIComponent(q)}${signal ? `&signal=${encodeURIComponent(signal)}` : ''}&sort=${encodeURIComponent(sort)}`),
  chart: (id: string, asOf?: string) => request<ChartData>(`/api/instruments/${encodeURIComponent(id)}/chart?limit=500${asOf ? `&as_of=${asOf}` : ''}`),
  watchlist: (market?: Market) => request<{ items: WatchItem[] }>(`/api/watchlist${market ? `?market=${market}` : ''}`),
  addWatch: (instrument_id: string, note = '') => request('/api/watchlist', { method: 'POST', body: JSON.stringify({ instrument_id, note }) }),
  removeWatch: (id: string) => request(`/api/watchlist/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  refresh: (market: Market | 'ALL' = 'ALL') => request<{ items: Array<{ status: string }> }>('/api/refresh', { method: 'POST', body: JSON.stringify({ market }) }),
  simulate: (instrument_id: string, start_date: string, fee_bps: number, slippage_bps: number) => request<SimulationResult>('/api/simulations', { method: 'POST', body: JSON.stringify({ instrument_id, start_date, fee_bps, slippage_bps }) }),
};
