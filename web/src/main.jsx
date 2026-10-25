import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { request, setSessionCsrf } from './api';
import { Button, Empty, ErrorLine, Icon, PageHeading, Permission } from './components';
import { ConnectDialog, ResearchDialog } from './forms';
import { researchDraft } from './research-form';
import { ResearchSettingsPage } from './research-settings';
import { TaskDetail, TasksPage, TaskTable } from './tasks';
import { ReportDetail, ReportsPage } from './reports';
import { ExperimentDetail, ExperimentsPage, PlanDialog } from './evaluation';
import { OperationsPage } from './operations';
import { SettingsPage } from './settings';
import { AccountsPage, AuthPage, roleNames } from './auth';
import { BeginnerGuide, BeginnerHome, WatchlistPage } from './investor';
import './style.css';
import './investor.css';

const nav = [
  ['home', '工作台', 'grid'], ['tasks', '研究任务', 'task'], ['reports', '报告与复核', 'report'],
  ['evaluation', '评估实验', 'experiment'], ['operations', '运营与审计', 'ops'],
  ['settings', '设置', 'settings'],
  ['watchlist', '关注清单', 'shield'], ['guide', '入门指南', 'report'],
];
const descriptions = {
  tasks: ['研究任务', '从研究契约出发，追踪每一次执行和结果。'],
  reports: ['报告与复核', '阅读固定报告，核验证据，再作独立复核。'],
  evaluation: ['评估实验', '在相同期限、币种与基准下观察研究结果。'],
  operations: ['运营与审计', '查看完整任务分母、模型费用与工作空间控制。'],
  settings: ['设置', '配置研究模板、默认参数与模型，让研究按你的输入运行。'],
  watchlist: ['我的关注清单', '保存感兴趣的对象，记下需要核实的事项。'],
  guide: ['入门指南', '用简单的解释读懂公司研究。'],
};

function App() {
  const [token, setToken] = useState('');
  const [session, setSession] = useState(null);
  const [authStatus, setAuthStatus] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState(null);
  const [authVersion, setAuthVersion] = useState(0);
  const [settingsTab, setSettingsTab] = useState('models');
  const [page, setPage] = useState(() => nav.some(n => n[0] === location.hash.slice(1)) ? location.hash.slice(1) : 'home');
  const [connect, setConnect] = useState(false);
  const [create, setCreate] = useState(false);
  const [draft, setDraft] = useState(null);
  const [returnResearch, setReturnResearch] = useState(false);
  const [plan, setPlan] = useState(false);
  const [menu, setMenu] = useState(false);
  const [tasks, setTasks] = useState(null);
  const [reports, setReports] = useState(null);
  const [experiments, setExperiments] = useState(null);
  const [operations, setOperations] = useState(null);
  const [audit, setAudit] = useState(null);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState('');
  const [version, setVersion] = useState(0);
  const [investor, setInvestor] = useState(null);
  const [mode, setMode] = useState(() => {
    try { return localStorage.getItem('ta-display-v1') || 'auto'; } catch { return 'auto'; }
  });
  const generation = useRef(0);
  const scopes = new Set(session?.scopes || []);
  const demoMode = Boolean(session?.demo_mode);
  const beginner = Boolean(session?.investor_tools && (mode === 'beginner' || mode === 'auto'
    && !['reviewer', 'operator'].includes(session?.account?.role)));
  function changeMode() {
    const next = beginner ? 'professional' : 'beginner';
    setMode(next);
    try { localStorage.setItem('ta-display-v1', next); } catch {}
    navigate('home');
  }
  const call = useCallback((path, options) => request(token, demoMode ? `/demo${path}` : path, options), [token, demoMode]);
  const notify = message => setNotice(message);
  const refresh = () => setVersion(value => value + 1);
  function navigate(next) { setPage(next); history.replaceState(null, '', `#${next}`); setSelected(null); setDetail(null); setOffset(0); setMenu(false); setError(null); window.scrollTo({ top: 0 }); }
  function select(next, id) { navigate(next); setSelected(id); }
  function disconnect() {
    generation.current++; setSession(null); setToken(''); setTasks(null); setReports(null);
    setExperiments(null); setOperations(null); setAudit(null); setSelected(null); setDetail(null); setError(null);
    setSessionCsrf(''); setCreate(false); setPlan(false); setSettingsTab('models'); setMenu(false);
    setDraft(null); setReturnResearch(false);
    setInvestor(null);
  }
  function passwordLogin(identity) {
    disconnect(); setSessionCsrf(identity.csrf); setSession(identity); setConnect(false);
    if (identity.demo_mode) sessionStorage.setItem('ta-demo', 'yes');
    else sessionStorage.removeItem('ta-demo');
    navigate('home'); setVersion(v => v + 1);
  }
  async function enterDemo() {
    try { passwordLogin(await request('', '/demo/enter', { method: 'POST', body: {} })); }
    catch (err) { setAuthError(err); setError(err); }
  }
  async function switchDemo(role) {
    try {
      const identity = await call('/role', { method: 'POST', body: { role } });
      passwordLogin(identity); notify(`已切换为${roleNames[role]}。`);
    } catch (err) { setError(err); }
  }
  async function logout() {
    if (['password', 'demo'].includes(session?.auth_method)) {
      try { await call('/auth/logout', { method: 'POST', body: {} }); }
      catch (err) { setError(err); return; }
    }
    sessionStorage.removeItem('ta-demo');
    disconnect();
  }
  async function login(credential) {
    const identity = await request(credential, '/session');
    disconnect(); setToken(credential); setSession(identity); setConnect(false); setVersion(v => v + 1);
    notify(`已连接 ${identity.workspace} 工作空间。`);
  }
  async function modelsSaved() {
    const current = generation.current;
    const identity = await call('/session');
    if (current === generation.current) setSession(identity);
  }
  useEffect(() => {
    const controller = new AbortController();
    setAuthLoading(true); setAuthError(null);
    async function restore() {
      try {
        const status = await request('', '/auth/status', { signal: controller.signal });
        if (controller.signal.aborted) return;
        setAuthStatus(status);
        if (status.demo_enabled && sessionStorage.getItem('ta-demo') === 'yes') {
          try {
            const identity = await request('', '/demo/session', { signal: controller.signal });
            if (!controller.signal.aborted) { setSessionCsrf(identity.csrf); setSession(identity); }
            return;
          } catch (err) { if (err.status !== 401) throw err; sessionStorage.removeItem('ta-demo'); }
        }
        if (status.accounts_enabled && !status.setup_required) {
          try {
            const identity = await request('', '/auth/session', { signal: controller.signal });
            if (!controller.signal.aborted) { setSessionCsrf(identity.csrf); setSession(identity); }
          } catch (err) { if (err.status !== 401) throw err; }
        }
      } catch (err) {
        if (err.name !== 'AbortError') {
          if ([401, 404].includes(err.status)) setAuthStatus({ accounts_enabled: false });
          else setAuthError(err);
        }
      } finally { if (!controller.signal.aborted) setAuthLoading(false); }
    }
    restore();
    return () => controller.abort();
  }, [authVersion]);
  useEffect(() => {
    if (!notice) return;
    const timeout = setTimeout(() => setNotice(''), 5500);
    return () => clearTimeout(timeout);
  }, [notice]);
  useEffect(() => {
    if (!session) return;
    const controller = new AbortController();
    const current = ++generation.current;
    const keep = setter => value => { if (current === generation.current && !controller.signal.aborted) setter(value); };
    async function load() {
      setLoading(true);
      try {
        const fetches = [];
        if (session.investor_tools && scopes.has('task:read')) fetches.push(call('/watchlist', { signal: controller.signal }).then(keep(setInvestor)));
        if (scopes.has('task:read')) fetches.push(call(`/tasks?offset=${page === 'tasks' ? offset : 0}`, { signal: controller.signal }).then(keep(setTasks)));
        if (scopes.has('report:read')) fetches.push(call(`/reports?offset=${page === 'reports' ? offset : 0}`, { signal: controller.signal }).then(keep(setReports)));
        if (scopes.has('evaluation:read') && page === 'evaluation') fetches.push(call(`/experiments?offset=${offset}`, { signal: controller.signal }).then(keep(setExperiments)));
        if (scopes.has('ops:read') && ['home', 'operations'].includes(page)) fetches.push(call('/operations', { signal: controller.signal }).then(keep(setOperations)));
        if (scopes.has('audit:read') && page === 'operations') fetches.push(call('/audit', { signal: controller.signal }).then(keep(setAudit)));
        if (selected) {
          const prefix = { tasks: 'tasks', reports: 'reports', evaluation: 'experiments' }[page];
          fetches.push(call(`/${prefix}/${selected}`, { signal: controller.signal }).then(keep(setDetail)));
        }
        await Promise.all(fetches);
        if (current === generation.current) setError(null);
      } catch (err) {
        if (err.name !== 'AbortError' && current === generation.current) {
          if (err.status === 401) { disconnect(); setAuthStatus(current => ({ ...current, setup_required: false })); }
          setError(err);
        }
      } finally { if (current === generation.current) setLoading(false); }
    }
    load();
    return () => controller.abort();
  }, [token, session?.subject, demoMode, page, selected, offset, version]);
  useEffect(() => {
    if (!session || !tasks?.items.some(t => ['queued', 'running'].includes(t.status) || t.status === 'succeeded' && !t.report_id)) return;
    const interval = setInterval(() => {
      if (document.visibilityState === 'visible') setVersion(v => v + 1);
    }, 1500);
    return () => clearInterval(interval);
  }, [session, tasks, page]);
  async function openCreate(symbol) {
    if (!session.stock_catalog) { notify('股票研究入口已更新，请打开页面上的新版工作台链接。'); return; }
    if (!scopes.has('task:create')) { notify('当前账号可查看研究，创建研究请使用研究员或管理员账号。'); return; }
    if (!session.templates.length) { navigate('settings'); setSettingsTab('research'); return; }
    if (typeof symbol === 'string') {
      const template = session.templates.find(t => t.tickers.includes(symbol) || t.allow_listed_stocks);
      if (!template) { notify('当前对象已不在批准清单中，请先配置研究模板。'); return; }
      let security = session.instruments?.find(i => i.symbol === symbol);
      if (!security && template.allow_listed_stocks) {
        try { security = (await call(`/instruments?q=${encodeURIComponent(symbol)}&limit=1`)).items.find(i => i.symbol === symbol); }
        catch { notify('股票资料暂时无法读取，请在新建研究中重新搜索。'); }
      }
      setDraft({ ...researchDraft(session, template), ticker: symbol, selected_security: security || null,
        currency: security?.quote_currency || 'USD', benchmark: security?.benchmark || 'SPY' });
    } else if (!draft) setDraft(researchDraft(session));
    setCreate(true);
  }
  function researchSettings(tab) {
    setCreate(false); setReturnResearch(true); setSettingsTab(tab); navigate('settings');
  }
  function retryResearch(task) {
    const template = session.templates.find(t => t.tickers.includes(task.mandate.ticker) || t.allow_listed_stocks);
    if (!template) { notify('该对象已不在批准清单中，请先配置研究模板。'); return; }
    const m = task.mandate, i = task.inputs;
    const security = i.security || session.instruments?.find(stock => stock.symbol === m.ticker);
    const next = { ...researchDraft(session, template), ticker: m.ticker, selected_security: security || null,
      horizon: String(m.prediction_horizon_trading_days), benchmark: security?.benchmark || m.benchmark,
      currency: security?.quote_currency || m.quote_currency, display_currency: i.display_currency || (['USD', 'CNY'].includes(m.quote_currency) ? m.quote_currency : 'USD'),
      stock_question: i.stock_question || 'understand', asset_type: m.asset_type, purpose: m.purpose,
      analysts: i.analysts, portfolio_mode: i.portfolio ? i.portfolio.positions.length ? 'positions' : 'empty' : 'none',
      portfolio_currency: i.portfolio?.currency || m.quote_currency, cash: String(i.portfolio?.cash ?? ''),
      positions: (i.portfolio?.positions || []).map(p => ({ id: crypto.randomUUID(), ticker: p.ticker,
        quantity: String(p.quantity), average_price: String(p.average_price ?? '') })),
    };
    if (i.allocation_valuation) for (const key of ['price', 'equity', 'current_units', 'change_units', 'valuation_date']) next[key] = String(i.allocation_valuation[key]);
    setDraft(next); setCreate(true);
  }
  const taskCount = tasks?.total ?? operations?.task_total ?? null;
  const reviewCount = reports?.items.filter(r => r.status === 'draft').length ?? operations?.review_backlog ?? null;
  const published = reports?.items.filter(r => r.status === 'published').length ?? null;
  const canRead = { tasks: scopes.has('task:read'), reports: scopes.has('report:read'),
    evaluation: scopes.has('evaluation:read'), operations: scopes.has('ops:read') || scopes.has('audit:read'),
    settings: scopes.has('settings:read') || session?.demo_mode,
    watchlist: session?.investor_tools && scopes.has('task:read'), guide: Boolean(session?.investor_tools) };
  const visibleNav = nav.filter(([id]) => (id === 'home' || canRead[id])
    && (!beginner || !['evaluation', 'operations'].includes(id))).sort((a, b) => beginner
      ? ['home', 'watchlist', 'tasks', 'reports', 'guide', 'settings'].indexOf(a[0])
        - ['home', 'watchlist', 'tasks', 'reports', 'guide', 'settings'].indexOf(b[0]) : 0);
  const username = session?.account?.username || session?.subject || '';
  if (authLoading) return <div className="auth-loading" role="status">正在打开研究工作台…</div>;
  if (!session) return <><AuthPage status={authStatus} error={authError} onRetry={() => setAuthVersion(v => v + 1)}
    onLogin={identity => { setAuthStatus(current => ({ ...current, setup_required: false })); passwordLogin(identity); }}
    onAdvanced={() => setConnect(true)} onDemo={enterDemo} />
    {connect ? <ConnectDialog onClose={() => setConnect(false)} onConnect={login} /> : null}</>;
  return <div className={`app-shell ${beginner ? 'beginner' : ''}`}>
    <a className="skip-link" href="#main">跳转到内容</a>
    <aside className={`sidebar ${menu ? 'sidebar-open' : ''}`}>
      <a className="brand" href="#" onClick={e => { e.preventDefault(); navigate('home'); }}><span className="brand-mark">T</span><span>TradingAgents<small>研究工作台</small></span></a>
      <nav aria-label="主导航">{visibleNav.map(([id, title, icon]) => <button key={id} className={`nav-item ${page === id ? 'selected' : ''}`}
        onClick={() => navigate(id)} aria-current={page === id ? 'page' : undefined}><Icon name={icon} size={19} /><span>{title}</span>{page === id ? <span className="nav-dot" /> : null}</button>)}</nav>
      <div className="sidebar-bottom"><div className="workspace-icon"><Icon name="shield" size={19} /></div><div><strong>{session?.workspace || '本地工作空间'}</strong>
        <small>{username} · {roleNames[session.account?.role] || '访问凭据'}</small></div></div>
      <div className="sidebar-footnote">研究有据，决策有界。</div>
    </aside>
    {menu ? <button className="sidebar-overlay" aria-label="关闭导航" onClick={() => setMenu(false)} /> : null}
    <div className="main-shell">
      <header className="topbar"><div className="breadcrumb"><button className="icon-button mobile-menu" aria-label="打开导航" onClick={() => setMenu(!menu)}><Icon name="menu" /></button>
        <span>{session?.workspace || 'research'}</span><span className="breadcrumb-separator">/</span><strong>{nav.find(n => n[0] === page)[1]}</strong></div>
        <div className="topbar-actions">{session.investor_tools ? <button className="display-mode" onClick={changeMode}>{beginner ? '专业界面' : '入门界面'}</button> : null}
          <span className="account-button"><span className="avatar">{username.slice(0, 1).toUpperCase()}</span>
          <span>{username}</span><small>{roleNames[session.account?.role] || ''}</small></span>
          <button className="disconnect" onClick={logout}>{session.demo_mode ? '退出演示' : session.auth_method === 'password' ? '退出登录' : '断开'}</button></div>
      </header>
      <main id="main">
        {!session.stock_catalog ? <div className="notice"><strong>股票研究入口已更新</strong>
          <p>新版提供证券目录、推荐参数和有界研究路线，使用原账号继续。</p>
          <a className="text-button" href="http://127.0.0.1:8783/">打开新版工作台</a></div> : null}
        {!session.research_options ? <div className="notice"><strong>可配置研究流程已更新</strong>
          <p>使用原账号登录新版入口，继续配置模板、输入参数和创建研究。</p>
          <a className="text-button" href="http://127.0.0.1:8783/">打开新版工作台</a></div> : null}
        {session.research_options && !session.investor_tools ? <div className="notice"><strong>入门投资者界面已更新</strong>
          <p>使用原账号登录新入口，阅读简明报告并保存个人关注。</p><a className="text-button" href="http://127.0.0.1:8783/">打开入门工作台</a></div> : null}
        {session?.demo_mode ? <div className="notice" role="status"><strong>合成演示工作空间</strong>
          <p>{beginner ? '行情、事件、财务和评级均为预设内容，仅供练习。实际执行并保存记录，不调用付费模型。' : session.demo_notice}</p>
          {!beginner ? <><p>开始研究 → 查看自动生成的报告 → 复核员批准并发布 → 研究员固定预测、登记观察。</p>
          <label className="demo-role">体验身份<select aria-label="演示身份" value={session.account.role} onChange={e => switchDemo(e.target.value)}>
            <option value="researcher">研究员</option><option value="reviewer">复核员</option><option value="operator">运营员</option>
          </select></label></> : null}</div> : null}
        {page === 'home' && beginner ? <BeginnerHome session={session} data={investor} onCreate={openCreate}
          onHelp={() => navigate('guide')} onWatchlist={() => navigate('watchlist')}
          onTask={id => select('tasks', id)} onReport={id => select('reports', id)} onSettings={() => navigate('settings')} />
        : page === 'home' ? <>
          <PageHeading title={<>让每一次研究<br className="mobile-break" />都有据可循。</>} description="从研究任务开始，追踪证据、复核与结果。">
            {scopes.has('task:create') ? <Button icon="plus" onClick={openCreate}>新建研究</Button> : null}</PageHeading>
          <div className="metric-row">
            {[['研究任务', taskCount], ['待复核', reviewCount], ['已发布', published]].map(([title, value]) => <div key={title}><span>{title}</span>
              <strong>{session ? value ?? '—' : '—'}</strong><small>{!session ? '连接后查看' : '当前可见记录'}</small></div>)}
            <div className="metric-context"><Icon name="shield" size={26} /><p>明确研究边界<br /><strong>保留证据与独立复核</strong></p></div>
          </div>
          {!demoMode && authStatus?.demo_enabled ? <div className="connection-banner"><div><strong>先跑一遍完整流程</strong>
            <p>无需模型密钥，体验研究执行、报告、独立复核与结果观察。</p></div>
            <Button secondary onClick={enterDemo}>体验演示<Icon name="arrow" size={16} /></Button></div> : null}
          {!session ? <div className="connection-banner"><div><strong>连接你的研究工作空间</strong><p>使用访问凭据查看真实任务、报告与评估记录。</p></div>
            <button className="text-button" onClick={() => setConnect(true)}>开始连接<Icon name="arrow" size={18} /></button></div>
              : session.templates.some(t => !t.execution.credentials_present) ? <div className="notice">新任务的模型执行尚待配置。
              <button className="text-button settings-shortcut" onClick={() => navigate('settings')}>前往模型设置<Icon name="arrow" size={16} /></button></div> : null}
          <div className="home-layout"><section className="panel research-panel"><div className="panel-heading"><h2>最近研究</h2>
            <button className="text-button" onClick={() => navigate('tasks')}>查看全部<Icon name="arrow" size={16} /></button></div>
            {session && scopes.has('task:read') ? <TaskTable items={(tasks?.items || []).slice(0, 5)} onSelect={id => select('tasks', id)} onCreate={scopes.has('task:create') ? openCreate : null} compact />
              : <Empty title="当前账号未开放研究任务" text="请使用研究员或管理员账号查看研究任务。" />}
          </section><aside className="panel workflow"><h2>研究流程</h2><p>从问题到证据，再到结果。</p>
            <ol>{[['创建研究', '固定标的、期限和基准'], ['生成报告', '保留来源与质量检查'], ['独立复核', '核验后批准固定版本'], ['观察结果', '按一致窗口记录收益']].map(([title, text], i) =>
              <li key={title}><span className="step-number">0{i + 1}</span><div><strong>{title}</strong><p>{text}</p></div>{i < 3 ? <span className="step-line" /> : null}</li>)}</ol>
            <div className="workflow-footer"><Icon name="clock" size={17} /><span>日级研究 · 全程可追踪</span></div></aside></div>
          {session && reports?.items.some(r => r.status === 'draft') ? <section className="panel review-summary"><div><h2>待复核报告</h2><p>研究完成后，通过独立复核再发布。</p></div>
            <Button secondary onClick={() => navigate('reports')}>进入报告复核<Icon name="arrow" size={16} /></Button></section> : null}
          <div className="boundary"><Icon name="shield" size={20} /><span><strong>研究边界</strong>本系统提供研究与复核，不执行交易。</span><span className="boundary-tail">TradingAgents</span></div>
        </> : <>
          <PageHeading title={descriptions[page][0]} description={descriptions[page][1]}>
            {session ? <button className="icon-button refresh-button" aria-label="刷新记录" onClick={refresh} disabled={loading}><Icon name="refresh" /></button> : null}
            {page === 'tasks' && scopes.has('task:create') ? <Button icon="plus" onClick={openCreate}>新建研究</Button> : null}
          </PageHeading>
          {!canRead[page] ? <section className="panel"><Permission onBack={() => navigate('home')} /></section>
            : page === 'tasks' ? selected ? <TaskDetail beginner={beginner} onRetry={retryResearch} task={detail} call={call} scopes={scopes} onBack={() => navigate('tasks')} onRefresh={refresh} notify={notify}
              onSettings={() => navigate('settings')} onReport={id => select('reports', id)} /> : <TasksPage tasks={tasks} onSelect={id => select('tasks', id)} onCreate={scopes.has('task:create') ? openCreate : null} offset={offset} onOffset={setOffset} loading={loading} />
              : page === 'watchlist' ? <WatchlistPage session={session} data={investor} call={call} onRefresh={refresh} onCreate={openCreate}
                onTask={id => select('tasks', id)} onReport={id => select('reports', id)} notify={notify} />
              : page === 'guide' ? <BeginnerGuide onCreate={openCreate} canCreate={scopes.has('task:create')} />
              : page === 'reports' ? selected ? <ReportDetail key={selected} beginner={beginner} report={detail} session={session} call={call}
                onWatchlist={() => navigate('watchlist')} onBack={() => navigate('reports')} onRefresh={refresh} notify={notify} />
                : <ReportsPage reports={reports} onSelect={id => select('reports', id)} offset={offset} onOffset={setOffset} />
                : page === 'evaluation' ? selected ? <ExperimentDetail summary={detail} tasks={tasks} reports={reports} call={call} session={session}
                  onBack={() => navigate('evaluation')} onRefresh={refresh} notify={notify} /> : <ExperimentsPage experiments={experiments}
                    onSelect={id => select('evaluation', id)} offset={offset} onOffset={setOffset} onCreate={scopes.has('task:create') && scopes.has('evaluation:write') ? () => setPlan(true) : null} />
                  : page === 'settings' ? <>
                    {returnResearch ? <div className="research-context"><span>研究草稿已保留，配置完成后返回继续。</span>
                      <Button secondary onClick={() => { setReturnResearch(false); setCreate(true); }}>返回新建研究</Button></div> : null}
                    <div className="settings-tabs tabs">
                      {session.research_options ? <button className={settingsTab === 'research' ? 'active' : ''} onClick={() => setSettingsTab('research')}>研究模板</button> : null}
                      <button className={settingsTab === 'models' ? 'active' : ''} onClick={() => setSettingsTab('models')}>模型配置</button>
                      {scopes.has('accounts:manage') && session.auth_method === 'password' ? <button className={settingsTab === 'accounts' ? 'active' : ''}
                        onClick={() => setSettingsTab('accounts')}>账号管理</button> : null}
                    </div>
                    {settingsTab === 'research' ? <ResearchSettingsPage call={call} session={session} version={version} onSaved={modelsSaved} />
                      : settingsTab === 'accounts' ? <AccountsPage call={call} /> : <SettingsPage call={call} session={session} version={version} onSaved={modelsSaved} />}
                  </>
                    : <OperationsPage operations={operations} audit={audit} session={session} call={call} notify={notify} onRefresh={refresh} />}
        </>}
        <ErrorLine error={error} />
        <footer className="page-footer"><span>TradingAgents 研究工作台</span><span>证据可追踪 · 结论需复核</span></footer>
      </main>
    </div>
    {notice ? <div className="toast" role="status"><Icon name="check" size={19} />{notice}</div> : null}
    {connect ? <ConnectDialog onClose={() => setConnect(false)} onConnect={login} /> : null}
    {create && session && draft ? <ResearchDialog beginner={beginner} session={session} call={call} draft={draft} onDraft={setDraft} onSettings={researchSettings}
      onClose={() => { setCreate(false); setReturnResearch(false); }} onCreated={result => {
      setCreate(false); setDraft(null); setReturnResearch(false); select('tasks', result.id); refresh(); notify('研究已开始，完成后自动生成报告。');
    }} /> : null}
    {plan && session ? <PlanDialog session={session} call={call} onClose={() => setPlan(false)} onCreated={id => {
      setPlan(false); select('evaluation', id); refresh(); notify('评估计划已固定。');
    }} /> : null}
  </div>;
}

createRoot(document.getElementById('root')).render(<App />);
