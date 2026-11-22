import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, ArrowDownRight, ArrowUpRight, CheckCircle2, Clock3, Download, ExternalLink, RefreshCw, ShieldCheck, Wifi, WifiOff } from 'lucide-react';
import { api } from './api';

type RealtimeStatus = {
  provider: string;
  state: string;
  connected: boolean;
  authorized: boolean;
  scope?: string | null;
  last_error?: string | null;
  last_message_at?: string | null;
  last_quote_at?: string | null;
  latest_snapshot_minute?: string | null;
  stored_snapshot_count: number;
  quotes_count: number;
  fresh_quotes_count: number;
  subscribed_symbols?: string[];
  unavailable_symbols?: string[];
  symbols: Array<{ symbol: string; name: string }>;
  market_session?: 'continuous' | 'closed';
};

type Quote = {
  symbol: string;
  name: string;
  currency: string;
  last_price: number;
  prev_close_price: number | null;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  volume: number | null;
  turnover: number | null;
  quote_at: string;
  received_at: string;
  quote_age_seconds: number;
  freshness: 'fresh' | 'stale';
  session: string;
};

function time(value?: string | null) {
  if (!value) return '暂无';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '暂无';
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(date);
}

function price(value?: number | null, symbol = '') {
  if (value == null || !Number.isFinite(value)) return '—';
  const digits = value < 10 ? 3 : 2;
  const formatted = new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: digits }).format(value);
  return symbol.startsWith('HK.8') ? `${formatted} 点` : `HK$${formatted}`;
}

function pct(quote: Quote) {
  if (!quote.prev_close_price) return null;
  return (quote.last_price / quote.prev_close_price - 1) * 100;
}

function stateText(status?: RealtimeStatus | null) {
  if (!status) return '正在读取';
  if (status.state === 'connected') return '行情推送已连接';
  if (status.state === 'connected_partial') return '部分标的已连接';
  if (status.state === 'connecting') return '正在连接';
  if (status.state === 'reconnecting') return '断线重连中';
  if (status.state === 'permission_error') return '行情权限不足';
  if (status.state === 'reauthorization_required') return '需要重新授权';
  if (status.state === 'storage_error') return '本机安全存储不可用';
  return '等待只读授权';
}

export default function RealtimePage() {
  const [status, setStatus] = useState<RealtimeStatus | null>(null);
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [now, setNow] = useState(() => new Date());

  const reload = useCallback(async () => {
    try {
      const [nextStatus, nextQuotes] = await Promise.all([api.realtimeStatus(), api.realtimeQuotes()]);
      setStatus(nextStatus);
      setQuotes(nextQuotes.items);
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '行情状态读取失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
    const poll = window.setInterval(() => { void reload(); setNow(new Date()); }, 5000);
    return () => window.clearInterval(poll);
  }, [reload]);

  const bySymbol = useMemo(() => new Map(quotes.map((quote) => [quote.symbol, quote])), [quotes]);
  const connected = Boolean(status?.connected);

  return <div className="page-stack realtime-page">
    <section className="page-heading realtime-heading">
      <div><div className="eyebrow"><span className="eyebrow-line" />行情接入 / 只读</div><h1>实时行情<span className="heading-period">.</span></h1><p>行情由富途 OpenAPI 推送；分析与历史回放中的 DEMO 数据仍单独标记。</p></div>
      <div className="realtime-clock"><Clock3 size={15} /><span>{new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'medium', timeStyle: 'medium', hour12: false }).format(now)}</span><small>北京时间</small></div>
    </section>

    {error && <div className="alert alert--error"><span>{error}</span><button onClick={() => void reload()}><RefreshCw size={14} />重试</button></div>}

    <section className={`panel realtime-status-panel ${connected ? 'is-connected' : ''}`}>
      <div className="realtime-status-main">
        <span className={`realtime-status-icon ${connected ? 'is-connected' : ''}`}>{connected ? <Wifi size={19} /> : <WifiOff size={19} />}</span>
        <div><div className="section-kicker">FUTU OPENAPI</div><h2>{stateText(status)}</h2><p>{status?.authorized ? `授权范围：${status.scope || 'quote:read'} · 仅行情读取` : '尚未授权；点击后将在富途官方页面完成登录与授权'}</p></div>
      </div>
      <div className="realtime-status-actions">
        <a className="primary-button realtime-connect-button" href="/api/realtime/oauth/start"><ShieldCheck size={15} />{status?.authorized ? '重新打开授权页' : '连接富途行情'}<ExternalLink size={14} /></a>
        <button className="icon-button" onClick={() => void reload()} aria-label="刷新连接状态"><RefreshCw size={15} /></button>
      </div>
      <div className="realtime-status-metrics">
        <div><span>已接收标的</span><strong>{status?.quotes_count ?? 0} / {status?.symbols.length ?? 7}</strong></div>
        <div><span>新鲜报价</span><strong>{status?.fresh_quotes_count ?? 0}</strong></div>
        <div><span>已存分钟快照</span><strong>{(status?.stored_snapshot_count ?? 0).toLocaleString('zh-CN')}</strong></div>
        <div><span>最近行情接收</span><strong>{time(status?.last_quote_at)}</strong></div>
      </div>
      {(status?.last_error || status?.unavailable_symbols?.length) && <div className="realtime-error-note"><WifiOff size={14} />{status.last_error || `未返回报价：${status.unavailable_symbols?.join('、')}`}</div>}
    </section>

    {!status?.authorized && <section className="realtime-consent-note">
      <div className="consent-note-icon"><ShieldCheck size={17} /></div>
      <div><strong>只申请行情读取权限</strong><p>授权页面会显示本机应用名称和 <code>quote:read</code>。请勿选择账户资产、交易或下单权限；密码和验证码只在富途官方页面填写。</p></div>
      <a href="https://open.futunn.com/api/overview/getting-started" target="_blank" rel="noreferrer">官方权限说明 <ExternalLink size={13} /></a>
    </section>}

    <section className="panel realtime-quotes-panel">
      <div className="panel-heading"><div><div className="section-kicker">WATCHLIST / HK</div><h2>指数与自选报价 <small>7 个标的</small></h2></div><a className="text-action" href="/api/realtime/history.csv">导出分钟记录 <Download size={14} /></a></div>
      <div className="table-wrap"><table className="data-table realtime-table"><thead><tr><th>标的</th><th>最新价</th><th>涨跌幅</th><th>开盘</th><th>日内区间</th><th>行情时间</th><th>接收状态</th></tr></thead><tbody>
        {(status?.symbols || []).map((item) => {
          const quote = bySymbol.get(item.symbol);
          const change = quote ? pct(quote) : null;
          const fresh = quote?.freshness === 'fresh';
          return <tr key={item.symbol}>
            <td><span className={`realtime-symbol-tag ${item.symbol.startsWith('HK.8') ? 'index' : ''}`}>{item.symbol.startsWith('HK.8') ? '指数' : '港股'}</span><span className="realtime-symbol-name"><b>{item.name}</b><small>{item.symbol}</small></span></td>
            <td className="number-cell realtime-price-cell">{quote ? price(quote.last_price, quote.symbol) : '—'}</td>
            <td className={`number-cell ${change == null ? '' : change >= 0 ? 'tone-up' : 'tone-down'}`}>{change == null ? '—' : <><span className="change-arrow">{change >= 0 ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}</span>{change > 0 ? '+' : ''}{change.toFixed(2)}%</>}</td>
            <td className="number-cell">{quote ? price(quote.open_price, quote.symbol) : '—'}</td>
            <td className="number-cell">{quote ? `${price(quote.low_price, quote.symbol)} – ${price(quote.high_price, quote.symbol)}` : '—'}</td>
            <td><span className="realtime-time">{time(quote?.quote_at)}</span>{quote && <small className="realtime-age">{quote.quote_age_seconds < 60 ? `${Math.round(quote.quote_age_seconds)} 秒前` : `${Math.floor(quote.quote_age_seconds / 60)} 分钟前`}</small>}</td>
            <td>{quote ? <span className={`quote-freshness ${fresh ? 'fresh' : 'stale'}`}>{fresh ? <CheckCircle2 size={13} /> : <Clock3 size={13} />}{fresh ? '新鲜' : '较旧'}</span> : <span className="quote-freshness pending"><Clock3 size={13} />等待数据</span>}</td>
          </tr>;
        })}
      </tbody></table></div>
      {loading && <div className="realtime-loading"><span className="loading-orbit" />读取行情连接信息…</div>}
    </section>

    <div className="realtime-footnotes">
      <div><Activity size={14} /><span>{status?.market_session === 'continuous' ? '港股当前处于连续交易时段。' : '港股当前不在连续交易时段。'}分钟快照按港股连续交易时段保存；报价时间和本机接收时间分别记录。</span></div>
      <div><Clock3 size={14} /><span>免费本机方案的运行边界：Mac 睡眠或关机时采集会暂停；这台工作台没有云主机，因此不能在 Mac 关机后继续监测。</span></div>
      <div><ShieldCheck size={14} /><span>指数覆盖和实时权限以富途账号授权结果为准；没有权限的代码会显示具体缺失状态，不以演示行情填充。</span></div>
    </div>
  </div>;
}
