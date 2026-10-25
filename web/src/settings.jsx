import React, { useEffect, useState } from 'react';
import { Button, ErrorLine, Field, Icon } from './components';

const providerNames = {
  openai: 'OpenAI', deepseek: 'DeepSeek', 'qwen-cn': '通义千问 · 中国', qwen: '通义千问 · 国际',
  'glm-cn': '智谱 GLM · 中国', glm: 'GLM · 国际', 'minimax-cn': 'MiniMax · 中国',
  minimax: 'MiniMax · 国际', kimi: 'Kimi / Moonshot', anthropic: 'Anthropic / Claude',
  google: 'Google / Gemini', openrouter: 'OpenRouter', xai: 'xAI', mistral: 'Mistral',
  groq: 'Groq', nvidia: 'NVIDIA NIM', azure: 'Azure OpenAI', ollama: 'Ollama · 本地',
  openai_compatible: 'OpenAI 兼容接口',
};
const messages = {
  connected: '连接成功，模型已响应。', missing_key: '请先填写 API Key，再测试连接。',
  authentication: '授权未通过，请核对 API Key 和该模型的访问权限。',
  rate_limit: '供应商限流或额度不足，请检查账户额度后重试。',
  model_or_request: '模型或请求未被接受，请核对模型 ID、接口地址及 Azure API 版本。',
  endpoint: '接口地址无法使用，请核对地址及网络配置。',
  timeout: '连接超时，请检查服务是否启动、网络是否可达。',
  connection: '未能连接模型服务，请检查接口地址、服务状态和网络。',
};
const clean = settings => ({
  quick: { ...settings.quick, api_key: '', clear_api_key: false },
  deep: { ...settings.deep, api_key: '', clear_api_key: false },
});

export function SettingsPage({ call, session, version, onSaved }) {
  const [saved, setSaved] = useState(null);
  const [draft, setDraft] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState('');
  const [probes, setProbes] = useState({});
  const writable = session.scopes.includes('settings:write') && !session.demo_mode;
  useEffect(() => {
    if (session.demo_mode) { setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true); setError(null);
    call('/settings/models', { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) { setSaved(data); setDraft(clean(data)); setProbes({}); }
    }).catch(err => { if (err.name !== 'AbortError') setError(err); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [call, version, session.demo_mode]);

  function edit(tier, changes) {
    setDraft(current => ({ ...current, [tier]: { ...current[tier], ...changes } }));
    setProbes(current => ({ ...current, [tier]: null })); setNotice(''); setError(null);
  }
  function changeProvider(tier, provider) {
    const endpoint = saved.providers.find(item => item.id === provider)?.default_url || '';
    edit(tier, { provider, base_url: endpoint, model: '', api_key: '', clear_api_key: false,
      api_version: provider === 'azure' ? '2025-03-01-preview' : '' });
  }
  function payload() {
    const data = { expected_version: saved.version };
    for (const tier of ['quick', 'deep']) {
      const value = draft[tier];
      data[tier] = {
        provider: value.provider, model: value.model.trim(), base_url: value.base_url.trim(),
        api_version: value.api_version.trim(), api_key: value.api_key || null,
        clear_api_key: value.clear_api_key,
      };
    }
    return data;
  }
  async function save(event) {
    event.preventDefault(); setBusy('save'); setError(null); setNotice('');
    try {
      await call('/settings/models', { method: 'POST', body: payload() });
      setDraft(current => ({
        quick: { ...current.quick, api_key: '' }, deep: { ...current.deep, api_key: '' },
      }));
      const data = await call('/settings/models');
      setSaved(data); setDraft(clean(data)); setProbes({});
      setNotice(`已保存配置 v${data.version}，新建研究任务将使用此配置。`);
      await onSaved();
    } catch (err) { setError(err); }
    finally { setBusy(''); }
  }
  async function probe(tier) {
    setBusy(tier); setError(null);
    try {
      const result = await call('/settings/models/test', { method: 'POST', body: {
        expected_version: saved.version, tier, settings: payload()[tier],
      } });
      setProbes(current => ({ ...current, [tier]: result }));
    } catch (err) { setError(err); }
    finally { setBusy(''); }
  }
  const changed = draft && saved && JSON.stringify(draft) !== JSON.stringify(clean(saved));
  if (session.demo_mode) return <section className="panel model-card-fields"><h2>演示模型</h2>
    <p className="small muted">演示空间使用固定的合成模型，供你体验研究与复核流程。</p>
    <div className="notice">退出演示后登录你的工作空间，在“设置 → 模型配置”中保存模型与密钥。</div></section>;
  if (loading) return <section className="panel loading" role="status">正在读取模型配置…</section>;
  if (!draft) return <ErrorLine error={error} />;
  return <div className="settings-page">
    <div className="settings-intro"><span className="settings-symbol"><Icon name="settings" size={24} /></span>
      <div><strong>配置研究使用的模型</strong><p>快速模型处理分析与日常推理，深度模型负责综合研判。两者可以使用不同的供应商。</p></div>
      <span className="settings-version">{saved.version ? `已保存 · v${saved.version}` : '尚未保存'}</span>
    </div>
    {!writable ? <div className="notice">当前身份可查看配置。保存和测试连接需要具有模型设置权限的管理员凭据。</div> : null}
    <form onSubmit={save} autoComplete="off">
      <fieldset disabled={!writable || Boolean(busy)} className="settings-fieldset">
        <div className="model-settings-grid">
          {['quick', 'deep'].map((tier, index) => {
            const value = draft[tier];
            const retained = saved[tier].api_key_configured && saved[tier].provider === value.provider
              && saved[tier].base_url.replace(/\/$/, '') === value.base_url.trim().replace(/\/$/, '');
            const local = value.provider === 'ollama';
            const result = probes[tier];
            return <section className="panel model-settings-card" key={tier} aria-label={tier === 'quick' ? '快速模型配置' : '深度模型配置'}>
              <div className="model-card-heading"><span className="model-number">0{index + 1}</span><div>
                <h2>{tier === 'quick' ? '快速模型' : '深度模型'}</h2>
                <p>{tier === 'quick' ? '分析、信息整理与日常推理' : '综合研判、辩论与研究结论'}</p></div></div>
              <div className="model-card-fields">
                <Field label="供应商" source="预置选项 → 配置"><select aria-label={`${tier === 'quick' ? '快速' : '深度'}模型供应商`} value={value.provider}
                  onChange={event => changeProvider(tier, event.target.value)}>
                  {saved.providers.map(provider => <option key={provider.id} value={provider.id}>{providerNames[provider.id] || provider.id}</option>)}
                </select></Field>
                <Field label={value.provider === 'azure' ? '部署名称' : '模型 ID'} source="输入 → 配置" hint="填写供应商控制台中可访问的准确名称。">
                  <input name={`${tier}-model`} required maxLength={200} value={value.model} placeholder="输入模型 ID"
                    onChange={event => edit(tier, { model: event.target.value })} /></Field>
                <Field label="接口地址 / Base URL" source={value.provider === 'google' ? '供应商预置' : '预置 → 配置'} hint={['ollama', 'openai_compatible'].includes(value.provider)
                  ? '支持 HTTPS 接口，或带端口的本机 HTTP 服务，例如 http://127.0.0.1:11434/v1。'
                  : value.provider === 'google' ? '当前Gemini适配器使用供应商固定接口；选择其他供应商可配置地址。'
                    : '已提供供应商默认地址；自定义接口需使用 HTTPS。'}>
                  {value.provider === 'google' ? <output className="template-identity">{value.base_url}</output>
                    : <input type="url" name={`${tier}-endpoint`} required maxLength={1000} value={value.base_url}
                      placeholder="https://api.example.com/v1"
                      onChange={event => edit(tier, { base_url: event.target.value })} />}</Field>
                {value.provider === 'azure' ? <Field label="Azure API 版本" source="预置 → 配置"><input required value={value.api_version} maxLength={80}
                  onChange={event => edit(tier, { api_version: event.target.value })} /></Field> : null}
                <Field label={<span className="key-field-label">API Key <span className={`key-state ${retained && !value.clear_api_key ? 'configured' : ''}`}>
                  {value.clear_api_key ? '将清除' : retained ? '已配置' : local ? '本地可不填' : '未配置'}</span></span>}
                  source="输入 → 配置" hint={retained ? '留空保留已保存的密钥；输入新值后替换。更换供应商或接口需重新填写。'
                    : '密钥在本机加密保存，保存后不回显。'}>
                  <input type="password" name={`${tier}-api-key`} autoComplete="new-password" maxLength={4096}
                    value={value.api_key} disabled={value.clear_api_key} placeholder={retained ? '留空保留已保存的密钥' : '填写 API Key'}
                    onChange={event => edit(tier, { api_key: event.target.value })} /></Field>
                {retained ? <label className="clear-key-control"><input type="checkbox" checked={value.clear_api_key}
                  onChange={event => edit(tier, { clear_api_key: event.target.checked, api_key: '' })} /><span>清除已保存的 API Key</span></label> : null}
                <div className="model-test-row"><Button type="button" secondary icon="link" onClick={() => probe(tier)}>
                  {busy === tier ? '正在测试…' : '测试连接'}</Button><small>一次短请求 · 可能产生少量费用</small></div>
                {result ? <div className={`model-probe-result ${result.ok ? 'probe-ok' : 'probe-failed'}`} role={result.ok ? 'status' : 'alert'}>
                  <strong>{messages[result.category] || messages.connection}</strong>
                  <small>耗时 {(result.elapsed_ms / 1000).toFixed(1)} 秒{result.usage?.total_tokens != null ? ` · ${result.usage.total_tokens} tokens` : ''} · {changed ? '测试的是当前输入，保存后用于新任务' : '测试不会运行研究任务'}</small>
                </div> : null}
              </div>
            </section>;
          })}
        </div>
        <div className="settings-save-bar"><div><strong>{changed ? '有未保存的修改' : saved.version ? '配置已同步' : '当前为模板默认配置'}</strong>
          <p>保存后立即用于新建任务；已有任务保留创建时的模型配置。</p></div>
          <div><Button type="button" secondary disabled={!changed} onClick={() => {
            setDraft(clean(saved)); setProbes({}); setError(null); setNotice('');
          }}>还原修改</Button><Button type="submit" icon="check" disabled={!changed}>{busy === 'save' ? '正在保存…' : '保存配置'}</Button></div></div>
      </fieldset>
      {notice ? <div className="settings-saved" role="status"><Icon name="check" size={18} />{notice}</div> : null}
      <ErrorLine error={error} />
    </form>
  </div>;
}
