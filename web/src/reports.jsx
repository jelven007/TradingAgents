import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { dateTime, label, qualityIssue, shortId } from './api';
import { Badge, Button, Empty, ErrorLine, Field, Icon, Modal, Pager } from './components';
import { InputSummary } from './input-summary';
import { ReportBrief, company } from './investor';

export function ReportsPage({ reports, onSelect, offset, onOffset }) {
  const [status, setStatus] = useState('all');
  const items = (reports?.items || []).filter(report => status === 'all' || report.status === status);
  return <section className="panel">
    <div className="panel-heading"><h2>报告与复核 <span className="count">{reports?.total || 0}</span></h2>
      <select aria-label="筛选报告状态" value={status} onChange={e => setStatus(e.target.value)}><option value="all">全部报告</option>
        {['draft', 'approved', 'published', 'rejected', 'withdrawn'].map(s => <option key={s} value={s}>{label(s)}</option>)}</select></div>
    {items.length ? <div className="table-scroll"><table><thead><tr><th>研究报告</th><th>评级</th><th>质量检查</th><th>复核状态</th><th>作者</th><th>查看</th></tr></thead>
      <tbody>{items.map(report => <tr key={report.id}><td><button className="entity-link" onClick={() => onSelect(report.id)}>{report.mandate.ticker}</button>
        <small>{report.mandate.analysis_date} · {report.mandate.prediction_horizon_trading_days} 个交易日</small></td>
        <td>{label(report.rating)}</td><td><Badge value={report.quality_status} /></td><td><Badge value={report.status} />{report.expired ? <small className="danger-text">已过期</small> : null}</td>
        <td>{report.author}</td><td><button className="icon-button" onClick={() => onSelect(report.id)} aria-label={`打开 ${report.mandate.ticker} 报告`}><Icon name="chevron" /></button></td></tr>)}</tbody></table></div>
      : <Empty title="暂无研究报告" text="任务完成后，研究员可登记固定报告，再交给复核员审核。" />}
    <Pager total={reports?.total || 0} offset={offset} onChange={onOffset} />
  </section>;
}

function ReviewDialog({ report, action, call, onClose, onDone }) {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const reviews = report.quality.issues.filter(issue => issue.severity === 'review');
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError(null);
    const data = new FormData(event.currentTarget);
    try {
      await call(`/reports/${report.id}/review`, { method: 'POST', body: {
        action, reason: data.get('reason'), acknowledgements: data.getAll('ack'),
      } }); onDone(); onClose();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return <Modal title={`${label(action)}报告`} subtitle="操作绑定当前固定版本，理由与核验记录会保留。" onClose={onClose}>
    <form onSubmit={submit}>
      {action === 'approved' && reviews.length ? <div className="acknowledgements"><h3>逐项确认待核验内容</h3>
        {reviews.map(issue => <label key={issue.code}><input type="checkbox" name="ack" value={issue.code} required />
          <span><strong>{qualityIssue(issue).title}</strong>{qualityIssue(issue).description}</span></label>)}</div> : null}
      <Field label="操作理由"><textarea name="reason" autoFocus rows={4} required maxLength={4000} /></Field>
      <ErrorLine error={error} /><div className="modal-footer"><Button type="button" secondary onClick={onClose}>取消</Button>
        <Button disabled={busy} danger={action === 'withdrawn' || action === 'rejected'}>{busy ? '处理中…' : `确认${label(action)}`}</Button></div>
    </form>
  </Modal>;
}

export function ReportDetail({ report, session, call, onBack, onRefresh, notify, beginner = false, onWatchlist }) {
  const [tab, setTab] = useState(beginner ? 'brief' : 'content');
  const [reviewAction, setReviewAction] = useState(null);
  const scopes = new Set(session.scopes);
  if (!report) return <div className="loading">正在加载报告…</div>;
  const blocked = report.quality.issues.some(issue => issue.severity === 'block');
  const selfReview = session.subject === report.author;
  const markdown = (report.report_markdown || '').replace(/独立(?=复核员)/g, '');
  function download() {
    const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }));
    const anchor = document.createElement('a'); anchor.href = url;
    anchor.download = `${report.mandate.ticker}-${report.mandate.analysis_date}-${shortId(report.id).replace('…', '')}.md`;
    anchor.click(); URL.revokeObjectURL(url);
  }
  return <>
    <section className="panel report-detail">
      <button className="text-button back" onClick={onBack}>返回报告列表</button>
      <div className="detail-heading"><div><h2>{company(session, report.mandate.ticker)} · 研究报告</h2>
        <p>{report.mandate.analysis_date} · 基准 {report.mandate.benchmark} · {report.mandate.prediction_horizon_trading_days} 个交易日</p></div>
        <div className="report-state"><Badge value={report.status} />{!beginner ? <span>{label(report.rating)}</span> : null}</div></div>
      <div className="report-toolbar"><div className="tabs" role="tablist" aria-label="报告内容">
        {[...(report.brief ? [['brief', '简明概览']] : []), ['content', '研究正文'], ['quality', '独立质量检查'], ['audit', '复核记录']].map(([id, title]) =>
          <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{title}</button>)}
      </div><Button secondary icon="download" onClick={download}>下载报告</Button></div>
      {report.expired ? <div className="notice error-notice">报告已过有效期，无法批准或发布。</div> : null}
      {blocked ? <div className="notice error-notice">独立规则发现阻断项；需要新研究版本解决，不能通过人工勾选豁免。</div> : null}
      {selfReview && report.status === 'draft' ? <div className="notice">作者不能复核自己的报告，请由复核员连接工作空间。</div> : null}
      {tab !== 'brief' ? <InputSummary inputs={report.inputs} /> : null}
      {tab === 'brief' ? <ReportBrief report={report} call={call} canWrite={scopes.has('task:create')}
        onQuality={() => setTab('quality')} onContent={() => setTab('content')} onWatchlist={onWatchlist} notify={notify} onRefresh={onRefresh} />
      : tab === 'content' ? <article className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}
        components={{ img: ({ alt }) => <span className="muted">{alt || '报告图像引用'}</span>, a: ({ href, children }) =>
          <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> }}>{markdown || '暂无报告正文。'}</ReactMarkdown></article>
        : tab === 'quality' ? <div className="quality-content"><div className="quality-header"><h3>确定性规则检查</h3><Badge value={report.quality.status} /></div>
          {report.quality.issues.map((issue, i) => <div className={`quality-issue severity-${issue.severity}`} key={`${issue.code}-${i}`}>
            <span>{issue.severity === 'block' ? '阻断' : '核验'}</span><div><strong>{qualityIssue(issue).title}</strong><p>{qualityIssue(issue).description}</p>
              <details><summary>查看原始规则记录</summary><code>{issue.code}</code><p>{issue.detail}</p></details></div></div>)}
          <h3>结构化计算</h3>{report.quality.calculations.length ? <pre>{JSON.stringify(report.quality.calculations, null, 2)}</pre>
            : <p className="muted">没有可展示的结构化计算。</p>}
          <div className="aside-note">质量检查覆盖结构化数据与规则；自然语言论据仍需研究负责人核验。</div></div>
          : <div className="quality-content"><ol className="timeline">{report.events.map(event => <li key={event.event_hash}>
            <span className="timeline-dot" /><div><strong>{label(event.action)} · {event.actor}</strong><p>{event.reason}</p>
              <small>{dateTime(event.at)}</small></div></li>)}</ol><p>固定内容指纹</p><code className="break">{report.manifest_hash}</code></div>}
      <div className="review-actions">
        <span className="muted">报告作者：{report.author}</span><div>
          {report.status === 'draft' && scopes.has('report:review') ? <>
            <Button secondary disabled={selfReview} onClick={() => setReviewAction('rejected')}>退回修改</Button>
            <Button disabled={selfReview || blocked || report.expired} onClick={() => setReviewAction('approved')}>批准报告</Button></> : null}
          {report.status === 'approved' && scopes.has('report:publish') ? <Button disabled={blocked || report.expired} onClick={() => setReviewAction('published')}>发布报告</Button> : null}
          {['draft', 'approved', 'published'].includes(report.status) && scopes.has('report:withdraw')
            ? <Button danger secondary onClick={() => setReviewAction('withdrawn')}>撤回报告</Button> : null}
        </div></div>
    </section>
    {reviewAction ? <ReviewDialog report={report} action={reviewAction} call={call} onClose={() => setReviewAction(null)}
      onDone={() => { notify('报告状态已更新，复核记录已保存。'); onRefresh(); }} /> : null}
  </>;
}
