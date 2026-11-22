import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity, ArrowLeft, ArrowRight, BarChart3, Bell, CalendarDays,
  Check, ChevronDown, CircleHelp, Clock3, Database, FileClock,
  Download, Filter, Gauge, Layers3, LineChart, ListFilter, Menu, RefreshCw, Search, Settings2, ShieldCheck,
  SlidersHorizontal, Star, Sun, Moon, X, Radio,
} from 'lucide-react';
import { api } from './api';
import PriceChart from './components/PriceChart';
import RealtimePage from './RealtimePage';
import type { ChartData, Instrument, Market, MarketStatus, Opportunity, Page, SimulationResult, WatchItem } from './types';

const navGroups = [
  { label: '研究', items: [
    { id: 'realtime' as Page, label: '实时行情', icon: Radio },
    { id: 'overview' as Page, label: '市场全景', icon: BarChart3 },
    { id: 'opportunities' as Page, label: '机会池', icon: Activity },
    { id: 'instrument' as Page, label: '个股分析', icon: LineChart },
  ] },
  { label: '策略', items: [
    { id: 'watchlist' as Page, label: '我的自选', icon: Star },
    { id: 'replay' as Page, label: '历史回放', icon: FileClock },
  ] },
];

const pageTitles: Record<Page, string> = {
  overview: '市场全景', opportunities: '机会池', instrument: '个股分析', watchlist: '我的自选', replay: '历史回放', realtime: '实时行情',
};

const maLabels = [5, 13, 21, 34, 55];

function formatDate(value?: string | null) {
  if (!value) return '—';
  const [year, month, day] = value.slice(0, 10).split('-');
  return `${year}.${month}.${day}`;
}

function formatTime(value?: string | null) {
  if (!value) return '—';
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));
}

function money(value?: number | null, currency = 'HKD') {
  if (value == null || !Number.isFinite(value)) return '—';
  const symbol = currency === 'HKD' ? 'HK$' : '$';
  return `${symbol}${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: value < 10 ? 3 : 2 }).format(value)}`;
}

function signedPercent(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function compactMoney(value?: number | null, currency = 'HKD') {
  if (value == null || !Number.isFinite(value)) return '—';
  const unit = currency === 'HKD' ? 'HK$' : '$';
  if (value >= 1e9) return `${unit}${(value / 1e9).toFixed(2)}B`;
  if (value >= 1e6) return `${unit}${(value / 1e6).toFixed(1)}M`;
  return `${unit}${(value / 1e3).toFixed(0)}K`;
}

function latestDailyText(status?: MarketStatus) {
  if (!status) return '读取中';
  if (!status.is_current) return '数据日期落后';
  return '最新完整交易日';
}

function signClass(value?: number | null, redUp = true) {
  if (value == null || value === 0) return 'tone-flat';
  const positive = value > 0;
  return positive === redUp ? 'tone-up' : 'tone-down';
}

function SignalTag({ value }: { value?: string | null }) {
  if (!value) return <span className="signal-tag signal-tag--quiet">观察中</span>;
  return <span className={`signal-tag ${value === '突破观察' ? 'signal-tag--up' : 'signal-tag--down'}`}>{value}</span>;
}

function EmptyState({ icon: Icon, title, detail, action }: { icon: typeof Search; title: string; detail: string; action?: React.ReactNode }) {
  return <div className="empty-state"><div className="empty-icon"><Icon size={19} /></div><strong>{title}</strong><span>{detail}</span>{action}</div>;
}

function EquitySparkline({ points }: { points: SimulationResult['equity_curve'] }) {
  if (points.length < 2) return <div className="equity-empty">生成回放结果后显示资金曲线</div>;
  const values = points.map((point) => point.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const width = 840;
  const height = 190;
  const path = values.map((value, index) => `${index ? 'L' : 'M'} ${(index / (values.length - 1) * width).toFixed(2)} ${(height - 12 - (value - min) / range * (height - 24)).toFixed(2)}`).join(' ');
  const last = values[values.length - 1];
  return <div className="equity-chart">
    <div className="equity-chart__axis"><span>1.00× 起始资金</span><span>结束 {last.toFixed(3)}×</span></div>
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="按交易日收盘估值的回放曲线">
      <defs><linearGradient id="equity-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#68d3bf" stopOpacity=".18" /><stop offset="100%" stopColor="#68d3bf" stopOpacity="0" /></linearGradient></defs>
      <path d={`${path} L ${width} ${height} L 0 ${height} Z`} fill="url(#equity-fill)" />
      <path d={path} fill="none" stroke="#68d3bf" strokeWidth="2.5" vectorEffect="non-scaling-stroke" />
    </svg>
    <div className="equity-chart__dates"><span>{formatDate(points[0].date)}</span><span>{formatDate(points[points.length - 1].date)}</span></div>
  </div>;
}

export default function App() {
  const [page, setPage] = useState<Page>('overview');
  const [market, setMarket] = useState<Market>('HK');
  const [overview, setOverview] = useState<any>(null);
  const [allInstruments, setAllInstruments] = useState<Instrument[]>([]);
  const [selectedId, setSelectedId] = useState('DEMO-HK-001');
  const [search, setSearch] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [isRefreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [redUp, setRedUp] = useState<boolean | null>(null);
  const [theme, setTheme] = useState<'dark' | 'light'>(() => localStorage.getItem('hkus-theme') === 'light' ? 'light' : 'dark');
  const [minute, setMinute] = useState(() => new Date());

  const loadOverview = useCallback(async () => {
    const [overviewResult, instrumentResult] = await Promise.all([api.overview(), api.instruments()]);
    setOverview(overviewResult);
    setAllInstruments(instrumentResult.items);
    setLoading(false);
  }, []);

  useEffect(() => {
    loadOverview().catch((reason: Error) => { setError(reason.message); setLoading(false); });
  }, [loadOverview]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('hkus-theme', theme);
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#0b1118' : '#f2f5f7');
  }, [theme]);

  useEffect(() => {
    const timer = window.setInterval(() => setMinute(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        document.querySelector<HTMLInputElement>('.global-search input')?.focus();
      }
    };
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, []);

  useEffect(() => {
    if (notice) {
      const timer = window.setTimeout(() => setNotice(''), 3200);
      return () => window.clearTimeout(timer);
    }
  }, [notice]);

  const searchResults = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return [];
    return allInstruments.filter((item) => item.display_symbol.toLowerCase().includes(needle) || item.name.toLowerCase().includes(needle)).slice(0, 7);
  }, [allInstruments, search]);
  const themeRedUp = redUp ?? market === 'HK';

  const refresh = async () => {
    setRefreshing(true);
    setError('');
    try {
      const result = await api.refresh('ALL');
      await loadOverview();
      setNotice(result.items.every((item) => item.status === 'unchanged') ? '演示数据无变化，已沿用最新快照' : '两市演示快照已更新');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '刷新失败');
    } finally {
      setRefreshing(false);
    }
  };

  const openInstrument = (id: string) => {
    setSelectedId(id);
    const instrument = allInstruments.find((item) => item.instrument_id === id);
    if (instrument) setMarket(instrument.market);
    setPage('instrument');
    setSearch('');
    setSearchOpen(false);
  };

  const selectPage = (nextPage: Page) => {
    setPage(nextPage);
    if (nextPage === 'instrument' && !selectedId) {
      const first = allInstruments.find((item) => item.market === market);
      if (first) setSelectedId(first.instrument_id);
    }
  };

  const activeInstrument = allInstruments.find((item) => item.instrument_id === selectedId);

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand-lockup">
        <div className="brand-mark"><span /><span /><span /></div>
        <div><strong>港美股 / 研究台</strong><small>本机行情与研究工作台</small></div>
      </div>
      <div className="workspace-pill"><span className="workspace-orbit"><Activity size={13} /></span><span><strong>个人研究空间</strong><small>本机工作区</small></span><ChevronDown size={14} /></div>
      <div className="nav-area">
        {navGroups.map((group) => <div className="nav-group" key={group.label}>
          <div className="nav-group__title">{group.label}</div>
          {group.items.map((item) => {
            const Icon = item.icon;
            return <button key={item.id} className={`nav-item ${page === item.id ? 'is-active' : ''}`} onClick={() => selectPage(item.id)} aria-current={page === item.id ? 'page' : undefined}>
              <Icon size={17} strokeWidth={1.8} /><span>{item.label}</span>{item.id === 'opportunities' && overview?.opportunities?.length > 0 && <i className="nav-count">{overview.opportunities.length}</i>}
            </button>;
          })}
        </div>)}
      </div>
      <div className="sidebar-bottom">
        <div className="source-card">
          <div className="source-card__top"><span className="pulse-dot" /><span>数据源状态</span><span className="source-mode">DEMO</span></div>
          <strong>研究数据：合成演示</strong>
          <p>实时行情单独接入，在「实时行情」页查看数据源和授权状态。</p>
        </div>
        <button className="nav-item nav-item--muted" onClick={() => setNotice('运行状态：本机 · 合成数据 · 只读研究')}><Settings2 size={17} /><span>工作台说明</span><CircleHelp size={14} className="nav-help" /></button>
        <div className="user-card"><div className="avatar">研</div><span><strong>个人研究员</strong><small>本机单用户</small></span><Menu size={16} /></div>
      </div>
    </aside>

    <div className="workspace">
      <header className="topbar">
        <div className="topbar__crumb"><span>研究终端</span><span className="crumb-slash">/</span><strong>{pageTitles[page]}</strong></div>
        <div className="topbar__tools">
          {page !== 'realtime' && <div className="global-search">
            <Search size={15} />
            <input aria-label="搜索证券代码或名称" value={search} onChange={(event) => { setSearch(event.target.value); setSearchOpen(true); }} onFocus={() => setSearchOpen(true)} onBlur={() => window.setTimeout(() => setSearchOpen(false), 120)} onKeyDown={(event) => { if (event.key === 'Enter' && searchResults[0]) openInstrument(searchResults[0].instrument_id); if (event.key === 'Escape') setSearchOpen(false); }} placeholder="搜索代码 / 名称" />
            <kbd>⌘ K</kbd>
            {searchOpen && search.trim() && <div className="search-dropdown">{searchResults.length ? searchResults.map((item) => <button key={item.instrument_id} onMouseDown={(event) => event.preventDefault()} onClick={() => openInstrument(item.instrument_id)}><span className="search-market">{item.market}</span><span><strong>{item.display_symbol}</strong><small>{item.name}</small></span><ArrowRight size={14} /></button>) : <div className="search-no-result">目录中没有匹配证券</div>}</div>}
          </div>}
          {page !== 'realtime' && <><span className="topbar-divider" />
          <div className="market-switch" role="group" aria-label="选择市场">
            <button className={market === 'HK' ? 'selected' : ''} onClick={() => { setMarket('HK'); setRedUp(null); }}>HK</button>
            <button className={market === 'US' ? 'selected' : ''} onClick={() => { setMarket('US'); setRedUp(null); }}>US</button>
          </div>
          <button className="icon-button tone-toggle" title="切换涨跌颜色" aria-label="切换涨跌颜色" onClick={() => setRedUp((current) => !(current ?? market === 'HK'))}><SlidersHorizontal size={16} /><span>{themeRedUp ? '红涨' : '绿涨'}</span></button>
          <button className="icon-button theme-toggle" aria-label={theme === 'dark' ? '切换浅色主题' : '切换深色主题'} title={theme === 'dark' ? '切换浅色主题' : '切换深色主题'} onClick={() => setTheme((current) => current === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}<span>{theme === 'dark' ? '浅色' : '深色'}</span></button>
          <span className="local-time"><Clock3 size={14} />{new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hour12: false }).format(minute)} <small>北京</small></span>
          <button className="icon-button notification-button" aria-label="数据说明" title="查看数据说明" onClick={() => setNotice('仅演示：所有价格、证券和信号均为合成数据')}><Bell size={16} /><i /></button>
          <button className="top-refresh" onClick={refresh} disabled={isRefreshing}><RefreshCw size={15} className={isRefreshing ? 'spin' : ''} /><span>{isRefreshing ? '计算中' : '重新计算'}</span></button>
          </>}
          {page === 'realtime' && <button className="icon-button theme-toggle" aria-label={theme === 'dark' ? '切换浅色主题' : '切换深色主题'} title={theme === 'dark' ? '切换浅色主题' : '切换深色主题'} onClick={() => setTheme((current) => current === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}<span>{theme === 'dark' ? '浅色' : '深色'}</span></button>}
        </div>
      </header>

      <main className="main-content">
        {error && <div className="alert alert--error"><span>{error}</span><button aria-label="关闭错误" onClick={() => setError('')}><X size={15} /></button></div>}
        {loading ? <div className="page-loading"><div className="loading-orbit" /><span>正在读取本机演示数据…</span></div> : <>
          {page === 'overview' && <OverviewPage overview={overview} market={market} setMarket={setMarket} redUp={themeRedUp} theme={theme} onOpenInstrument={openInstrument} onRefresh={refresh} onGoOpportunities={() => setPage('opportunities')} />}
          {page === 'opportunities' && <OpportunitiesPage market={market} setMarket={setMarket} redUp={themeRedUp} onOpenInstrument={openInstrument} />}
          {page === 'instrument' && activeInstrument && <InstrumentPage instrument={activeInstrument} redUp={themeRedUp} theme={theme} onWatch={() => api.addWatch(activeInstrument.instrument_id).then(() => setNotice('已加入自选')).catch((reason) => setError((reason as Error).message))} allInstruments={allInstruments} onSelect={setSelectedId} onBack={() => setPage('opportunities')} />}
          {page === 'watchlist' && <WatchlistPage market={market} setMarket={setMarket} redUp={themeRedUp} instruments={allInstruments} onOpenInstrument={openInstrument} onNotice={setNotice} />}
          {page === 'replay' && <ReplayPage market={market} instruments={allInstruments} onOpenInstrument={openInstrument} />}
          {page === 'realtime' && <RealtimePage />}
        </>}
      </main>
      <footer className="app-footer"><span><ShieldCheck size={13} />仅本机 · 只读研究</span><span>规则 <b>trend-breakout-v1</b></span><span>© 2026 港美股研究台</span></footer>
    </div>
    {notice && <div className="toast"><Check size={15} />{notice}</div>}
  </div>;
}

function OverviewPage({ overview, market, setMarket, redUp, theme, onOpenInstrument, onRefresh, onGoOpportunities }: {
  overview: any; market: Market; setMarket: (market: Market) => void; redUp: boolean; theme: 'dark' | 'light';
  onOpenInstrument: (id: string) => void; onRefresh: () => void; onGoOpportunities: () => void;
}) {
  const statuses = (overview?.markets || []) as MarketStatus[];
  const status = statuses.find((item) => item.market === market);
  const featured = overview?.opportunities?.find((item: Opportunity) => item.market === market) || overview?.opportunities?.[0];
  const [chart, setChart] = useState<ChartData | null>(null);
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  useEffect(() => {
    api.opportunities(market).then((response) => setOpportunities(response.items.slice(0, 5))).catch(() => setOpportunities([]));
    const firstId = featured?.instrument_id || (market === 'HK' ? 'DEMO-HK-001' : 'DEMO-US-001');
    api.chart(firstId).then(setChart).catch(() => setChart(null));
  }, [market, featured?.instrument_id]);

  return <div className="page-stack">
    <section className="page-heading page-heading--overview">
      <div><div className="eyebrow"><span className="eyebrow-line" />日终研究 / 01</div><h1>市场全景<span className="heading-period">.</span></h1><p>用可追溯的日终数据，检查结构、信号与自选变化。</p></div>
      <div className="heading-side"><div className="heading-status"><span className="status-ring"><span /></span><div><small>工作台状态</small><strong>本机运行 · 合成数据</strong></div></div><div className="heading-date"><CalendarDays size={15} /><span>演示日线至 {formatDate(status?.latest_data_date)}</span></div></div>
    </section>

    <section className="market-overview-grid">
      {statuses.map((item) => <button key={item.market} className={`market-panel ${market === item.market ? 'market-panel--selected' : ''}`} onClick={() => setMarket(item.market)}>
        <div className="market-panel__head"><span className={`market-code market-code--${item.market.toLowerCase()}`}>{item.market}</span><span className="market-state"><i />{latestDailyText(item)}</span><ArrowRight size={15} className="market-panel__arrow" /></div>
        <div className="market-panel__name">{item.market_name}<span>{item.market === 'HK' ? '香港 / HKT' : '美国 / ET'}</span></div>
        <div className="market-panel__date">{formatDate(item.latest_data_date)}<small>最新完整交易日</small></div>
        <div className="market-panel__foot"><span>证券覆盖 <b>{item.coverage_success} / {item.coverage_total}</b></span><span>数据时间 <b>{formatTime(item.snapshot?.created_at)} 北京</b></span></div>
        <div className="market-progress"><span style={{ width: `${item.coverage_total ? item.coverage_success / item.coverage_total * 100 : 0}%` }} /></div>
      </button>)}
    </section>

    <section className="overview-layout">
      <div className="panel chart-panel">
        <div className="panel-heading"><div><div className="section-kicker">当前个股</div><h2>{featured?.display_symbol || `SYN-${market}-001`} <small>{featured?.name || '合成样本'}</small></h2></div><button className="text-action" onClick={() => featured && onOpenInstrument(featured.instrument_id)}>打开个股 <ArrowRight size={14} /></button></div>
        {chart ? <>
          <div className="chart-summary"><div><strong>{money(chart.bars.at(-1)?.close, chart.instrument.currency)}</strong><span className={signClass(featured?.change_pct, redUp)}>{signedPercent(featured?.change_pct)}</span></div><span className="asof-chip">日线 · {formatDate(chart.as_of_date)}</span></div>
          <PriceChart data={chart} visibleMAs={[21, 55]} compact redUp={redUp} theme={theme} />
          <div className="chart-legend"><span><i className="legend-candle" />日K</span><span><i className="legend-ma legend-ma--21" />MA21</span><span><i className="legend-ma legend-ma--55" />MA55</span><span className="chart-legend__source">合成演示 / 未复权</span></div>
        </> : <div className="chart-placeholder"><div className="chart-placeholder__grid" /><span>读取图表…</span></div>}
      </div>

      <div className="panel signal-panel">
        <div className="panel-heading"><div><div className="section-kicker">规则信号 / V1</div><h2>机会观察</h2></div><span className="mini-count">{opportunities.filter((item) => item.signal).length.toString().padStart(2, '0')} <small>条</small></span></div>
        <p className="panel-caption">规则按收盘确认；模拟执行最早为下一交易日开盘。</p>
        <div className="signal-list">
          {opportunities.filter((item) => item.signal).slice(0, 4).map((item, index) => <button className="signal-row" key={item.instrument_id} onClick={() => onOpenInstrument(item.instrument_id)}>
            <span className={`signal-index ${item.signal === '突破观察' ? 'signal-index--up' : 'signal-index--down'}`}>{String(index + 1).padStart(2, '0')}</span>
            <span className="signal-row__main"><span><strong>{item.display_symbol}</strong><SignalTag value={item.signal} /></span><small>{item.reason}</small></span>
            <span className="signal-row__price"><b className={signClass(item.change_pct, redUp)}>{signedPercent(item.change_pct)}</b><small>{money(item.close, item.currency)}</small></span>
            <ArrowRight size={14} className="signal-row__arrow" />
          </button>)}
          {!opportunities.some((item) => item.signal) && <div className="no-signal"><Gauge size={18} /><span>当前样本没有满足规则的最新信号</span></div>}
        </div>
        <button className="signal-panel__link" onClick={onGoOpportunities}><span>查看全部机会</span><ArrowRight size={14} /></button>
      </div>
    </section>

    <section className="bottom-grid">
      <div className="panel snapshot-panel">
        <div className="panel-heading"><div><div className="section-kicker">最新快照</div><h2>快照与来源</h2></div><Database size={17} className="muted-icon" /></div>
        <div className="snapshot-meta-grid"><div><small>模式</small><strong><span className="demo-pill">DEMO</span>固定合成数据</strong></div><div><small>策略版本</small><strong>trend-breakout-v1</strong></div><div><small>规则计算时间</small><strong>{formatTime(status?.snapshot?.created_at)} 北京时间</strong></div><div><small>当前数据口径</small><strong>未复权 / 合成OHLCV</strong></div></div>
        <div className="data-warning"><CircleHelp size={15} /><span>行情、信号与回放结果仅演示功能；不代表真实证券或历史收益。</span></div>
      </div>
      <div className="panel quick-panel">
        <div className="panel-heading"><div><div className="section-kicker">研究快捷入口</div><h2>快速进入</h2></div><Layers3 size={17} className="muted-icon" /></div>
        <div className="quick-links"><button onClick={() => onOpenInstrument(featured?.instrument_id || `DEMO-${market}-001`)}><span className="quick-icon quick-icon--chart"><LineChart size={17} /></span><span><strong>分析个股</strong><small>查看日K、均线与规则理由</small></span><ArrowRight size={15} /></button><button onClick={() => onRefresh()}><span className="quick-icon quick-icon--refresh"><RefreshCw size={17} /></span><span><strong>更新演示快照</strong><small>重跑已存日线和规则</small></span><ArrowRight size={15} /></button></div>
      </div>
    </section>
  </div>;
}

function OpportunitiesPage({ market, setMarket, redUp, onOpenInstrument }: { market: Market; setMarket: (market: Market) => void; redUp: boolean; onOpenInstrument: (id: string) => void }) {
  const [items, setItems] = useState<Opportunity[]>([]);
  const [query, setQuery] = useState('');
  const [signal, setSignal] = useState('');
  const [sort, setSort] = useState('signal');
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    setLoading(true);
    api.opportunities(market, query, signal || undefined, sort).then((result) => setItems(result.items)).catch(() => setItems([])).finally(() => setLoading(false));
  }, [market, query, signal, sort]);
  const observed = items.filter((item) => item.signal).length;
  return <div className="page-stack">
    <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line" />规则扫描 / 02</div><h1>机会池<span className="heading-period">.</span></h1><p>白名单内的规则观察结果；按市场和快照日期分别查看。</p></div><div className="heading-side"><div className="heading-stat"><span>{items.length.toString().padStart(2, '0')}</span><small>演示覆盖标的</small></div><div className="heading-stat"><span>{observed.toString().padStart(2, '0')}</span><small>当前信号</small></div></div></section>
    <section className="panel opportunities-panel">
      <div className="table-toolbar"><div className="market-tabs"><button className={market === 'HK' ? 'selected' : ''} aria-pressed={market === 'HK'} onClick={() => setMarket('HK')}>HK <small>港股</small></button><button className={market === 'US' ? 'selected' : ''} aria-pressed={market === 'US'} onClick={() => setMarket('US')}>US <small>美股</small></button></div><div className="toolbar-spacer" /><div className="table-search"><Search size={15} /><input aria-label="过滤证券" placeholder="筛代码或名称" value={query} onChange={(event) => setQuery(event.target.value)} /></div><label className="select-control"><Filter size={14} /><select aria-label="信号筛选" value={signal} onChange={(event) => setSignal(event.target.value)}><option value="">全部观察</option><option value="突破观察">突破观察</option><option value="退出观察">退出观察</option></select><ChevronDown size={13} /></label><label className="select-control select-control--sort"><ListFilter size={14} /><select aria-label="排序方式" value={sort} onChange={(event) => setSort(event.target.value)}><option value="signal">信号优先</option><option value="change_pct">日变动</option><option value="average_turnover20">20日成交额</option><option value="display_symbol">代码</option></select><ChevronDown size={13} /></label><a className="soft-button export-link" aria-label="导出机会池CSV" href={`/api/export/opportunities.csv?market=${market}`} download={`opportunities-${market}.csv`}><Download size={14} />导出 CSV</a></div>
      <div className="table-wrap"><table className="data-table"><thead><tr><th>标的</th><th>收盘价 <span>· {market === 'HK' ? 'HKD' : 'USD'}</span></th><th>日变动</th><th>20日平均成交额</th><th>规则状态</th><th>理由</th><th>自选</th></tr></thead><tbody>
        {items.map((item, index) => <tr key={item.instrument_id} onClick={() => onOpenInstrument(item.instrument_id)} className="clickable-row"><td><button className="table-symbol table-symbol--button" aria-label={`分析 ${item.display_symbol}`} onClick={(event) => { event.stopPropagation(); onOpenInstrument(item.instrument_id); }}><i>{String(index + 1).padStart(2, '0')}</i><span><b>{item.display_symbol}</b><small>{item.name}</small></span></button></td><td className="number-cell">{money(item.close, item.currency)}</td><td className={`number-cell ${signClass(item.change_pct, redUp)}`}>{signedPercent(item.change_pct)}</td><td className="number-cell table-muted">{compactMoney(item.average_turnover20, item.currency)}<small>估算值</small></td><td><SignalTag value={item.signal} /></td><td className="reason-cell">{item.reason || '满足预热要求，等待规则触发'}</td><td>{item.is_watched ? <Star size={15} className="star-filled" fill="currentColor" /> : <Star size={15} className="muted-icon" />}</td></tr>)}
        {!loading && items.length === 0 && <tr><td colSpan={7}><EmptyState icon={Search} title="没有匹配的标的" detail="调整筛选条件，或查看另一个市场。" /></td></tr>}
        {loading && <tr><td colSpan={7} className="table-loading">读取机会池…</td></tr>}
      </tbody></table></div>
      <div className="table-footer"><span>覆盖 {items.length} / {items.length} · 仅合成白名单</span><span>“突破观察”与“退出观察”不是交易指令</span></div>
    </section>
    <div className="footnote-card"><ShieldCheck size={15} /><span>首版仅展示 30 个合成样本（港、美各 15 个）；流动性过滤未启用（阈值未配置），没有用户提供的证券名单前不添加真实标的。</span><span className="footnote-label">演示证券池</span></div>
  </div>;
}

function InstrumentPage({ instrument, redUp, theme, onWatch, allInstruments, onSelect, onBack }: { instrument: Instrument; redUp: boolean; theme: 'dark' | 'light'; onWatch: () => void; allInstruments: Instrument[]; onSelect: (id: string) => void; onBack: () => void }) {
  const [chart, setChart] = useState<ChartData | null>(null);
  const [loading, setLoading] = useState(true);
  const [visibleMAs, setVisibleMAs] = useState<number[]>([21, 55]);
  const [asOf, setAsOf] = useState('');
  const [chartError, setChartError] = useState('');
  useEffect(() => {
    setLoading(true);
    setChartError('');
    api.chart(instrument.instrument_id, asOf || undefined).then(setChart).catch((reason: Error) => { setChartError(reason.message); setChart(null); }).finally(() => setLoading(false));
  }, [instrument.instrument_id, asOf]);
  const latest = chart?.bars.at(-1);
  const recentSignals = chart?.signals.slice(-5).reverse() || [];
  const toggleMA = (window: number) => setVisibleMAs((items) => items.includes(window) ? items.filter((item) => item !== window) : [...items, window]);

  return <div className="page-stack">
    <section className="instrument-heading"><div className="instrument-heading__left"><button className="back-link" onClick={onBack}><ArrowLeft size={15} />返回机会池</button><div className="instrument-title-row"><span className="market-square">{instrument.market}</span><div><div className="eyebrow eyebrow--small">{instrument.exchange} / {instrument.currency}</div><h1>{instrument.display_symbol}<small>{instrument.name}</small></h1></div></div><div className="instrument-tags"><span className="demo-pill">DEMO</span><span>合成证券</span><span>未复权价格</span><span>日线</span></div></div>
      <div className="instrument-heading__right"><label className="instrument-select"><span>快速切换</span><select aria-label="切换证券" value={instrument.instrument_id} onChange={(event) => onSelect(event.target.value)}>{allInstruments.filter((item) => item.market === instrument.market).map((item) => <option value={item.instrument_id} key={item.instrument_id}>{item.display_symbol} · {item.name}</option>)}</select><ChevronDown size={14} /></label><button className="primary-outline" onClick={onWatch}><Star size={15} />加入自选</button></div>
    </section>

    <section className="instrument-stats">
      <div className="instrument-price"><small>最新收盘 <span>· {formatDate(latest?.trading_date)}</span></small><strong>{money(latest?.close, instrument.currency)}</strong><span className={`price-change ${signClass(latest ? (latest.close / (chart?.bars.at(-2)?.close || latest.close) - 1) * 100 : 0, redUp)}`}>{signedPercent(latest ? (latest.close / (chart?.bars.at(-2)?.close || latest.close) - 1) * 100 : null)} <small>较上个交易日</small></span></div>
      <div className="instrument-stat"><small>20日最高区间</small><strong>{money(latest ? Math.max(...(chart?.bars.slice(-20).map((bar) => bar.high) || [0])) : null, instrument.currency)}</strong><span>当前图表口径</span></div>
      <div className="instrument-stat"><small>20日平均成交额</small><strong>{compactMoney(latest?.average_turnover20, instrument.currency)}</strong><span>收盘价 × 成交量估算</span></div>
      <div className="instrument-stat"><small>规则版本</small><strong className="stat-rule">trend-breakout-v1</strong><span>只读 · 可解释</span></div>
    </section>

    <section className="panel instrument-chart-panel">
      <div className="panel-heading instrument-chart-heading"><div><div className="section-kicker">价格走势 / 日线</div><h2>日线结构 <small>{chart?.history_count || '—'} 根有效K线</small></h2></div><div className="chart-controls"><label className="date-control"><CalendarDays size={14} /><input aria-label="回放截止日期" type="date" value={asOf} max={chart?.as_of_date} onChange={(event) => setAsOf(event.target.value)} /></label><button className="icon-button" title="清除回放截止日" aria-label="清除回放截止日" disabled={!asOf} onClick={() => setAsOf('')}><X size={15} /></button></div></div>
      <div className="ma-switches"><span>均线</span>{maLabels.map((window) => <button key={window} className={visibleMAs.includes(window) ? 'active' : ''} onClick={() => toggleMA(window)}><i style={{ backgroundColor: visibleMAs.includes(window) ? ({ 5: '#60d7c4', 13: '#82b8ff', 21: '#dbb678', 34: '#c897ff', 55: '#f28a8a' } as Record<number, string>)[window] : undefined }} />MA{window}</button>)}<span className="chart-control-spacer" /><span className="chart-meta">数据截止 {formatDate(chart?.as_of_date)} · 报价时间按市场交易日解释</span></div>
      {loading ? <div className="chart-placeholder"><div className="loading-orbit" /><span>正在计算指标…</span></div> : chartError ? <EmptyState icon={CircleHelp} title="图表暂不可用" detail={chartError} /> : chart && <PriceChart data={chart} visibleMAs={visibleMAs} redUp={redUp} theme={theme} />}
      <div className="chart-bottom-note"><span><i className="legend-volume" />成交量</span><span>图表与规则计算口径一致；回放截止日后的数据不会进入视图。</span><span>TradingView Lightweight Charts</span></div>
    </section>

    <section className="instrument-detail-grid">
      <div className="panel rules-panel"><div className="panel-heading"><div><div className="section-kicker">规则说明</div><h2>信号如何产生</h2></div><span className="rule-version-pill">V1</span></div><div className="rule-definition"><div className="rule-number">01</div><div><strong>突破观察</strong><p>当日收盘价 <b>大于</b> 前 20 根有效日线最高价，且 MA21 大于 MA55。</p></div></div><div className="rule-definition"><div className="rule-number">02</div><div><strong>退出观察</strong><p>持有模拟仓位时，收盘价小于前 10 根有效日线最低价，或 MA21 小于 MA55。</p></div></div><div className="rule-warning"><CircleHelp size={14} /><span>信号在收盘后才可知。简化模拟最早使用下一交易日开盘价，不构成买卖建议。</span></div></div>
      <div className="panel signal-history-panel"><div className="panel-heading"><div><div className="section-kicker">信号历史</div><h2>近期规则记录</h2></div><span className="mini-count">{recentSignals.length.toString().padStart(2, '0')} <small>条</small></span></div>
        {recentSignals.length ? <div className="history-list">{recentSignals.map((signal) => <div className="history-row" key={`${signal.decision_date}-${signal.signal_type}`}><span className="history-date">{formatDate(signal.decision_date)}</span><SignalTag value={signal.signal_type} /><span className="history-reason">{signal.reason}</span><span className="history-status">{signal.simulated_status === 'pending' ? '待模拟执行' : signal.simulated_status}</span></div>)}</div> : <EmptyState icon={Activity} title="尚无规则事件" detail="预热完成后，满足条件的信号会出现在这里。" />}
      </div>
    </section>
  </div>;
}

function WatchlistPage({ market, setMarket, redUp, instruments, onOpenInstrument, onNotice }: { market: Market; setMarket: (market: Market) => void; redUp: boolean; instruments: Instrument[]; onOpenInstrument: (id: string) => void; onNotice: (text: string) => void }) {
  const [items, setItems] = useState<WatchItem[]>([]);
  const [query, setQuery] = useState('');
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState('');
  const results = instruments.filter((item) => item.market === market && (query.trim().length === 0 || item.display_symbol.toLowerCase().includes(query.trim().toLowerCase()) || item.name.toLowerCase().includes(query.trim().toLowerCase()))).slice(0, 8);
  const load = useCallback(() => api.watchlist(market).then((result) => { setItems(result.items); setNoteDrafts(Object.fromEntries(result.items.map((item) => [item.instrument_id, item.note || '']))); }), [market]);
  useEffect(() => { load().catch(() => setItems([])); }, [load]);
  const add = async (instrument: Instrument) => {
    setBusy(instrument.instrument_id);
    try { await api.addWatch(instrument.instrument_id); await load(); setQuery(''); onNotice(`已添加 ${instrument.display_symbol}`); }
    catch (reason) { onNotice((reason as Error).message); }
    finally { setBusy(''); }
  };
  const remove = async (item: WatchItem) => {
    setBusy(item.instrument_id);
    try { await api.removeWatch(item.instrument_id); await load(); onNotice(`已移除 ${item.display_symbol}`); }
    catch (reason) { onNotice((reason as Error).message); }
    finally { setBusy(''); }
  };
  const saveNote = async (item: WatchItem) => {
    if (noteDrafts[item.instrument_id] === item.note) return;
    try { await api.addWatch(item.instrument_id, noteDrafts[item.instrument_id] || ''); await load(); onNotice('备注已保存'); } catch (reason) { onNotice((reason as Error).message); }
  };

  return <div className="page-stack">
    <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line" />个人自选 / 04</div><h1>我的自选<span className="heading-period">.</span></h1><p>仅存本机数据库；切换港美市场，跟踪快照变化并添加备注。</p></div><div className="heading-side"><div className="heading-stat"><span>{items.length.toString().padStart(2, '0')}</span><small>{market === 'HK' ? '港股自选' : '美股自选'}</small></div></div></section>
    <section className="panel add-watch-panel"><div className="add-watch-intro"><span className="quick-icon quick-icon--chart"><Star size={17} /></span><div><strong>添加演示标的</strong><small>从本机合成证券目录中选择；还没有接入真实证券清单。</small></div></div><div className="market-tabs market-tabs--compact"><button className={market === 'HK' ? 'selected' : ''} onClick={() => setMarket('HK')}>HK</button><button className={market === 'US' ? 'selected' : ''} onClick={() => setMarket('US')}>US</button></div><div className="watch-search"><Search size={15} /><input aria-label="搜索并添加自选" placeholder="输入合成代码或名称" value={query} onChange={(event) => setQuery(event.target.value)} /><span>仅演示</span>{query && <div className="watch-dropdown">{results.map((item) => <button key={item.instrument_id} onClick={() => add(item)} disabled={busy === item.instrument_id}><span><b>{item.display_symbol}</b><small>{item.name}</small></span><span>{busy === item.instrument_id ? '添加中…' : '＋ 添加'}</span></button>)}{!results.length && <div className="search-no-result">目录中没有匹配证券</div>}</div>}</div></section>
    <section className="panel watchlist-panel"><div className="panel-heading"><div><div className="section-kicker">本机自选</div><h2>关注标的 <small>{items.length.toString().padStart(2, '0')} 个</small></h2></div><span className="local-only-pill"><ShieldCheck size={13} />本机保存</span></div>
      {items.length ? <div className="table-wrap"><table className="data-table watch-table"><thead><tr><th>标的</th><th>最新收盘</th><th>日变动</th><th>规则状态</th><th>个人备注</th><th>操作</th></tr></thead><tbody>{items.map((item) => <tr key={item.instrument_id}><td><button className="table-symbol table-symbol--button" onClick={() => onOpenInstrument(item.instrument_id)}><i>{item.market}</i><span><b>{item.display_symbol}</b><small>{item.name}</small></span></button></td><td className="number-cell">{money(item.close, item.currency)}</td><td className={`number-cell ${signClass(item.change_pct, redUp)}`}>{signedPercent(item.change_pct)}</td><td><SignalTag value={item.signal} /></td><td><input className="note-input" aria-label={`${item.display_symbol}个人备注`} placeholder="添加观察备注" value={noteDrafts[item.instrument_id] || ''} onChange={(event) => setNoteDrafts((state) => ({ ...state, [item.instrument_id]: event.target.value }))} onBlur={() => saveNote(item)} onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur(); }} /></td><td><button className="remove-watch" onClick={() => remove(item)} disabled={busy === item.instrument_id} aria-label={`移除 ${item.display_symbol}`}><X size={14} /></button></td></tr>)}</tbody></table></div> : <EmptyState icon={Star} title="自选列表还是空的" detail="在上方搜索合成标的，加入后会保存在本机数据库。" />}
    </section>
    <div className="footnote-card"><Database size={15} /><span>自选资料与行情数据库均位于项目本地 data/ 目录，已加入 Git 忽略规则。</span><span className="footnote-label">本机数据库</span></div>
  </div>;
}

function ReplayPage({ market, instruments, onOpenInstrument }: { market: Market; instruments: Instrument[]; onOpenInstrument: (id: string) => void }) {
  const defaultInstrument = instruments.find((item) => item.market === market)?.instrument_id || `DEMO-${market}-001`;
  const [instrumentId, setInstrumentId] = useState(defaultInstrument);
  const [startDate, setStartDate] = useState(() => { const d = new Date(); d.setFullYear(d.getFullYear() - 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; });
  const [feeBps, setFeeBps] = useState(5);
  const [slippageBps, setSlippageBps] = useState(5);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { setInstrumentId(instruments.find((item) => item.market === market)?.instrument_id || `DEMO-${market}-001`); setResult(null); }, [market, instruments]);
  const options = instruments.filter((item) => item.market === market);
  const run = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true); setError(''); setResult(null);
    try { setResult(await api.simulate(instrumentId, startDate, feeBps, slippageBps)); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };

  return <div className="page-stack">
    <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line" />历史回放 / 05</div><h1>历史回放<span className="heading-period">.</span></h1><p>逐日重建当时可知信号，以独立标的模拟，不合并成投资组合。</p></div><div className="heading-side"><span className="replay-badge"><FileClock size={15} /> 无未来数据泄漏</span></div></section>
    <section className="panel replay-form-panel"><div className="panel-heading"><div><div className="section-kicker">回放参数</div><h2>设置回放区间</h2></div><span className="demo-pill">合成数据</span></div><form className="replay-form" onSubmit={run}><label><span>市场 / 标的</span><select aria-label="回放标的" value={instrumentId} onChange={(event) => setInstrumentId(event.target.value)}>{options.map((item) => <option key={item.instrument_id} value={item.instrument_id}>{item.display_symbol} · {item.name}</option>)}</select></label><label><span>开始日期</span><input aria-label="回放开始日期" type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} required /></label><label><span>每边费用（基点）</span><input aria-label="费用基点" type="number" min="0" max="500" step="1" value={feeBps} onChange={(event) => setFeeBps(Number(event.target.value))} /></label><label><span>每边滑点（基点）</span><input aria-label="滑点基点" type="number" min="0" max="500" step="1" value={slippageBps} onChange={(event) => setSlippageBps(Number(event.target.value))} /></label><button className="primary-button" type="submit" disabled={busy}><Activity size={15} />{busy ? '逐日计算中…' : '运行单标的回放'}</button></form>{error && <div className="inline-error">{error}</div>}<div className="form-assumption"><CircleHelp size={14} /><span>费用与滑点是可调假设值，不代表券商真实收费；模拟成交使用下一交易日开盘价。</span></div></section>
    {result ? <>
      <section className="replay-summary"><div className="replay-summary__title"><div><span className="eyebrow eyebrow--small">回放结果 / {result.instrument.display_symbol}</span><h2>{result.instrument.name}<small>{formatDate(result.start_date)} — {formatDate(result.end_date)} · {result.currency}</small></h2></div><button className="text-action" onClick={() => onOpenInstrument(result.instrument.instrument_id)}>个股分析 <ArrowRight size={14} /></button></div><div className="result-metrics"><div><small>模拟区间收益</small><strong className={signClass(result.total_return_pct, true)}>{signedPercent(result.total_return_pct)}</strong><span>单标的全仓假设</span></div><div><small>最大回撤</small><strong className="tone-down">{result.max_drawdown_pct.toFixed(2)}%</strong><span>逐日收盘估值</span></div><div><small>已平仓交易</small><strong>{result.closed_trade_count.toString().padStart(2, '0')}</strong><span>{result.open_or_pending_count} 笔持仓 / 待执行</span></div><div><small>胜率</small><strong>{result.win_rate_pct == null ? '—' : `${result.win_rate_pct.toFixed(1)}%`}</strong><span>仅基于已平仓交易</span></div></div></section>
      <section className="panel replay-chart-panel"><div className="panel-heading"><div><div className="section-kicker">资金曲线 / 单一标的</div><h2>模拟资金变化 <small>初始单位资金 = 1.000</small></h2></div><span className="chart-meta">最大回撤：{result.drawdown_basis}</span></div><EquitySparkline points={result.equity_curve} /></section>
      <section className="panel replay-trades-panel"><div className="panel-heading"><div><div className="section-kicker">成交记录</div><h2>信号与模拟成交</h2></div><span className="mini-count">{result.trades.length.toString().padStart(2, '0')} <small>笔</small></span></div>{result.trades.length ? <div className="table-wrap"><table className="data-table"><thead><tr><th>入场信号日</th><th>模拟入场</th><th>入场价</th><th>退出信号日</th><th>模拟退出</th><th>净收益</th><th>状态</th></tr></thead><tbody>{result.trades.map((trade, index) => <tr key={`${trade.entry_signal_date}-${index}`}><td>{formatDate(trade.entry_signal_date)}</td><td>{formatDate(trade.entry_date)}</td><td className="number-cell">{money(trade.entry_price, result.currency)}</td><td>{formatDate(trade.exit_signal_date)}</td><td>{formatDate(trade.exit_date)}</td><td className={`number-cell ${signClass(trade.return_pct, true)}`}>{trade.return_pct == null ? '—' : signedPercent(trade.return_pct)}</td><td><span className={`trade-status trade-status--${trade.status}`}>{trade.status === 'closed' ? '已平仓' : trade.status === 'open' ? '持仓中' : trade.status === 'pending' ? '待入场' : trade.status === 'pending_exit' ? '待退出' : trade.skip_reason || '已跳过'}</span></td></tr>)}</tbody></table></div> : <EmptyState icon={Activity} title="该区间没有模拟交易" detail="策略在当前日期区间内没有触发有效信号。" />}</section>
      <section className="assumptions-grid">{result.assumptions.map((assumption, index) => <div className="assumption-card" key={assumption}><span>{String(index + 1).padStart(2, '0')}</span><p>{assumption}</p></div>)}</section>
    </> : <section className="panel replay-intro-panel"><div className="replay-empty-art"><div className="replay-empty-line replay-empty-line--one" /><div className="replay-empty-line replay-empty-line--two" /><div className="replay-empty-line replay-empty-line--three" /><span><Activity size={18} /></span></div><div><div className="section-kicker">确定性规则 / 可审计</div><h2>从历史某一天开始回放</h2><p>规则只使用回放日之前可见的数据。未来K线、排名和信号不会泄漏到过去。</p><div className="replay-steps"><span><i>01</i>确定标的与起始日</span><span><i>02</i>按次日开盘模拟成交</span><span><i>03</i>查看交易与回撤假设</span></div></div></section>}
  </div>;
}
