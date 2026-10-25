import React, { useState } from 'react';
import { dateTime, futureDate, label, shortId, today } from './api';
import { Badge, Button, Empty, ErrorLine, Field, Modal, Pager } from './components';

export function PlanDialog({ session, call, onClose, onCreated }) {
  const [mode, setMode] = useState('diagnostic');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError(null);
    const data = new FormData(event.currentTarget);
    try {
      const sessions = data.get('sessions').split(/[\s,，]+/).filter(Boolean);
      const plan = {
        workspace: session.workspace, experiment: data.get('experiment'), mode,
        price_basis: data.get('basis'), calendar_source: data.get('calendar_source'),
        calendar_evidence: data.get('calendar_evidence'),
        samples: [{
          key: data.get('sample_key'), template: data.get('template'), sessions,
          mandate: {
            ticker: data.get('ticker'), analysis_date: data.get('date'),
            prediction_horizon_trading_days: Number(data.get('horizon')),
            benchmark: data.get('benchmark'), quote_currency: data.get('currency'),
            valid_until: data.get('valid_until'), asset_type: 'stock', purpose: 'general_research',
          },
        }],
      };
      const result = await call('/experiments', { method: 'POST', body: plan }); onCreated(result.id);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return <Modal title="创建评估计划" subtitle="先固定样本与观察窗口，再登记预测和结果。此表单创建一个样本。" onClose={onClose} wide>
    <form onSubmit={submit}><div className="form-grid">
      <Field label="实验名称"><input name="experiment" pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,95}" required placeholder="evaluation-2026" /></Field>
      <Field label="评估模式"><select value={mode} onChange={e => setMode(e.target.value)}><option value="diagnostic">历史诊断</option><option value="prospective">前瞻观察</option></select></Field>
      <Field label="样本键"><input name="sample_key" defaultValue="sample-1" pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,95}" required /></Field>
      <Field label="研究模板"><select name="template">{session.templates.map(t => <option key={t.name}>{t.name}</option>)}</select></Field>
      <Field label="证券标的"><select name="ticker">{session.templates.flatMap(t => t.tickers).filter((t, i, a) => a.indexOf(t) === i).map(t => <option key={t}>{t}</option>)}</select></Field>
      <Field label="研究日期"><input name="date" type="date" key={mode} defaultValue={mode === 'prospective' ? futureDate(1) : session.research_today || today()} required /></Field>
      <Field label="预测期限"><input name="horizon" type="number" min="1" max="2520" defaultValue="5" required /></Field>
      <Field label="对照基准"><input name="benchmark" defaultValue="SPY" required /></Field>
      <Field label="报价币种"><select name="currency"><option>USD</option><option>CNY</option><option>HKD</option><option>EUR</option></select></Field>
      <Field label="有效至"><input name="valid_until" type="date" defaultValue={futureDate(30)} required /></Field>
      <Field label="价格口径" wide><select name="basis"><option value="unadjusted_close">未复权收盘价</option><option value="split_adjusted_close">拆股复权收盘价</option><option value="total_return_index">总收益指数</option></select></Field>
      <Field label="观察会话日期" wide hint="按顺序填入口日期与后续交易会话，数量为预测期限+1；不自动推断交易所节假日。">
        <textarea name="sessions" rows={3} required placeholder="2026-10-26, 2026-10-27, …" /></Field>
      <Field label="日历来源" wide><input name="calendar_source" required maxLength={200} placeholder="填写核定的日历来源" /></Field>
      <Field label="日历依据" wide><textarea name="calendar_evidence" rows={3} maxLength={24000} required placeholder="保留能核对会话日期的来源文本" /></Field>
    </div><div className="notice">{mode === 'prospective' ? '前瞻计划须在所有研究日之前登记，预测须在观察入口前发布并固定。' : '历史诊断明确保留模型事后知识未知，不能当作严格历史回测。'}</div>
      <ErrorLine error={error} /><div className="modal-footer"><Button secondary type="button" onClick={onClose}>取消</Button>
        <Button disabled={busy}>{busy ? '保存中…' : '固定评估计划'}</Button></div></form>
  </Modal>;
}

function ObserveDialog({ prediction, sample, basis, call, onClose, onDone, demoValues }) {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const previous = prediction.observations[0]?.input;
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError(null);
    const data = new FormData(event.currentTarget);
    const pair = (symbol, prefix) => ({ symbol, currency: sample.mandate.quote_currency, basis,
      entry: data.get(`${prefix}_entry`), exit: data.get(`${prefix}_exit`) });
    try {
      await call(`/predictions/${prediction.id}/observations`, { method: 'POST', body: {
        entry_session: sample.sessions[0], exit_session: data.get('exit'),
        asset: pair(sample.mandate.ticker, 'asset'), benchmark: pair(sample.mandate.benchmark, 'benchmark'),
        source: data.get('source'), source_payload: data.get('source_payload'),
      } }); onDone(); onClose();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return <Modal title="登记结果观察" subtitle="标的与基准使用相同窗口、币种和价格口径。数据需自行核定来源。" onClose={onClose} wide>
    <form onSubmit={submit}><div className="form-grid">
      <Field label="入口会话"><input value={sample.sessions[0]} readOnly /></Field>
      <Field label="出口会话"><select name="exit" defaultValue={demoValues?.exit_session}>{sample.sessions.slice(1).map((date, i) => <option key={date} value={date}>
        {date} · {i === sample.sessions.length - 2 ? '完整期限' : '中期观察'}</option>)}</select></Field>
      <Field label={`${sample.mandate.ticker} 入口价格`}><input name="asset_entry" defaultValue={previous?.asset.entry || demoValues?.asset.entry || ''} inputMode="decimal" required /></Field>
      <Field label={`${sample.mandate.ticker} 出口价格`}><input name="asset_exit" defaultValue={demoValues?.asset.exit || ''} inputMode="decimal" required /></Field>
      <Field label={`${sample.mandate.benchmark} 入口价格`}><input name="benchmark_entry" defaultValue={previous?.benchmark.entry || demoValues?.benchmark.entry || ''} inputMode="decimal" required /></Field>
      <Field label={`${sample.mandate.benchmark} 出口价格`}><input name="benchmark_exit" defaultValue={demoValues?.benchmark.exit || ''} inputMode="decimal" required /></Field>
      <Field label="价格来源" wide><input name="source" defaultValue={demoValues?.source || ''} required maxLength={200} /></Field>
      <Field label="原始来源文本" wide hint="完整留存并计算hash；hash不证明来源真实性。"><textarea name="source_payload" defaultValue={demoValues?.source_payload || ''} required maxLength={24000} rows={4} /></Field>
    </div>{demoValues ? <div className="notice">已预填合成演示价格。标的与基准收益分别为8%和3%，仅用于体验观察记录。</div> : null}
      <ErrorLine error={error} /><div className="modal-footer"><Button secondary type="button" onClick={onClose}>取消</Button>
      <Button disabled={busy}>{busy ? '记录中…' : '保存不可改写的观察'}</Button></div></form>
  </Modal>;
}

export function ExperimentsPage({ experiments, onSelect, offset, onOffset, onCreate }) {
  return <section className="panel"><div className="panel-heading"><h2>评估实验 <span className="count">{experiments?.total || 0}</span></h2>
    {onCreate ? <Button secondary icon="plus" onClick={onCreate}>创建评估计划</Button> : null}</div>
    {experiments?.items.length ? <div className="experiment-list">{experiments.items.map(experiment => <button className="experiment-row" key={experiment.id} onClick={() => onSelect(experiment.id)}>
      <div><strong>{experiment.name}</strong><small>登记于 {dateTime(experiment.registered_at)}</small></div><Badge value={experiment.mode} /><span>{experiment.sample_count} 个计划样本</span>
    </button>)}</div> : <Empty icon="experiment" title="暂无评估实验" text="固定观察窗口，按相同币种和期限比较研究标的与基准。" />}
    <Pager total={experiments?.total || 0} offset={offset} onChange={onOffset} /></section>;
}

export function ExperimentDetail({ summary, tasks, call, session, onBack, notify, onRefresh }) {
  const [prediction, setPrediction] = useState(null);
  const [observation, setObservation] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState('');
  if (!summary) return <div className="loading">正在加载评估记录…</div>;
  const plan = summary.experiment.plan;
  const scopes = new Set(session.scopes);
  async function createTask(sample) {
    setBusy(sample.key); setError(null);
    try {
      await call('/research', { method: 'POST', key: sample.key, body: {
        workspace: session.workspace, experiment: plan.experiment, template: sample.template, mandate: sample.mandate,
      } }); notify('计划样本已开始研究，完成后自动生成报告。'); onRefresh();
    } catch (err) { setError(err); } finally { setBusy(''); }
  }
  async function bind(sample, taskId) {
    setBusy(sample.key); setError(null);
    try {
      const task = tasks?.items.find(t => t.id === taskId);
      let reportId = task?.report_id;
      if (!reportId) reportId = (await call(`/tasks/${taskId}/report`, { method: 'POST', body: {} })).id;
      const value = await call(`/experiments/${summary.experiment.id}/predictions`, {
        method: 'POST', body: { task_id: taskId, report_id: reportId },
      }); setPrediction(value); notify('预测已绑定固定报告。'); onRefresh();
    } catch (err) { setError(err); } finally { setBusy(''); }
  }
  async function loadPrediction(id) {
    setError(null);
    try { setPrediction(await call(`/predictions/${id}`)); } catch (err) { setError(err); }
  }
  const sample = prediction ? plan.samples.find(s => s.key === prediction.sample_key) : null;
  return <section className="panel evaluation-detail">
    <button className="text-button back" onClick={onBack}>返回评估实验</button>
    <div className="detail-heading"><div><h2>{plan.experiment}</h2><p>完整计划分母保留，短窗口观察不构成最终投资判定。</p></div><Badge value={plan.mode} /></div>
    <div className="metric-row compact-metrics">{[['计划样本', summary.planned_total], ['完整期限', summary.final_samples],
      ['中期观察', summary.interim_samples], ['待观察', summary.pending_samples]].map(([name, value]) =>
      <div key={name}><span>{name}</span><strong>{value}</strong></div>)}</div>
    <ErrorLine error={error} />
    <div className="evaluation-samples">{summary.samples.map(row => {
      const planned = plan.samples.find(s => s.key === row.key);
      const task = tasks?.items.find(t => t.id === row.task_ids[0]);
      return <div className="sample-row" key={row.key}><div><strong>{planned.mandate.ticker} · {session.demo_mode ? '合成演示样本' : row.key}</strong>
        <small>{planned.sessions[0]} → {planned.sessions.at(-1)} · {planned.mandate.benchmark}</small></div>
        <div><Badge value={row.observation_status} /><small>{row.task_statuses.map(label).join(' / ')}</small></div><div>
          {!row.task_ids.length && scopes.has('task:create') ? <Button secondary disabled={busy === row.key} onClick={() => createTask(planned)}>开始样本研究</Button> : null}
          {row.prediction_id ? <Button secondary onClick={() => loadPrediction(row.prediction_id)}>查看预测与观察</Button>
            : task?.status === 'succeeded' && scopes.has('evaluation:write') && scopes.has('report:register')
              ? <Button secondary disabled={busy === row.key} onClick={() => bind(planned, task.id)}>固定预测</Button> : null}
        </div></div>;
    })}</div>
    <p className="muted small">任务 {summary.task_total} · 未提交 {summary.not_submitted} · 失败 {summary.task_statuses.failed} · 取消 {summary.task_statuses.cancelled}
      · 未计划任务 {summary.unplanned_task_total} · 评级待判断 {summary.rating_counts.REVIEW || 0}</p>
    {prediction ? <div className="prediction-panel"><div className="panel-heading"><h3>{sample.mandate.ticker} 预测与观察</h3>
      {scopes.has('evaluation:write') ? <Button secondary onClick={() => setObservation(true)}>登记观察</Button> : null}</div>
      <p>固定评级：{label(prediction.rating)} · 报告 {shortId(prediction.report_id)} · 登记时状态 {label(prediction.report_status_at_registration)}</p>
      {prediction.observations.length ? <>
        <div className="observation-cards">{prediction.observations.map(o => <div key={o.id}>
          <p>{label(o.result.window)} · {o.input.exit_session}</p>
          <div>{[['标的收益', o.result.asset_return], ['基准收益', o.result.benchmark_return], ['收益差', o.result.excess_return]].map(([name, value]) =>
            <span key={name}><small>{name}</small><strong>{(Number(value) * 100).toFixed(4)}%</strong></span>)}</div>
        </div>)}</div>
        <div className="table-scroll observation-table"><table><thead><tr><th>窗口</th><th>出口日</th><th>标的收益</th><th>基准收益</th><th>收益差</th></tr></thead>
        <tbody>{prediction.observations.map(o => <tr key={o.id}><td><Badge value={o.result.window} /></td><td>{o.input.exit_session}</td>
          {[o.result.asset_return, o.result.benchmark_return, o.result.excess_return].map((r, i) => <td key={i}>{(Number(r) * 100).toFixed(4)}%</td>)}</tr>)}</tbody></table></div></>
        : <p className="muted">尚未记录价格观察。</p>}
      <p className="muted small">收益不含仓位、融资、交易费用或成交。历史模型事后知识：未知。</p></div> : null}
    <details className="form-details"><summary>固定计划与日历依据</summary><pre>{JSON.stringify(plan, null, 2)}</pre></details>
    {observation && prediction ? <ObserveDialog prediction={prediction} sample={sample} basis={plan.price_basis} call={call}
      demoValues={session.demo_mode ? summary.demo_observation : undefined}
      onClose={() => setObservation(false)} onDone={() => { notify('观察记录已保存。'); loadPrediction(prediction.id); onRefresh(); }} /> : null}
  </section>;
}
