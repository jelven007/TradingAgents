import React, { useEffect, useState } from 'react';
import { Field } from './components';

export const benchmarkNames = { SPY: '标普500 · SPY', QQQ: '纳斯达克100 · QQQ',
  '000300.SS': '沪深300 · 000300.SS', '^HSI': '恒生指数 · ^HSI', 'BTC-USD': '比特币 · BTC-USD' };
export const currencyNames = { USD: '美元（USD）', CNY: '人民币（CNY）', HKD: '港币（HKD）' };

export function StockPicker({ session, call, template, value, onSelect, onInput, error, label = '公司名称或代码' }) {
  const [market, setMarket] = useState('');
  const [result, setResult] = useState({ items: session.instruments || [], total: 0, offset: 0 });
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setFailed(false);
    const timer = setTimeout(() => {
      call(`/instruments?q=${encodeURIComponent(value)}&market=${market}&limit=12&offset=${offset}`,
        { signal: controller.signal }).then(data => {
        if (!controller.signal.aborted) {
          setResult(data); setLoading(false);
        }
      }).catch(e => {
        if (e.name !== 'AbortError' && !controller.signal.aborted) { setFailed(true); setLoading(false); }
      });
    }, 180);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [call, value, market, offset]);
  const needle = value.trim().toLowerCase();
  const rows = result.items.filter(i => (!template || template.allow_listed_stocks || template.tickers.includes(i.symbol))
    && (!market || i.market === market)
    && (!needle || [i.symbol, i.name, ...(i.aliases || [])].join(' ').toLowerCase().includes(needle)));
  return <div className="stock-picker">
    <div className="market-options" aria-label="股票市场">{[['', '全部市场'], ['US', '美股'], ['CN', 'A股'], ['HK', '港股']].map(([id, name]) =>
      <button type="button" key={id} aria-pressed={market === id} onClick={() => {
        setMarket(id); setOffset(0); onInput('');
      }}>{name}</button>)}</div>
    <Field label={label} source="预置证券目录 → 选择" hint={session.stock_catalog
      ? `内置美股、A股、港股 ${Object.values(session.stock_catalog.counts).reduce((a, n) => a + n, 0).toLocaleString()} 条资料；目录更新 ${session.stock_catalog.generated_at.slice(0, 10)}，不含实时行情。`
      : '按公司名称或代码搜索，点击选择。'} error={error}>
      <input autoFocus type="search" value={value} maxLength={100} placeholder="搜索英伟达、贵州茅台、腾讯或股票代码"
        onChange={e => { setOffset(0); onInput(e.target.value); }} /></Field>
    <div className="company-options">{rows.map(i =>
      <button type="button" key={i.symbol} aria-pressed={value === i.symbol} onClick={() => onSelect(i)}>
        {i.name} <span>{i.symbol} · {i.exchange}</span></button>)}</div>
    {loading ? <p className="small muted" role="status">正在搜索股票资料…</p> : failed
      ? <p className="small danger-text" role="alert">证券搜索暂时不可用，请重新输入名称或代码。</p>
      : !rows.length ? <p className="small muted">没有匹配的可研究对象；试试代码或更短的名称。</p>
        : <p className="small muted">{result.total} 个匹配对象{value ? ' · 点击上方股票确认选择' : ''}
          {offset > 0 ? <button className="text-button" type="button" onClick={() => setOffset(Math.max(0, offset - 12))}>上一页</button> : null}
          {offset + 12 < result.total ? <button className="text-button" type="button" onClick={() => setOffset(offset + 12)}>更多股票</button> : null}</p>}
  </div>;
}
