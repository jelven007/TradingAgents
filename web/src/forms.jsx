import React, { useState } from 'react';
import { Button, ErrorLine, Field, Icon, Modal } from './components';
export { ResearchDialog } from './research-form';

export function ConnectDialog({ onClose, onConnect }) {
  const [credential, setCredential] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function connect(event) {
    event.preventDefault(); setBusy(true); setError(null);
    try { await onConnect(credential.trim()); } catch (err) { setError(err); } finally { setBusy(false); }
  }
  async function upload(event) {
    const file = event.target.files[0];
    if (file) setCredential((await file.text()).trim());
  }
  return <Modal title="连接工作空间" subtitle="使用运营者发放的访问凭据进入研究工作台。" onClose={onClose}>
    <form onSubmit={connect}>
      <div className="connect-note"><Icon name="shield" size={24} /><span>凭据只保存在当前页面内存，刷新或断开后需要重新连接。</span></div>
      <Field label="访问凭据">
        <input autoFocus type="password" value={credential} onChange={e => setCredential(e.target.value)}
          required minLength={32} maxLength={128} autoComplete="off" placeholder="粘贴访问凭据" />
      </Field>
      <label className="file-control"><Icon name="report" size={17} />从凭据文件导入
        <input type="file" accept=".token,.txt" onChange={upload} />
      </label>
      <p className="muted small">选择运营者发放的凭据文件。普通环境位于 runtime/tokens，合成演示凭据位于 runtime/demo。</p>
      <ErrorLine error={error} />
      <div className="modal-footer"><Button type="button" secondary onClick={onClose}>取消</Button>
        <Button type="submit" disabled={busy || !credential}>{busy ? '连接中…' : '连接工作空间'}</Button>
      </div>
    </form>
  </Modal>;
}

export function ConfirmDialog({ title, description, onClose, onConfirm, reasonLabel = '操作原因', confirmText = '确认', danger = false }) {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError(null);
    try { await onConfirm(new FormData(event.currentTarget).get('reason')); onClose(); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }
  return <Modal title={title} subtitle={description} onClose={onClose}>
    <form onSubmit={submit}><Field label={reasonLabel}>
      <textarea name="reason" rows={3} required maxLength={4000} autoFocus /></Field>
      <ErrorLine error={error} /><div className="modal-footer">
        <Button type="button" secondary onClick={onClose}>取消</Button>
        <Button danger={danger} disabled={busy}>{busy ? '处理中…' : confirmText}</Button>
      </div></form>
  </Modal>;
}
