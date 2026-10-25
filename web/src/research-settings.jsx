import React, { useEffect, useState } from 'react';
import { Button, ErrorLine, Field } from './components';
import { analystNames, assetNames, purposeNames } from './research-form';

const clean = entry => {
  const { version, source, ...profile } = entry;
  return structuredClone(profile);
};
export function ResearchSettingsPage({ call, session, version, onSaved }) {
  const [saved, setSaved] = useState(null);
  const [draft, setDraft] = useState(null);
  const [tickersText, setTickersText] = useState('');
  const [selected, setSelected] = useState('');
  const [base, setBase] = useState('');
  const [expected, setExpected] = useState(0);
  const [isNew, setIsNew] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [errors, setErrors] = useState({});
  const [notice, setNotice] = useState('');
  const writable = session.scopes.includes('settings:write');
  function choose(entry) {
    setSelected(entry.name); setBase(entry.name); setDraft(clean(entry)); setExpected(entry.version);
    setTickersText(entry.tickers.join(', '));
    setIsNew(false); setErrors({}); setError(null); setNotice('');
  }
  useEffect(() => {
    const controller = new AbortController();
    call('/settings/research', { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) { setSaved(data); if (data.templates[0]) choose(data.templates[0]); }
    }).catch(err => { if (err.name !== 'AbortError') setError(err); });
    return () => controller.abort();
  }, [call, version]);
  function edit(changes) { setDraft(current => ({ ...current, ...changes })); setErrors({}); setError(null); setNotice(''); }
  const defaults = changes => edit({ defaults: { ...draft.defaults, ...changes } });
  function toggle(key, value, checked) {
    edit({ [key]: checked ? [...draft[key], value] : draft[key].filter(item => item !== value) });
  }
  function create(duplicate) {
    const source = saved.templates.find(item => item.name === selected) || saved.templates[0];
    const value = clean(source);
    setBase(source.name); setExpected(0); setIsNew(true);
    setDraft({ ...value, name: '', title: duplicate ? `${source.title}副本` : '新研究模板',
      description: duplicate ? source.description : '' });
    setTickersText(value.tickers.join(', '));
    setErrors({}); setError(null); setNotice('');
  }
  async function save(event) {
    event.preventDefault(); setBusy(true); setError(null); setErrors({}); setNotice('');
    try {
      const result = await call('/settings/research', { method: 'POST', body: {
        expected_version: expected, profile: draft, base_template: base,
      } });
      const data = await call('/settings/research');
      setSaved(data); choose(data.templates.find(item => item.name === result.name));
      setNotice(`已保存研究模板 ${result.name} · v${result.version}，新任务使用此版本。`);
      await onSaved();
    } catch (err) {
      setError(err);
      setErrors(Object.fromEntries((err.fields || []).map(item => [item.field.replace(/^profile\./, ''), item.message])));
      requestAnimationFrame(() => document.querySelector('.research-settings [aria-invalid="true"]')?.focus());
    } finally { setBusy(false); }
  }
  if (!saved) return <section className="panel model-card-fields">{error ? <ErrorLine error={error} /> : <p role="status">正在读取研究模板…</p>}</section>;
  if (!draft) return <div className="notice">没有运营预置模板，请先由运营者配置基础研究模板。</div>;
  const input = (key, label, nested = '', type = 'text', min, max) => {
    const value = nested ? draft[nested][key] : draft[key];
    const path = nested ? `${nested}.${key}` : key;
    return <Field key={path} label={label} source="配置" error={errors[path]}>
      <input name={path} value={value} type={type} min={min} max={max} step={type === 'number' ? 1 : undefined}
        required onChange={e => {
          const next = type === 'number' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value;
          if (nested === 'defaults') defaults({ [key]: next });
          else if (nested) edit({ [nested]: { ...draft[nested], [key]: next } });
          else edit({ [key]: next });
        }} /></Field>;
  };
  return <div className="research-settings">
    <div className="research-context"><div><strong>研究模板</strong><p>预置模板来自运营配置；保存后按工作空间版本持久化。</p></div>
      <div className="inline-actions"><Button secondary disabled={!writable || busy} onClick={() => create(false)}>新增模板</Button>
        <Button secondary disabled={!writable || busy} onClick={() => create(true)}>复制模板</Button></div></div>
    <Field label="选择配置模板" source="预置 / 配置"><select value={isNew ? '' : selected} disabled={busy}
      onChange={e => choose(saved.templates.find(item => item.name === e.target.value))}>
      {isNew ? <option value="">正在创建新模板</option> : null}
      {saved.templates.map(entry => <option key={entry.name} value={entry.name}>{entry.title} · {entry.name} · v{entry.version}</option>)}</select></Field>
    {!writable ? <div className="notice">当前账号可查看模板。管理员可修改模板；演示研究员可修改自己的演示空间。</div> : null}
    <form onSubmit={save} noValidate>
      <fieldset className="settings-fieldset" disabled={!writable || busy}>
        <section className="panel model-card-fields">
          <h2>{isNew ? '创建研究模板' : `编辑模板 · v${expected}`}</h2>
          {isNew ? <Field label="基础模板" source="配置" hint="继承基础模板的来源许可与研究规则；可配置下方公开参数。">
            <select value={base} onChange={e => setBase(e.target.value)}>{saved.templates.map(entry => <option key={entry.name} value={entry.name}>{entry.title}</option>)}</select></Field> : null}
          <div className="form-grid">
            <Field label="模板标识" source="输入 → 配置" error={errors.name} hint={isNew ? '英文、数字、短横线或下划线，最多96字符。' : '标识固定；复制模板可以使用新标识。'}>
              {isNew ? <input name="name" value={draft.name} maxLength={96} onChange={e => edit({ name: e.target.value })} required />
                : <output className="template-identity">{draft.name}</output>}</Field>
            {input('title', '模板名称')}
          </div>
          <Field label="模板说明" source="配置" error={errors.description}>
            <textarea name="description" rows={2} maxLength={2000} value={draft.description} onChange={e => edit({ description: e.target.value })} /></Field>
          <Field label="批准标的清单" source="配置" hint="用逗号、空格或换行分隔；保存后标准化为大写。" error={errors.tickers}>
            <textarea name="tickers" rows={3} value={tickersText}
              onChange={e => { setTickersText(e.target.value); edit({ tickers: e.target.value.split(/[,\s，]+/).filter(Boolean) }); }} /></Field>
          {[['asset_types', '允许资产类型', assetNames], ['purposes', '允许研究用途', purposeNames], ['analysts', '允许分析团队', analystNames]].map(([key, title, names]) =>
            <fieldset className="research-section" key={key}><legend>{title} <span className="field-source">预置选项 → 配置</span></legend>
              <div className="check-options">{saved.options[key === 'asset_types' ? 'asset_types' : key].map(value => <label key={value}>
                <input type="checkbox" checked={draft[key].includes(value)} onChange={e => toggle(key, value, e.target.checked)}
                  aria-invalid={Boolean(errors[key])} />{names[value]}</label>)}</div>
              {errors[key] ? <p className="field-error" role="alert">{errors[key]}</p> : null}</fieldset>)}
          <h3>新建研究默认值</h3><div className="form-grid">
            {input('ticker', '默认标的', 'defaults')}
            <Field label="默认资产类型" source="配置" error={errors['defaults.asset_type']}><select value={draft.defaults.asset_type}
              onChange={e => defaults({ asset_type: e.target.value })}>{Object.entries(assetNames).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></Field>
            <Field label="默认研究用途" source="配置" error={errors['defaults.purpose']}><select value={draft.defaults.purpose}
              onChange={e => defaults({ purpose: e.target.value })}>{Object.entries(purposeNames).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></Field>
            {input('quote_currency', '默认币种', 'defaults')}
            {input('benchmark', '默认基准', 'defaults')}
            {input('prediction_horizon_trading_days', '默认预测期限', 'defaults', 'number', 1, 2520)}
            {input('valid_days', '默认有效天数', 'defaults', 'number', 0, 3650)}
          </div><h3>执行与准入上限</h3><div className="form-grid">
            {input('max_calls', '模板调用上限', 'limits', 'number', 1, 1000)}
            {input('max_seconds', '模板时长上限（秒）', 'limits', 'number', 1, 86400)}
            {input('max_output_tokens', '模板输出上限（tokens）', 'limits', 'number', 1, 65536)}
            {input('max_attempts', '最大尝试次数', 'limits', 'number', 1, 10)}
            {input('budget_microusd', '单任务预算（微美元）', 'limits', 'number', 1)}
            {input('reserve_per_call_microusd', '单次调用预留（微美元）', 'limits', 'number', 1)}
            {input('max_pending', '最大待执行任务数', '', 'number', 1, 1000)}
            {input('workspace_budget_microusd', '累计准入预算（微美元）', '', 'number', 1)}
          </div><p className="small muted">1,000,000 微美元 = 1 USD。预算为准入预留，不代表供应商实际收费。</p>
          <div className="settings-save-bar"><p>已有任务与评估计划保留原冻结版本。</p><div>
            <Button secondary type="button" onClick={() => choose(saved.templates.find(item => item.name === selected) || saved.templates[0])}>还原修改</Button>
            <Button type="submit" icon="check">{busy ? '正在保存…' : '保存研究模板'}</Button></div></div>
        </section>
      </fieldset>
      {notice ? <div className="settings-saved" role="status">{notice}</div> : null}<ErrorLine error={error} />
    </form>
  </div>;
}
