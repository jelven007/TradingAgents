import React, { useState } from 'react';
import { dateTime, shortId, usd } from './api';
import { Button, Empty, ErrorLine, Field, Modal } from './components';
import { ConfirmDialog } from './forms';

function InvoiceDialog({ callRecord, call, onClose, onDone }) {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError(null);
    const data = new FormData(event.currentTarget);
    const amount = data.get('amount');
    const [whole, fraction = ''] = amount.split('.');
    const micro = Number(whole) * 1000000 + Number(fraction.padEnd(6, '0'));
    if (!/^\d+(\.\d{1,6})?$/.test(amount) || !Number.isSafeInteger(micro)) {
      setError(new Error('金额最多6位小数，且必须为非负美元数。')); setBusy(false); return;
    }
    try {
      await call(`/calls/${callRecord.id}/reconcile`, { method: 'POST', body: {
        amount_microusd: micro, invoice_ref: data.get('invoice'),
      } }); onDone(); onClose();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return <Modal title="登记模型账单" subtitle="对账一次固定；金额和账单行冲突不能覆盖原记录。" onClose={onClose}>
    <form onSubmit={submit}><Field label="实际金额（USD）"><input name="amount" required inputMode="decimal" autoFocus placeholder="0.012500" /></Field>
      <Field label="账单行引用"><input name="invoice" maxLength={200} required /></Field>
      <ErrorLine error={error} /><div className="modal-footer"><Button type="button" secondary onClick={onClose}>取消</Button>
        <Button disabled={busy}>{busy ? '保存中…' : '确认对账'}</Button></div></form>
  </Modal>;
}

export function OperationsPage({ operations, audit, session, call, notify, onRefresh }) {
  const [control, setControl] = useState(null);
  const [invoice, setInvoice] = useState(null);
  const [tab, setTab] = useState('calls');
  const scopes = new Set(session.scopes);
  if (!operations && !audit) return <div className="loading">正在加载运营信息…</div>;
  return <>
    {operations ? <>
      <div className="metric-row ops-metrics">{[['模型调用', operations.model_calls], ['累计预留', usd(operations.reserved_microusd)],
        ['已对账', usd(operations.invoiced_microusd)], ['费用待对账', operations.unknown_cost_calls]].map(([title, value]) =>
        <div key={title}><span>{title}</span><strong>{value}</strong></div>)}</div>
      <section className="panel controls-panel"><div><h2>工作空间控制</h2><p>按需暂停新增研究或冻结报告发布，操作原因会保留。</p></div>
        <div className="controls">
          {[['pause_submissions', '暂停新研究'], ['freeze_publication', '冻结报告发布']].map(([kind, title]) =>
            <button key={kind} className={`switch-control ${operations.controls[kind] ? 'on' : ''}`} aria-pressed={operations.controls[kind]}
              disabled={!scopes.has('ops:control')} onClick={() => setControl({ kind, title, enabled: !operations.controls[kind] })}>
              <span>{title}<small>{operations.controls[kind] ? '已启用' : '未启用'}</small></span><span className="switch-track"><span /></span></button>)}
        </div></section>
    </> : null}
    <section className="panel"><div className="panel-heading"><h2>运营记录</h2><div className="tabs" role="tablist" aria-label="运营记录">
      {operations ? <button role="tab" aria-selected={tab === 'calls'} className={tab === 'calls' ? 'active' : ''} onClick={() => setTab('calls')}>模型调用账本</button> : null}
      {scopes.has('audit:read') ? <button role="tab" aria-selected={tab === 'audit'} className={tab === 'audit' ? 'active' : ''} onClick={() => setTab('audit')}>访问审计</button> : null}
    </div></div>
      {tab === 'calls' && operations ? operations.call_ledger.length ? <div className="table-scroll"><table><thead><tr><th>调用 / 任务</th><th>模型</th><th>预留额</th><th>实际费用</th><th>对账</th></tr></thead>
        <tbody>{operations.call_ledger.map(c => <tr key={c.id}><td><code>{shortId(c.id)}</code><small>任务 {shortId(c.task_id)}</small></td>
          <td>{c.model}<small>{c.status}</small></td><td>{usd(c.reserved_microusd)}</td><td>{usd(c.actual_microusd)}</td>
          <td>{c.actual_microusd == null && scopes.has('cost:reconcile') ? <button className="text-button" onClick={() => setInvoice(c)}>登记账单</button> : '—'}</td></tr>)}</tbody></table></div>
        : <Empty icon="ops" title="暂无模型调用" text="所有任务的模型调用，包括失败与取消产生的调用，都会进入账本。" />
        : audit?.length ? <div className="table-scroll"><table><thead><tr><th>时间</th><th>操作者</th><th>操作</th><th>结果</th><th>关联请求</th></tr></thead>
          <tbody>{audit.map(e => <tr key={e.seq}><td>{dateTime(e.at)}</td><td>{e.subject}</td><td>{e.action}</td><td>{e.outcome}</td><td><code>{shortId(e.request_id)}</code></td></tr>)}</tbody></table></div>
          : <Empty title="暂无访问记录" text="使用审计权限可查看当前工作空间的操作记录。" />}
    </section>
    <p className="muted small">费用仅覆盖模型调用，不包含数据、基础设施和人工成本。未知费用单列，累计预留不是实际账单。最近最多展示200条调用 / 审计记录。</p>
    {control ? <ConfirmDialog title={`${control.enabled ? '启用' : '解除'}${control.title}`} description="已有任务及已发出的请求仍按原状态处理。"
      onClose={() => setControl(null)} confirmText="确认调整" onConfirm={async reason => {
        await call('/controls', { method: 'POST', body: { kind: control.kind, enabled: control.enabled, reason } });
        notify('工作空间控制已更新。'); onRefresh();
      }} /> : null}
    {invoice ? <InvoiceDialog callRecord={invoice} call={call} onClose={() => setInvoice(null)} onDone={() => { notify('实际账单已固定保存。'); onRefresh(); }} /> : null}
  </>;
}
