import React, { useState } from 'react';
import { request } from './api';
import { Button, ErrorLine, Field, Icon } from './components';

export const roleNames = { admin: '管理员', researcher: '研究员', reviewer: '复核员', operator: '运营员' };

export function AuthPage({ status, onLogin, onAdvanced, onDemo, error: startupError, onRetry }) {
  const setup = status?.setup_required;
  const olderLocalService = ['8765', '8769', '8772', '8780', '8781', '8782'].includes(location.port);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function submit(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (setup && form.get('password') !== form.get('confirmation')) {
      setError(new Error('两次输入的密码不一致。')); return;
    }
    setBusy(true); setError(null);
    try {
      const identity = await request('', setup ? '/auth/setup' : '/auth/login', {
        method: 'POST', body: { username: form.get('username'), password: form.get('password') },
      });
      onLogin(identity);
    } catch (err) {
      setError(new Error(err.status === 401 ? '账号或密码不正确，请重新输入。'
        : err.status === 400 ? '账号创建未成功。账号请使用英文、数字或短横线，密码至少8位；若已创建，请刷新后登录。'
          : err.status === 429 ? '登录尝试过多，请稍后重试。' : err.message));
    } finally { setBusy(false); }
  }
  return <div className="auth-shell">
    <div className="auth-brand"><span className="brand-mark">T</span>TradingAgents<span>研究工作台</span></div>
    <main className="auth-main">
      <section className="auth-story"><span className="auth-eyebrow">从你关心的股票开始</span>
        <h1>买入、持有还是卖出，<br />先看清依据。</h1><p>选择股票和问题，系统整理行情与公司资料，给出买卖研究观点、反方理由和风险条件。</p>
        <div className="auth-features">{[['task', '选择股票'], ['report', '查看判断'], ['shield', '跟踪风险']].map(([icon, text]) =>
          <span key={text}><Icon name={icon} size={20} />{text}</span>)}</div>
      </section>
      <section className="auth-card">
        <div className="auth-card-heading"><span className="auth-local">本机工作空间</span>
          <h2>{olderLocalService ? '进入新版研究工作台' : setup ? '欢迎，先创建你的账号' : '登录研究工作台'}</h2>
          <p>{olderLocalService ? '新版支持直接开始研究、阶段进度、自动报告和完整流程演示。'
            : setup ? '只需设置一次账号和密码，即可使用全部页面和模型设置。'
            : status?.accounts_enabled ? '使用你的账号登录，继续上一次研究。'
              : olderLocalService ? '新版工作台已支持账号登录，点击下方进入。' : '此服务使用访问凭据，请从高级入口连接。'}</p></div>
        {olderLocalService ? <a className="button auth-submit" href="http://127.0.0.1:8783/">打开新版工作台</a> : null}
        {status?.demo_enabled && !olderLocalService ? <div className="auth-demo"><Button onClick={onDemo}>体验演示<Icon name="arrow" size={16} /></Button>
          <p>第一次使用，先体验合成示例。无需账号或配置，示例数据不代表真实公司。</p></div> : null}
        {status?.accounts_enabled && !olderLocalService ? <form onSubmit={submit}>
          <Field label="账号"><input name="username" defaultValue={setup ? 'admin' : ''} required maxLength={64}
            autoComplete="username" autoFocus placeholder="输入账号" pattern="[A-Za-z0-9_.-]+" /></Field>
          <Field label="密码" hint={setup ? '至少8位；这是工作台登录密码。' : null}>
            <input name="password" type="password" required minLength={setup ? 8 : 1} maxLength={256}
              autoComplete={setup ? 'new-password' : 'current-password'} placeholder={setup ? '设置登录密码' : '输入密码'} /></Field>
          {setup ? <Field label="确认密码"><input name="confirmation" type="password" required minLength={8}
            autoComplete="new-password" placeholder="再输入一次密码" /></Field> : null}
          <ErrorLine error={error} />
          <Button type="submit" disabled={busy} className="auth-submit">{busy ? '正在进入…' : setup ? '创建账号并进入' : '登录'}</Button>
          <p className="auth-session-note">登录后会保留本机登录状态；退出登录可结束会话。</p>
        </form> : null}
        <ErrorLine error={startupError} />
        {startupError ? <Button secondary onClick={onRetry}>重新连接服务</Button> : null}
        <details className="auth-advanced"><summary>高级连接</summary><p>已有访问凭据或需要连接旧版演示服务时使用。</p>
          <button className="text-button" onClick={onAdvanced}>使用访问凭据连接<Icon name="arrow" size={16} /></button></details>
      </section>
    </main>
    <footer className="auth-footer">TradingAgents · 研究与复核工作台</footer>
  </div>;
}

export function AccountsPage({ call }) {
  const [accounts, setAccounts] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  React.useEffect(() => {
    const controller = new AbortController();
    call('/accounts', { signal: controller.signal }).then(setAccounts).catch(err => {
      if (err.name !== 'AbortError') setError(err);
    });
    return () => controller.abort();
  }, [call]);
  async function create(event) {
    event.preventDefault(); setBusy(true); setError(null); setNotice('');
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      await call('/accounts', { method: 'POST', body: {
        username: data.get('username'), password: data.get('password'), role: data.get('role'),
      } });
      form.reset(); setNotice('账号已创建，可使用账号和密码登录。');
      setAccounts(await call('/accounts'));
    } catch (err) { setError(err.status === 400 ? new Error('账号已存在或输入不符合要求，请核对账号和密码。') : err); }
    finally { setBusy(false); }
  }
  return <div className="accounts-layout"><section className="panel"><div className="panel-heading"><h2>工作空间账号</h2></div>
    {accounts ? <div className="table-scroll"><table><thead><tr><th>账号</th><th>角色</th></tr></thead>
      <tbody>{accounts.map(account => <tr key={account.id}><td>{account.username}</td><td>{roleNames[account.role]}</td></tr>)}</tbody></table></div>
      : <div className="loading">正在读取账号…</div>}</section>
    <section className="panel account-create"><h2>添加账号</h2><p>为协作者创建账号；复核员使用自己的账号核验报告。</p>
      <form onSubmit={create}><Field label="账号"><input name="username" required pattern="[A-Za-z0-9_.-]+" maxLength={64} autoComplete="off" /></Field>
        <Field label="登录密码" hint="至少8位，请将账号和密码交给对应使用者。"><input name="password" type="password"
          required minLength={8} maxLength={256} autoComplete="new-password" /></Field>
        <Field label="角色"><select name="role" defaultValue="reviewer">{Object.entries(roleNames).map(([key, value]) =>
          <option key={key} value={key}>{value}</option>)}</select></Field>
        <Button disabled={busy} type="submit">{busy ? '正在创建…' : '创建账号'}</Button>
        {notice ? <div className="settings-saved" role="status">{notice}</div> : null}<ErrorLine error={error} /></form></section></div>;
}
