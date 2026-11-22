import { useEffect, useRef } from 'react';
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
} from 'lightweight-charts';
import type { ChartData } from '../types';

interface Props {
  data: ChartData;
  visibleMAs: number[];
  compact?: boolean;
  redUp?: boolean;
  theme?: 'dark' | 'light';
}

const maColors: Record<number, string> = {
  5: '#60d7c4',
  13: '#82b8ff',
  21: '#dbb678',
  34: '#c897ff',
  55: '#f28a8a',
};

export default function PriceChart({ data, visibleMAs, compact = false, redUp = true, theme = 'dark' }: Props) {
  const holder = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = holder.current;
    if (!element || !data.bars.length) return;
    const isLight = theme === 'light';
    const chart = createChart(element, {
      width: element.clientWidth,
      height: compact ? 180 : 370,
      layout: {
        background: { type: ColorType.Solid, color: isLight ? '#ffffff' : '#101820' },
        textColor: isLight ? '#657580' : '#84939f',
        attributionLogo: true,
        fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: isLight ? 'rgba(80, 102, 118, 0.08)' : 'rgba(121, 145, 161, 0.08)' },
        horzLines: { color: isLight ? 'rgba(80, 102, 118, 0.10)' : 'rgba(121, 145, 161, 0.10)' },
      },
      crosshair: { mode: 0 },
      rightPriceScale: { borderColor: isLight ? 'rgba(80, 102, 118, 0.18)' : 'rgba(137, 155, 171, 0.16)' },
      timeScale: {
        borderColor: isLight ? 'rgba(80, 102, 118, 0.18)' : 'rgba(137, 155, 171, 0.16)',
        timeVisible: false,
        rightOffset: 7,
        barSpacing: compact ? 8 : 7,
      },
      localization: {
        locale: 'zh-CN',
        priceFormatter: (price: number) => new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(price),
      },
      handleScroll: !compact,
      handleScale: !compact,
    });

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: redUp ? '#ef6c72' : '#55c5a2',
      downColor: redUp ? '#55c5a2' : '#ef6c72',
      borderUpColor: redUp ? '#ef6c72' : '#55c5a2',
      borderDownColor: redUp ? '#55c5a2' : '#ef6c72',
      wickUpColor: redUp ? '#ef6c72' : '#55c5a2',
      wickDownColor: redUp ? '#55c5a2' : '#ef6c72',
      priceLineVisible: false,
    });
    candles.setData(data.bars.map((bar) => ({
      time: bar.trading_date as `${number}-${number}-${number}`,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    })));

    visibleMAs.forEach((window) => {
      const valueFor = (bar: (typeof data.bars)[number]) => window === 5 ? bar.ma5 : window === 13 ? bar.ma13 : window === 21 ? bar.ma21 : window === 34 ? bar.ma34 : bar.ma55;
      chart.addSeries(LineSeries, {
        color: maColors[window],
        lineWidth: window >= 34 ? 2 : 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      }).setData(data.bars.filter((bar) => valueFor(bar) !== null).map((bar) => ({
        time: bar.trading_date as `${number}-${number}-${number}`,
        value: valueFor(bar) as number,
      })));
    });

    const volume = chart.addSeries(HistogramSeries, {
      priceScaleId: 'volume',
      priceFormat: { type: 'volume' },
      color: '#4f6576',
      lastValueVisible: false,
      priceLineVisible: false,
    });
    volume.setData(data.bars.map((bar) => ({
      time: bar.trading_date as `${number}-${number}-${number}`,
      value: bar.volume,
      color: bar.close >= bar.open ? (redUp ? 'rgba(239, 108, 114, 0.44)' : 'rgba(85, 197, 162, 0.44)') : (redUp ? 'rgba(85, 197, 162, 0.4)' : 'rgba(239, 108, 114, 0.4)'),
    })));
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.83, bottom: 0 } });

    const markers = data.signals.filter((signal) => data.bars.some((bar) => bar.trading_date === signal.decision_date)).map((signal) => ({
      time: signal.decision_date as `${number}-${number}-${number}`,
      position: signal.signal_type === '突破观察' ? 'belowBar' as const : 'aboveBar' as const,
      color: signal.signal_type === '突破观察' ? '#7acbb4' : '#e88d87',
      shape: signal.signal_type === '突破观察' ? 'arrowUp' as const : 'arrowDown' as const,
      text: signal.signal_type,
    }));
    createSeriesMarkers(candles, markers);
    chart.timeScale().fitContent();

    const observer = new ResizeObserver((entries) => {
      const width = Math.floor(entries[0]?.contentRect.width || 0);
      if (width > 0) chart.applyOptions({ width });
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [data, visibleMAs, compact, redUp, theme]);

  return <div className={`price-chart ${compact ? 'price-chart--compact' : ''}`} ref={holder} aria-label="日线K线图" />;
}
