import React, { useState } from 'react';
import { dateTime, label, qualityIssue } from './api';
import { Badge, Button, Empty, ErrorLine, Field, Icon, Modal, PageHeading } from './components';
import { StockPicker } from './stock-picker';

export function company(session, symbol) {
  const item = session.instruments?.find(i => i.symbol === symbol);
  return item && item.name !== symbol ? `${item.name} · ${symbol}` : symbol;
}

function Recent({ items, session, onTask, onReport }) {
  return items?.length ? <div className="investor-recent">{items.map(t => <button key={t.id} className="recent-research"
    onClick={() => t.report_id ? onReport(t.report_id) : onTask(t.id)}>
    <div><strong>{company(session, t.mandate.ticker)}</strong><small>研究日 {t.mandate.analysis_date} · {t.mandate.prediction_horizon_trading_days} 个交易日</small></div>
    <div><Badge value={t.status} /><span>{t.report_id ? '阅读报告' : '查看进度'} <Icon name="arrow" size={15} /></span></div>
  </button>)}</div> : <Empty title="从你想了解的公司开始" text="选择公司和研究问题，系统会整理资料、保留依据并生成报告。" />;
}

export function BeginnerHome({ session, data, onCreate, onHelp, onWatchlist, onTask, onReport, onSettings }) {
  const canCreate = session.scopes.includes('task:create');
  const ready = session.templates.some(t => t.execution.credentials_present && (t.tickers.length || t.allow_listed_stocks));
  return <>
    <PageHeading title={<>这只股票，<br />值得买、持有还是卖？</>} description="系统整理行情、公司与消息，比较多方和反方理由，给出研究观点、风险与重新评估条件。">
      {canCreate ? <Button icon="plus" onClick={onCreate}>开始了解公司</Button> : <Button secondary onClick={onHelp}>阅读入门指南</Button>}
    </PageHeading>
    {canCreate && !ready ? <div className="notice"><strong>开始前需要设置研究服务</strong>
      <p>模型或可研究对象尚未配置。可以先体验登录页的合成示例；正式研究需要管理员保存服务设置。</p>
      {session.scopes.includes('settings:read') ? <Button secondary onClick={onSettings}>打开设置</Button> : null}</div> : null}
    <div className="beginner-path" aria-label="上手步骤">
      {[['01', '选择股票', '内置美股、A股和港股资料'], ['02', '系统完成研究', '收集资料，比较机会与风险'], ['03', '查看结果', '买卖观点、理由与失效条件']].map(([n, title, text]) =>
        <div key={n}><span>{n}</span><div><strong>{title}</strong><p>{text}</p></div></div>)}
    </div>
    <div className="home-layout beginner-layout"><section className="panel"><div className="panel-heading"><h2>我的最近研究</h2></div>
      {data ? <Recent items={data.recent} session={session} onTask={onTask} onReport={onReport} /> : <p className="loading">正在读取个人研究…</p>}
    </section><aside className="panel beginner-side"><span className="eyebrow">下一次打开，从这里继续</span><h2>我的关注清单</h2>
      <p>{data?.watchlist.length ? `已关注 ${data.watchlist.length} 个对象，笔记保存在当前账号下。` : '把感兴趣的公司和待核实事项放在一起。'}</p>
      <Button secondary onClick={onWatchlist}>管理关注清单 <Icon name="arrow" size={16} /></Button>
      <hr /><h3>第一次用？</h3><p>了解代码、评级、研究期限和数据时间的含义。</p>
      <button className="text-button" onClick={onHelp}>打开入门指南 <Icon name="arrow" size={16} /></button>
    </aside></div>
    <div className="boundary"><Icon name="shield" /><span>研究观点帮助理解依据与风险；系统不执行交易，关注清单不提供实时行情。</span></div>
  </>;
}

function NoteDialog({ item, onClose, call, onSaved }) {
  const [note, setNote] = useState(item.note);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function save(e) {
    e.preventDefault(); setBusy(true); setError(null);
    try { await call('/watchlist', { method: 'POST', body: { action: 'save_note', symbol: item.symbol, note } });
      onSaved(); onClose();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return <Modal title={`核实笔记 · ${item.name}`} subtitle="仅当前账号可读取，保存到工作空间。" onClose={onClose}>
    <form onSubmit={save}><Field label="待核实事项" source="本人输入" hint="例如：查阅最新财报、核实新闻原文、比较竞争对手。最多4000字。">
      <textarea rows={6} autoFocus maxLength={4000} value={note} onChange={e => setNote(e.target.value)} /></Field>
      <ErrorLine error={error} /><div className="modal-footer"><Button secondary type="button" onClick={onClose}>取消</Button>
        <Button disabled={busy}>{busy ? '保存中…' : '保存笔记'}</Button></div></form>
  </Modal>;
}

export function WatchlistPage({ session, data, call, onRefresh, onCreate, onTask, onReport, notify }) {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState(null);
  const [remove, setRemove] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const canWrite = session.scopes.includes('task:create');
  async function change(action, symbol) {
    setBusy(true); setError(null);
    try { await call('/watchlist', { method: 'POST', body: { action, symbol } });
      setRemove(null); onRefresh(); notify(action === 'add' ? '已保存关注，已有笔记会保留。' : '已移除关注及笔记。');
    } catch (err) { setError(err.fields?.length ? new Error(err.fields[0].message) : err); } finally { setBusy(false); }
  }
  return <>
    <section className="panel watchlist-panel"><div className="panel-heading"><h2>个人关注 <span className="count">{data?.watchlist.length ?? 0}</span></h2></div>
      <p>保存在当前账号下。这里显示最后一次研究状态，不是实时价格。</p>
      {canWrite ? <StockPicker session={session} call={call} value={query} onInput={setQuery}
        label="搜索可关注对象" onSelect={i => { if (!busy) change('add', i.symbol); }} /> : null}
      {!data ? <p className="loading">正在读取关注清单…</p> : !data.watchlist.length ? <Empty title="还没有关注对象" text="可以在这里选择对象，或阅读报告时保存关注。" /> :
        <div className="watchlist-items">{data.watchlist.map(item => <article key={item.symbol} className="watchlist-item">
          <div className="watchlist-title"><div><h3>{item.name} <small>{item.symbol}</small></h3>
            {item.latest_task ? <p>最近研究日 {item.latest_task.mandate.analysis_date} · <Badge value={item.latest_task.status} /></p> : <p>还没有本人的研究记录</p>}
            {!item.approved ? <p className="danger-text">已移出批准清单；已有笔记可保留，重新研究需要配置。</p> : null}</div>
            <small>笔记更新 {dateTime(item.updated)}</small></div>
          <p className="saved-note">{item.note || '尚未记录待核实事项。'}</p>
          <div className="inline-actions">{item.latest_task ? <Button secondary onClick={() => item.latest_task.report_id
            ? onReport(item.latest_task.report_id) : onTask(item.latest_task.id)}>{item.latest_task.report_id ? '阅读最近报告' : '查看研究进度'}</Button> : null}
            {canWrite ? <><Button secondary disabled={!item.approved} onClick={() => onCreate(item.symbol)}>重新研究</Button>
              <Button secondary onClick={() => setSelected(item)}>编辑笔记</Button><button className="text-button danger-text" onClick={() => setRemove(item.symbol)}>移除关注</button></> : null}</div>
          {remove === item.symbol ? <div className="inline-confirm" role="alert"><span>移除后将删除此对象的个人笔记。</span>
            <Button danger disabled={busy} onClick={() => change('remove', item.symbol)}>确认移除</Button>
            <Button secondary onClick={() => setRemove(null)}>保留关注</Button></div> : null}
        </article>)}</div>}
      <ErrorLine error={error} />
    </section>
    {selected ? <NoteDialog item={selected} call={call} onClose={() => setSelected(null)}
      onSaved={() => { onRefresh(); notify('核实笔记已保存。'); }} /> : null}
  </>;
}

const TERMS = [
  ['股票代码', '每个市场用代码识别证券，例如苹果公司的 AAPL。公司名称是辅助信息，创建时以批准的代码为准。'],
  ['研究评级', '买入、增持、持有、减持、卖出是模型在本次期限下的研究观点。增持/减持涉及与基准比较，不直接决定你的账户仓位。'],
  ['对照基准', '用于比较研究结果的对象，例如 SPY。只有在相同时间窗口、币种和价格口径下，比较才有一致含义。'],
  ['交易日与研究期限', '交易日是市场交易的会话，不含通常休市的周末。5/20/60个交易日约一周/一月/三月，仅是近似，不是建议持有期限。'],
  ['数据时间', '研究日期、价格日期、内容采集时间和信息首次公开时间含义不同。系统留存内容不一定能证明它最早何时公开。'],
  ['草稿与复核', '执行完成后生成待复核报告。复核员核验依据和问题；质量阻断项必须由新的研究版本解决，发布也不保证投资结果。'],
  ['持仓占比', '某对象的持仓价值占账户净资产的比例。持仓复核需要你提供数量、同日价格、币种和净资产，不能从一般研究中推断。'],
  ['关注与核实笔记', '关注只保存研究对象和本人的待核实事项，不自动交易或获取实时价格。移除关注会删除对应个人笔记。'],
  ['合成示例', '行情、事件、财务和评级都是预设数据，实际运行系统流程但不调用付费模型，不能用于判断真实公司。'],
];

export function BeginnerGuide({ onCreate, canCreate }) {
  const [query, setQuery] = useState('');
  const terms = TERMS.filter(t => t.join(' ').includes(query.trim()));
  return <section className="panel investor-guide"><h2>读懂第一份研究</h2>
    <p>先明确想了解的公司和问题；读报告时先看数据状态，再看观点和原文依据，最后记下需要核实的事项。</p>
    {canCreate ? <Button icon="plus" onClick={onCreate}>开始了解公司</Button> : null}
    <Field label="搜索术语" source="系统预置" hint="例如：评级、基准、交易日、数据时间。"><input type="search" value={query}
      onChange={e => setQuery(e.target.value)} placeholder="输入想了解的词" /></Field>
    <dl>{terms.map(([name, text]) => <div key={name}><dt>{name}</dt><dd>{text}</dd></div>)}</dl>
    {!terms.length ? <p>没有匹配的术语，请缩短关键词。</p> : null}
  </section>;
}

export function ReportBrief({ report, call, canWrite, onQuality, onContent, onWatchlist, notify, onRefresh }) {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const brief = report.brief;
  if (!brief) return <p>此服务尚未提供简明概览，请打开完整研究正文。</p>;
  const blocked = report.quality.issues.some(i => i.severity === 'block');
  async function save() {
    setBusy(true); setError(null);
    try { await call('/watchlist', { method: 'POST', body: { action: 'add', symbol: report.mandate.ticker } });
      onRefresh(); notify('已保存关注，可以在关注清单中添加核实笔记。');
    } catch (err) { setError(err.fields?.length ? new Error(err.fields[0].message) : err); } finally { setBusy(false); }
  }
  return <div className="report-brief">
    <div className={`brief-status ${blocked || report.expired ? 'brief-alert' : ''}`}>
      <strong>先看这份研究的使用条件</strong>
      {brief.synthetic ? <p>合成示例：价格、事件、财务和评级为预设内容，仅用于练习系统流程。</p> : null}
      {report.expired ? <p>已超过报告有效期，继续判断前需要更新研究。</p> : null}
      {blocked ? <p>存在质量阻断项，当前版本无法批准或发布。</p> : null}
      <p>复核状态：{label(report.status)}。{['rejected', 'withdrawn'].includes(report.status) ? '该版本已退回或撤回，请查看复核记录。'
        : report.status === 'draft' ? '结论尚未完成复核。' : '复核与发布不保证未来投资结果。'}</p>
      <button className="text-button" onClick={onQuality}>查看 {report.quality.issues.length} 项质量与核验问题 <Icon name="arrow" size={15} /></button>
    </div>
    <div className="brief-opinion"><span className="eyebrow">本次股票研究结论</span><h3>{label(report.rating)}</h3><p>{brief.rating_meaning}</p>
      {brief.decision && brief.research_status === 'complete' ? <p className="decision-conclusion">{brief.decision.conclusion}</p> : null}
      {brief.research_status === 'insufficient' ? <p>资料不足，暂不形成买卖判断。已取得的资料仍可阅读，请核实缺口后更新研究。</p> : null}
      <p>关注期限 {report.mandate.prediction_horizon_trading_days} 个交易日 · 对照 {report.mandate.benchmark} · 有效至 {report.mandate.valid_until}</p></div>
    <div className="brief-price"><strong>本次留存的价格</strong>{brief.price ? <p>{Number(brief.price.close).toLocaleString('zh-CN', { maximumFractionDigits: 4 })} {brief.price.currency}
      <small>价格日 {brief.price.price_date} · 来源 {brief.price.source} · {brief.price.synthetic ? '合成收盘价' : '已留存收盘价'}；不是当前行情</small></p>
      : <p>没有可展示的完整价格证据。请在质量页查看缺失、币种、时效或价格冲突问题。</p>}</div>
    {brief.price && brief.display_currency !== brief.price.currency ? <div className="brief-price"><strong>显示货币换算</strong>
      {brief.converted_price ? <p>约 {brief.converted_price.close} {brief.converted_price.currency}
        <small>1 {brief.price.currency} = {Number(brief.converted_price.rate).toLocaleString('zh-CN', { maximumFractionDigits: 6 })} {brief.converted_price.currency} · 汇率日 {brief.converted_price.rate_date} · 来源 {brief.converted_price.source}</small></p>
        : <p>无法取得有效汇率，保留原始报价 {brief.price.currency}，未将价格直接改标为 {brief.display_currency}。</p>}</div> : null}
    {brief.decision ? <div className="decision-details">{[['reasons', '判断依据'], ['risks', '主要风险'], ['conditions', '何时需要重新判断']].map(([key, title]) =>
      <section key={key}><h3>{title}</h3><ul>{brief.decision[key].map((text, i) => <li key={i}>{text}</li>)}</ul></section>)}</div> : null}
    <details className="brief-original" open={!brief.decision}><summary>{brief.decision ? '查看原文节选与出处' : '研究原文节选'}</summary>
    <div className="brief-excerpts">{brief.excerpts.map(e => <section key={e.source}><h3>{e.title}</h3>
      <p className="excerpt-text">{e.provided ? e.text : '本份固定报告未提供此项原文，请继续核实。'}{e.truncated ? '…（已截取，完整内容见正文）' : ''}</p>
      <small>原文来源：{e.source}</small></section>)}</div></details>
    <section className="brief-gaps"><h3>继续核实什么</h3>
      <ul>{report.quality.issues.map((i, n) => <li key={n}>{qualityIssue(i).title}：{qualityIssue(i).description}</li>)}</ul>
      <p>已留存 {brief.evidence_count} 条来源输出。{brief.publication_times_known ? '来源记录提供了公开时间。' : '留存记录不能完整确认信息首次公开时间。'}</p>
    </section>
    <div className="inline-actions"><Button secondary onClick={onContent}>阅读完整研究正文</Button>
      {canWrite ? <Button disabled={busy} onClick={save}>保存关注</Button> : null}
      <Button secondary onClick={onWatchlist}>关注清单与笔记</Button></div>
    <small className="brief-source">{brief.source}</small><ErrorLine error={error} />
  </div>;
}
