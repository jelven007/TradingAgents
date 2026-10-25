import React, { useState } from 'react';
import { dateTime, label, shortId } from './api';
import { Badge, Button, Empty, ErrorLine, Icon, Pager } from './components';
import { InputSummary } from './input-summary';

export function TaskTable({ items, onSelect, onCreate, compact = false }) {
  if (!items.length) return <Empty title="尚无研究任务" text="从一个明确的研究问题开始，留下可追踪的证据与结论。"
    action={onCreate} actionLabel="创建你的第一份研究" />;
  return <div className="table-scroll"><table>
    <thead><tr><th>标的 / 研究用途</th><th>研究日期</th><th>期限 / 基准</th><th>状态</th>{!compact ? <th>创建时间</th> : null}<th><span className="sr-only">查看</span></th></tr></thead>
    <tbody>{items.map(task => <tr key={task.id}>
      <td><button className="entity-link" onClick={() => onSelect(task.id)}>{task.mandate.ticker}</button>
        <small>{task.experiment || shortId(task.id)}</small></td>
      <td>{task.mandate.analysis_date}</td><td>{task.mandate.prediction_horizon_trading_days} 个交易日<small>{task.mandate.benchmark}</small></td>
      <td><Badge value={task.status} /></td>{!compact ? <td>{dateTime(task.created)}</td> : null}
      <td><button className="icon-button" onClick={() => onSelect(task.id)} aria-label={`查看 ${task.mandate.ticker} 研究任务`}><Icon name="chevron" size={17} /></button></td>
    </tr>)}</tbody>
  </table></div>;
}

export function TasksPage({ tasks, onSelect, onCreate, offset, onOffset, loading }) {
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all');
  const items = (tasks?.items || []).filter(task =>
    `${task.mandate.ticker} ${task.experiment}`.toLowerCase().includes(search.toLowerCase()) &&
    (status === 'all' || task.status === status));
  return <section className="panel">
    <div className="panel-heading"><h2>研究任务 <span className="count">{tasks?.total || 0}</span></h2>
      <div className="filters"><input type="search" aria-label="搜索标的或实验" placeholder="搜索标的或实验" value={search} onChange={e => setSearch(e.target.value)} />
        <select aria-label="筛选任务状态" value={status} onChange={e => setStatus(e.target.value)}><option value="all">全部状态</option>
          {['queued', 'running', 'succeeded', 'failed', 'cancelled', 'timed_out'].map(s => <option value={s} key={s}>{label(s)}</option>)}</select></div>
    </div>
    {loading && !tasks ? <div className="loading">正在加载任务…</div> : items.length || !search && status === 'all'
      ? <TaskTable items={items} onSelect={onSelect} onCreate={onCreate} />
      : <Empty title="没有匹配的研究" text="试试其他标的或状态筛选。" />}
    <Pager total={tasks?.total || 0} offset={offset} onChange={onOffset} />
  </section>;
}

const stageHelp = {
  '行情分析': '整理价格与成交量，检查价格日期和币种。',
  '情绪分析': '整理讨论中的观点；讨论不等同于公司事实。',
  '新闻分析': '整理消息与事件，保留来源输出。',
  '基本面分析': '整理公司财务与经营资料。',
  '多方研究': '整理支持研究判断的理由。',
  '空方研究': '整理反对研究判断的理由。',
  '研究综合': '汇总分析依据和研究判断。',
  '方案分析': '整理本次期限内的研究方案。',
  '风险讨论': '讨论判断的风险与失效条件。',
  '形成研究结论': '形成最终研究观点，随后生成固定报告。',
  '读取历史研究': '读取可用的历史研究记录。',
  '证据与质量校验': '检查已留存的来源与确定性规则。',
  '生成固定报告': '整理已接受的结果为可阅读报告。',
};

export function TaskDetail({ task, call, scopes, onBack, onRefresh, notify, onReport, onSettings, beginner, onRetry }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [confirmCancel, setConfirmCancel] = useState(false);
  async function act(action) {
    setBusy(true); setError(null);
    try {
      const result = await call(`/tasks/${task.id}/${action}`, { method: 'POST', body: {} });
      if (action === 'report') {
        notify('报告已登记为固定版本。'); onReport(result.id);
      } else {
        notify(action === 'execute' ? '执行已请求，任务进度会自动更新。' : '任务已取消。');
        onRefresh();
      }
    } catch (err) { setError(err); } finally { setBusy(false); setConfirmCancel(false); }
  }
  if (!task) return <div className="loading">正在加载任务…</div>;
  return <div className="detail-layout">
    <section className="panel detail-main">
      <button className="text-button back" onClick={onBack}>返回研究任务</button>
      <div className="detail-heading"><div><h2>{task.mandate.ticker} 研究</h2><p>{task.mandate.analysis_date} · {task.experiment}</p></div><Badge value={task.status} /></div>
      {beginner ? <div className="beginner-task-action">{task.report_id ? <Button icon="report" onClick={() => onReport(task.report_id)}>查看研究报告</Button>
        : ['queued', 'running'].includes(task.status) ? <p role="status">研究正在整理资料，完成后可在这里阅读报告。可以离开页面，在“我的最近研究”继续查看。</p> : null}</div> : null}
      <div className="facts-grid">
        <div><span>研究期限</span><strong>{task.mandate.prediction_horizon_trading_days} 个交易日</strong></div>
        <div><span>对照基准</span><strong>{task.mandate.benchmark}</strong></div>
        <div><span>报价币种</span><strong>{task.mandate.quote_currency}</strong></div>
        <div><span>报告有效至</span><strong>{task.mandate.valid_until}</strong></div>
        <div><span>研究员</span><strong>{task.author}</strong></div><div><span>模型调用</span><strong>{task.calls} 次</strong></div>
      </div>
      <InputSummary inputs={task.inputs} />
      {task.progress?.stage ? <div className="research-progress" role="status"><strong>{task.status === 'running' ? `正在进行：${task.progress.stage}` : '研究阶段记录'}</strong>
        {beginner ? <p>{stageHelp[task.progress.stage] || '正在整理本阶段研究内容。'}可以离开页面，回到“我的最近研究”继续查看。</p> : null}
        <p>{task.progress.stages.join(' → ')}</p><small>已调用模型 {task.calls} 次 · 上限 {task.progress.max_calls} 次</small></div> : null}
      {task.execution.credentials_present === false && task.status === 'queued'
        ? <div className="notice"><strong>尚未配置模型</strong><p>在设置中填写模型与 API Key，保存后新建研究即可使用该配置。</p>
          {scopes.has('settings:read') ? <button className="text-button" onClick={onSettings}>前往模型设置<Icon name="arrow" size={16} /></button> : null}</div> : null}
      {task.status === 'failed' || task.status === 'timed_out'
        ? <div className="notice error-notice"><strong>研究未成功完成</strong><p>{task.status === 'timed_out' ? '超过本次执行时长上限，请核对时长及模型响应。'
          : task.error_type === 'BudgetExceeded' ? '原流程达到预算或调用上限。重新研究将使用有界的默认股票路线，系统会先核对预算是否足够。'
            : ['AuthenticationError', 'AuthenticationMissing'].includes(task.error_type) ? '模型身份验证失败，请检查已配置服务凭据。'
              : '执行记录尚不能确认具体原因。请检查研究输入和服务设置，再重新研究。'}</p>
          <small>记录分类：{task.error_type || 'Unknown'}</small>
          {scopes.has('task:create') ? <Button secondary onClick={() => onRetry(task)}>使用推荐配置重新研究</Button> : null}</div> : null}
      <ErrorLine error={error} />
      <div className="detail-actions">
        {task.status === 'queued' && scopes.has('task:execute') ? <Button icon="arrow" disabled={busy || !task.execution.credentials_present} onClick={() => act('execute')}>执行研究</Button> : null}
        {task.report_id ? !beginner ? <Button icon="report" onClick={() => onReport(task.report_id)}>查看研究报告</Button> : null
          : task.status === 'succeeded' && scopes.has('report:register') ? <Button icon="report" disabled={busy} onClick={() => act('report')}>生成研究报告</Button> : null}
        {['queued', 'running'].includes(task.status) && scopes.has('task:cancel')
          ? <Button secondary disabled={busy} onClick={() => setConfirmCancel(true)}>取消任务</Button> : null}
      </div>
      {confirmCancel ? <div className="inline-confirm" role="alert"><span>取消后将停止后续调用，已发出的请求仍可能计费。</span>
        <Button danger disabled={busy} onClick={() => act('cancel')}>确认取消</Button><Button secondary onClick={() => setConfirmCancel(false)}>继续保留</Button></div> : null}
      <h3 className="section-title">任务时间线</h3>
      <ol className="timeline">{(task.events || []).map((event, index) => <li key={index}>
        <span className="timeline-dot" /><div><strong>{{
          submitted: '创建研究任务', claimed: '开始执行研究', succeeded: '结果已通过完整性校验',
          failed: '研究执行失败', cancelled: '任务取消', timed_out: '执行超时', recovery_fenced: '恢复时隔离任务',
          stage: event.stage, auto_report_requested: '已安排自动生成报告', report_registered: '固定报告已生成',
        }[event.action] || label(event.action)}</strong><small>{dateTime(event.at)}</small></div></li>)}</ol>
    </section>
    <aside className="panel detail-aside"><h3>研究记录</h3><p>任务ID</p><code className="break">{task.id}</code>
      <p>创建时间</p><span>{dateTime(task.created)}</span><p>执行次数</p><span>{task.attempt_count}</span>
      {task.manifest_hash ? <><p>结果完整性指纹</p><code className="break">{task.manifest_hash}</code></> : null}
      <div className="aside-note">只有完成且被接受的结果能登记为报告。复核与发布保留为独立操作。</div>
    </aside>
  </div>;
}
