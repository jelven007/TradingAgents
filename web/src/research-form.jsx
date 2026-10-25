import React, { useRef, useState } from 'react';
import { today, usd } from './api';
import { Button, ErrorLine, Field, Modal } from './components';
import { StockPicker, benchmarkNames, currencyNames } from './stock-picker';

export const analystNames = { market: '行情分析', social: '情绪分析', news: '新闻分析', fundamentals: '基本面分析' };
export const assetNames = { stock: '股票', crypto: '加密资产' };
export const purposeNames = { general_research: '一般研究', event_research: '事件研究', portfolio_review: '持仓复核' };
const addDays = (date, days) => new Date(Date.parse(`${date}T00:00:00Z`) + days * 86400000).toISOString().slice(0, 10);
export function researchDraft(session, template = session.templates[0]) {
  const date = session.demo_analysis_date || session.research_today || today();
  const defaults = template?.defaults || {};
  const security = defaults.asset_type === 'crypto' || defaults.purpose === 'portfolio_review'
    ? null : session.instruments?.find(i => i.symbol === defaults.ticker);
  const executionMode = defaults.asset_type === 'crypto' || defaults.purpose === 'portfolio_review' ? 'full' : 'guided_stock';
  return {
    template: template?.name || '', ticker: defaults.ticker || '', date,
    horizon: String(defaults.prediction_horizon_trading_days || 5),
    benchmark: security?.benchmark || defaults.benchmark || 'SPY',
    currency: security?.quote_currency || defaults.quote_currency || 'USD',
    selected_security: security || null, display_currency: 'USD', stock_question: 'understand',
    execution_mode: executionMode,
    asset_type: defaults.asset_type || 'stock', purpose: defaults.purpose || 'general_research',
    valid_until: addDays(date, defaults.valid_days ?? 30),
    experiment: `research-${date.replaceAll('-', '')}-${crypto.randomUUID().slice(0, 8)}`,
    analysts: template?.analysts || [], max_calls: String(executionMode === 'guided_stock'
      ? Math.min(8, template?.limits.max_calls || 8) : template?.limits.max_calls || ''),
    max_seconds: String(template?.limits.max_seconds || ''),
    max_output_tokens: String(template?.limits.max_output_tokens || ''),
    budget: String((template?.limits.budget_microusd || 0) / 1000000),
    portfolio_mode: 'none', portfolio_currency: defaults.quote_currency || 'USD',
    cash: '', positions: [], portfolio_json: '',
    price: '', equity: '', current_units: '0', change_units: '0', valuation_date: date,
  };
}

export function ResearchDialog({ session, call, onClose, onCreated, draft, onDraft, onSettings, beginner = false }) {
  const [error, setError] = useState(null);
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [advanced, setAdvanced] = useState(!beginner || draft.purpose === 'portfolio_review');
  const idem = useRef({ key: crypto.randomUUID(), body: '' });
  const form = useRef(null);
  const template = session.templates.find(t => t.name === draft.template);
  const configured = `${template?.source || '预置'} → 输入`;
  const guided = draft.execution_mode === 'guided_stock';
  const update = changes => { onDraft({ ...draft, ...changes }); setErrors({}); setError(null); };
  const edit = key => event => update({ [key]: event.target.value });
  const field = key => errors[key];
  const selectStock = stock => update({ ticker: stock.symbol, selected_security: stock,
    currency: stock.quote_currency || draft.currency, benchmark: stock.benchmark || draft.benchmark,
    asset_type: 'stock', portfolio_currency: stock.quote_currency || draft.portfolio_currency });
  function invalid(found) {
    if (Object.keys(found).some(key => !['ticker', 'purpose', 'horizon'].includes(key))) setAdvanced(true);
    setErrors(found); setError(new Error('请修正标出的字段后重新提交。'));
    requestAnimationFrame(() => form.current?.querySelector('[aria-invalid="true"]')?.focus());
  }
  function selectTemplate(name) {
    const next = session.templates.find(t => t.name === name);
    update({ ...researchDraft(session, next), experiment: draft.experiment });
  }
  function position(index, changes) {
    update({ positions: draft.positions.map((row, i) => i === index ? { ...row, ...changes } : row) });
  }
  function importPortfolio() {
    try {
      const raw = JSON.parse(draft.portfolio_json);
      if (!raw || Array.isArray(raw) || typeof raw !== 'object' || !Array.isArray(raw.positions)
          || Object.keys(raw).some(key => !['currency', 'cash', 'positions'].includes(key))
          || raw.positions.some(row => !row || Object.keys(row).some(key => !['ticker', 'quantity', 'average_price'].includes(key)))) {
        throw new Error();
      }
      update({ portfolio_mode: raw.positions.length ? 'positions' : 'empty',
        portfolio_currency: raw.currency || draft.currency, cash: raw.cash == null ? '' : String(raw.cash),
        positions: raw.positions.map(row => ({ id: crypto.randomUUID(), ticker: String(row.ticker || ''),
          quantity: row.quantity == null ? '' : String(row.quantity),
          average_price: row.average_price == null ? '' : String(row.average_price) })) });
    } catch { invalid({ portfolio_json: '请输入含 positions 数组的持仓 JSON；仅支持币种、现金、标的、数量和成本。' }); }
  }
  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    const found = {};
    if (!template) found.template = '请选择已有模板。';
    const symbol = draft.ticker.trim().toUpperCase();
    if (!template?.tickers.includes(symbol) && !(template?.allow_listed_stocks && draft.selected_security?.symbol === symbol)) {
      found.ticker = '请搜索股票，并点击匹配的公司完成选择。';
    }
    if (!draft.date || draft.date > session.research_today) found.date = '请选择不晚于今天的研究日期。';
    if (!draft.valid_until || draft.valid_until < draft.date) found.valid_until = '有效日期不能早于研究日期。';
    if (!guided && !draft.analysts.length) found.analysts = '至少选择一个分析师。';
    if (!/^[A-Z]{3}$/.test(draft.currency.trim().toUpperCase())) found.currency = '请输入三位币种代码，如 USD。';
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$/.test(draft.experiment)) found.experiment = '使用英文、数字、短横线或下划线，最多96个字符。';
    const numeric = (key, min, max, integer = true) => {
      const value = Number(draft[key]);
      if (!draft[key].trim() || !Number.isFinite(value) || value < min || value > max || integer && !Number.isInteger(value)) {
        found[key] = `请输入${integer ? '整数' : '数值'}，范围 ${min}–${max}。`;
      }
      return value;
    };
    const options = {
      execution_mode: draft.execution_mode, display_currency: draft.display_currency, stock_question: draft.stock_question,
      selected_analysts: guided ? template.analysts : draft.analysts,
      max_calls: numeric('max_calls', 1, template?.limits.max_calls),
      max_seconds: numeric('max_seconds', 1, template?.limits.max_seconds),
      max_output_tokens: numeric('max_output_tokens', 1, template?.limits.max_output_tokens),
      budget_microusd: Math.round(numeric('budget', (template?.limits.reserve_per_call_microusd || 1) / 1000000,
        (template?.limits.budget_microusd || 1) / 1000000, false) * 1000000),
    };
    const horizon = numeric('horizon', 1, 2520);
    let portfolio = null;
    if (draft.portfolio_mode === 'json') found.portfolio_json = '请先点击“导入到持仓表”，检查后提交。';
    if (['positions', 'empty'].includes(draft.portfolio_mode)) {
      const seen = new Set();
      const positions = draft.portfolio_mode === 'positions' ? draft.positions.map((row, index) => {
        const ticker = row.ticker.trim().toUpperCase();
        if (!/^[A-Z0-9^][A-Z0-9._^=+-]{0,31}$/.test(ticker) || seen.has(ticker)) found[`positions.${index}.ticker`] = '填写有效标的；重复标的请合并。';
        seen.add(ticker);
        if (!row.quantity.trim() || !Number.isFinite(Number(row.quantity))) found[`positions.${index}.quantity`] = '填写有限数量，已有空头可为负数。';
        if (row.average_price && (!Number.isFinite(Number(row.average_price)) || Number(row.average_price) < 0)) found[`positions.${index}.average_price`] = '成本须为非负有限数值。';
        return { ticker, quantity: Number(row.quantity), average_price: row.average_price === '' ? null : Number(row.average_price) };
      }) : [];
      if (draft.portfolio_mode === 'positions' && !positions.length) found.portfolio_mode = '请添加持仓，或选择“明确空仓”。';
      if (draft.portfolio_currency.trim().toUpperCase() !== draft.currency.trim().toUpperCase()) found.portfolio_currency = '持仓币种须与研究报价币种一致。';
      if (draft.cash && !Number.isFinite(Number(draft.cash))) found.cash = '现金须为有限数值。';
      portfolio = { currency: draft.portfolio_currency.trim().toUpperCase(), cash: draft.cash === '' ? null : Number(draft.cash), positions };
    }
    let valuation = null;
    if (draft.purpose === 'portfolio_review') {
      if (!portfolio) found.portfolio_mode = '持仓复核需要选择明确空仓或填写持仓。';
      for (const key of ['price', 'equity']) numeric(key, 0.000001, 1e18, false);
      for (const key of ['current_units', 'change_units']) numeric(key, -1e15, 1e15, false);
      const held = portfolio?.positions.find(row => row.ticker === symbol)?.quantity || 0;
      if (Number(draft.current_units) !== held) found.current_units = `当前持仓表数量为 ${held}，请核对。`;
      if (draft.valuation_date !== draft.date) found.valuation_date = '估值日期须与研究日期一致。';
      valuation = { ticker: symbol, currency: draft.currency.trim().toUpperCase(), valuation_date: draft.valuation_date,
        price: draft.price, equity: draft.equity, current_units: draft.current_units, change_units: draft.change_units };
    }
    if (Object.keys(found).length) { invalid(found); return; }
    setBusy(true); setError(null); setErrors({});
    const payload = { workspace: session.workspace, experiment: draft.experiment, template: draft.template,
      mandate: { ticker: symbol, analysis_date: draft.date, asset_type: draft.asset_type, purpose: draft.purpose,
        prediction_horizon_trading_days: horizon, benchmark: draft.benchmark.trim().toUpperCase(),
        quote_currency: draft.currency.trim().toUpperCase(), valid_until: draft.valid_until },
      portfolio, allocation_valuation: valuation, options };
    const body = JSON.stringify(payload);
    if (idem.current.body && idem.current.body !== body) idem.current.key = crypto.randomUUID();
    idem.current.body = body;
    try { onCreated(await call('/research', { method: 'POST', body: payload, key: idem.current.key })); }
    catch (err) {
      const aliases = { 'mandate.ticker': 'ticker', 'mandate.analysis_date': 'date', 'mandate.valid_until': 'valid_until',
        'mandate.benchmark': 'benchmark', 'mandate.quote_currency': 'currency', 'mandate.asset_type': 'asset_type',
        'mandate.purpose': 'purpose', 'mandate.prediction_horizon_trading_days': 'horizon',
        'options.selected_analysts': 'analysts', 'options.budget_microusd': 'budget', 'portfolio.currency': 'portfolio_currency',
        portfolio: 'portfolio_mode', allocation_valuation: 'equity' };
      const mapped = Object.fromEntries((err.fields || []).map(item => [
        aliases[item.field] || item.field.replace(/^options\.|^allocation_valuation\.|^portfolio\./g, ''), item.message,
      ]));
      if (Object.keys(mapped).length) invalid(mapped);
      setError(err);
    } finally { setBusy(false); }
  }
  return <Modal title="新建研究" subtitle="选择股票和问题，系统整理资料、比较多空观点并给出研究结论。" onClose={onClose} wide>
    <form onSubmit={submit} ref={form} noValidate>
      <fieldset disabled={busy} className="settings-fieldset">
        <div className="research-mode tabs" aria-label="研究输入方式">
          <button type="button" className={!advanced ? 'active' : ''} onClick={() => setAdvanced(false)}>快速研究</button>
          <button type="button" className={advanced ? 'active' : ''} onClick={() => setAdvanced(true)}>完整参数</button>
        </div>
        {!advanced ? <div className="quick-research">
          <StockPicker session={session} call={call} template={template} value={draft.ticker}
            onInput={value => update({ ticker: value })} onSelect={selectStock} error={field('ticker')} />
          <Field label="想了解的问题" source="系统预置 → 选择" error={field('stock_question')}>
            <select value={draft.stock_question} onChange={edit('stock_question')}>
              <option value="understand">了解这家公司：机会与风险</option><option value="buy">寻找买入机会</option>
              <option value="hold">核对继续持有的理由</option><option value="sell">识别卖出风险</option></select></Field>
          <Field label="关注期限（交易日）" source={configured} hint="5/20/60个交易日约一周/一月/三月；只是近似，不是持有建议。" error={field('horizon')}>
            <input type="number" min={1} max={2520} value={draft.horizon} onChange={edit('horizon')} /></Field>
          <div className="horizon-options">{[5, 20, 60].map(n => <button type="button" key={n} aria-pressed={draft.horizon === String(n)}
            onClick={() => update({ horizon: String(n) })}>{n}个交易日</button>)}
            <button type="button" onClick={() => update({ horizon: String(template.defaults.prediction_horizon_trading_days) })}>模板默认</button></div>
          <div className="form-grid">
            <Field label="显示货币" source="系统预置 → 选择" hint={`行情按${currencyNames[draft.currency] || draft.currency}留存；换算单独列出汇率日期。`}>
              <select value={draft.display_currency} onChange={edit('display_currency')}><option value="USD">美元（USD）</option><option value="CNY">人民币（CNY）</option></select></Field>
            <Field label="比较基准" source="股票市场自动推荐 → 选择" hint="已按市场推荐；需要时可调整。">
              <select value={draft.benchmark} onChange={edit('benchmark')}>{[...new Set([draft.benchmark, ...session.research_options.benchmarks])].map(code =>
                <option key={code} value={code}>{benchmarkNames[code] || code}{code === draft.selected_security?.benchmark ? ' · 推荐' : ''}</option>)}</select></Field>
          </div>
          {draft.purpose === 'portfolio_review' ? <p className="notice">持仓复核需要持仓和账户估值，请展开完整参数补充后提交。</p> : null}
          <div className="quick-confirm"><h3>开始前，核对本次研究</h3>
            <p>模板：{template?.title}（来源：{template?.source} v{template?.version}）</p>
            <p>{draft.selected_security?.name || draft.ticker} · 研究日 {draft.date} · {benchmarkNames[draft.benchmark] || draft.benchmark}</p>
            <p>原始报价 {currencyNames[draft.currency] || draft.currency} · 显示 {currencyNames[draft.display_currency]}</p>
            <p>资产：{assetNames[draft.asset_type]} · 有效至 {draft.valid_until} · 持仓：{{none:'未提供',empty:'明确空仓',positions:'已填写',json:'待导入'}[draft.portfolio_mode]}</p>
            <p>本次费用预算上限 {usd(Number(draft.budget) * 1000000)} · 最多 {draft.max_calls} 次调用 · {draft.max_seconds} 秒</p>
            <small>来源：系统推荐及模板。{guided ? '股票默认路线最多8次模型调用（含重试）。' : '本次使用完整研究流程。'}{session.demo_mode ? '本次为合成示例。' : '将使用已配置模型，实际费用需对账。'}</small>
            <button className="text-button" type="button" onClick={() => setAdvanced(true)}>查看或修改完整参数</button>
          </div>
        </div> : null}
        <div hidden={!advanced}>
        <div className="research-context"><span>工作空间 <strong>{session.workspace}</strong> · 来源：登录身份</span>
          <button type="button" className="text-button" onClick={() => setAdvanced(false)}>从证券目录选股</button>
          <button type="button" className="text-button" onClick={() => onSettings('research')}>配置研究模板</button></div>
        <div className="form-grid">
          <Field label="研究路线" source="系统预置 → 选择" hint="默认股票路线固定4个环节，含重试最多8次调用。" error={field('execution_mode')}>
            <select value={draft.execution_mode} onChange={e => update({ execution_mode: e.target.value,
              max_calls: String(e.target.value === 'guided_stock' ? Math.min(8, template.limits.max_calls) : template.limits.max_calls) })}>
              <option value="guided_stock">股票快捷研究（推荐）</option><option value="full">完整多分析师研究</option></select></Field>
          <Field label="研究模板" source={template?.source || '预置'} hint={`当前版本 v${template?.version || 0}；新增、复制和修改请进入模板配置。`} error={field('template')}>
            <select name="template" value={draft.template} onChange={e => selectTemplate(e.target.value)}>
              {session.templates.map(t => <option key={t.name} value={t.name}>{t.title} · {t.name}</option>)}</select></Field>
          <Field label="证券标的" source={configured} hint="可输入批准代码，或点击“从证券目录选股”按名称选择。" error={field('ticker')}>
            <input autoFocus name="ticker" value={draft.ticker} onChange={edit('ticker')} list="approved-tickers" maxLength={32} required /></Field>
          <datalist id="approved-tickers">{template?.tickers.map(t => <option key={t} value={t} />)}</datalist>
          <Field label="资产类型" source={configured} error={field('asset_type')}><select name="asset_type" value={draft.asset_type} onChange={e => update({ asset_type: e.target.value, execution_mode: e.target.value === 'crypto' ? 'full' : draft.execution_mode })}>
            {template?.asset_types.map(type => <option key={type} value={type}>{assetNames[type]}</option>)}</select></Field>
          <Field label="研究用途" source={configured} error={field('purpose')}><select name="purpose" value={draft.purpose} onChange={e => update({ purpose: e.target.value, execution_mode: e.target.value === 'portfolio_review' ? 'full' : draft.execution_mode })}>
            {template?.purposes.map(purpose => <option key={purpose} value={purpose}>{purposeNames[purpose]}</option>)}</select></Field>
          <Field label="研究日期" source="预置 → 输入" hint="默认使用服务UTC日期；演示提供历史日期。" error={field('date')}>
            <input name="date" type="date" value={draft.date} onChange={edit('date')} max={session.research_today} required /></Field>
          <Field label="预测期限" source={configured} hint="1–2520个交易会话；评估计划显式固定日历。" error={field('horizon')}>
            <input name="horizon" type="number" min={1} max={2520} value={draft.horizon} onChange={edit('horizon')} required /></Field>
          <Field label="对照基准" source={configured} hint="常用建议为系统预置，也可以键入其他基准。" error={field('benchmark')}>
            <input name="benchmark" value={draft.benchmark} onChange={edit('benchmark')} list="benchmark-suggestions" maxLength={32} required /></Field>
          <datalist id="benchmark-suggestions">{session.research_options.benchmarks.map(value => <option key={value} value={value} />)}</datalist>
          <Field label="报价币种" source={guided ? '股票资料自动确定' : configured} hint="快捷研究按股票原始报价；人民币/美元请在显示货币中选择。" error={field('currency')}>
            <input name="currency" value={draft.currency} readOnly={guided} onChange={edit('currency')} list="currency-suggestions" maxLength={3} required /></Field>
          <Field label="报告显示货币" source="系统预置 → 选择">
            <select value={draft.display_currency} onChange={edit('display_currency')}><option value="USD">美元（USD）</option><option value="CNY">人民币（CNY）</option></select></Field>
          <datalist id="currency-suggestions">{session.research_options.currencies.map(value => <option key={value} value={value} />)}</datalist>
          <Field label="报告有效至" source={configured} hint={`模板有效期 ${template?.defaults.valid_days} 天；可修改，不早于研究日。`} error={field('valid_until')}>
            <input name="valid_until" type="date" value={draft.valid_until} onChange={edit('valid_until')} min={draft.date} required /></Field>
          <Field label="实验名称" source="预置 → 输入" hint="系统生成建议；可使用英文、数字、短横线和下划线。" error={field('experiment')}>
            <input name="experiment" value={draft.experiment} onChange={edit('experiment')} maxLength={96} required /></Field>
        </div>
        {guided ? <div className="research-context"><span>默认研究环节 · 来源：系统预置<br />资料分析 → 多方理由 → 反方理由 → 风险综合</span>
          <small>如需选择分析师团队，请切换完整研究路线。</small></div> : null}
        <fieldset className="research-section" hidden={guided}><legend>分析团队 <span className="field-source">{configured}</span></legend>
          <p>可选择模板允许的分析师，至少一项。</p><div className="check-options">
            {template?.analysts.map(analyst => <label key={analyst}><input type="checkbox" name="analysts" value={analyst}
              aria-invalid={Boolean(field('analysts'))} checked={draft.analysts.includes(analyst)}
              onChange={e => update({ analysts: e.target.checked ? [...draft.analysts, analyst] : draft.analysts.filter(a => a !== analyst) })} />{analystNames[analyst]}</label>)}</div>
          {field('analysts') ? <p className="field-error" role="alert">{field('analysts')}</p> : null}
        </fieldset>
        <div className="research-context model-context"><div><strong>研究模型 · 来源：配置</strong>
          <p>快速：{template?.models.quick} · 深度：{template?.models.deep}</p></div>
          <button type="button" className="text-button" onClick={() => onSettings('models')}>查看模型配置</button></div>
        <details className="form-details" open><summary>执行限额 · 来源：模板配置 → 本次输入</summary>
          <p className="small muted">可以降低上限；提高上限请修改模板。单次预留 {usd(template?.limits.reserve_per_call_microusd)}，预留额不等于账单。</p>
          <div className="form-grid limits-grid">{[
            ['max_calls', '调用上限', template?.limits.max_calls, 1],
            ['max_seconds', '时长上限（秒）', template?.limits.max_seconds, 1],
            ['max_output_tokens', '输出上限（tokens）', template?.limits.max_output_tokens, 1],
            ['budget', '执行预算（USD）', (template?.limits.budget_microusd || 0) / 1000000, 0.000001],
          ].map(([key, title, max, step]) => <Field key={key} label={title} source={configured} hint={`模板上限 ${max}`} error={field(key)}>
            <input name={key} type="number" min={key === 'budget' ? (template?.limits.reserve_per_call_microusd || 1) / 1000000 : 1}
              max={max} step={step} value={draft[key]} onChange={edit(key)} required /></Field>)}</div>
        </details>
        <fieldset className="research-section"><legend>持仓上下文 <span className="field-source">输入</span></legend>
          <Field label="持仓模式" source="预置 → 输入" hint="未提供、明确空仓和有持仓会形成不同研究输入。" error={field('portfolio_mode')}>
            <select name="portfolio_mode" value={draft.portfolio_mode} onChange={edit('portfolio_mode')}>
              <option value="none">未提供持仓</option><option value="empty">明确空仓</option>
              <option value="positions">有持仓</option><option value="json">JSON导入</option></select></Field>
          {draft.portfolio_mode === 'json' ? <><Field label="持仓JSON" source="输入" error={field('portfolio_json')}>
            <textarea name="portfolio_json" rows={4} value={draft.portfolio_json} onChange={edit('portfolio_json')} /></Field>
            <label className="file-control">选择JSON文件<input type="file" accept=".json,application/json"
              onChange={async e => { const file = e.target.files[0]; if (file) update({ portfolio_json: await file.text() }); }} /></label>
            <Button secondary type="button" onClick={importPortfolio}>导入到持仓表</Button></> : null}
          {['positions', 'empty'].includes(draft.portfolio_mode) ? <>
            <div className="form-grid">
              <Field label="持仓币种" source="输入" hint="研究币种提供初始建议，可核对后修改。" error={field('portfolio_currency')}>
                <input name="portfolio_currency" value={draft.portfolio_currency} onChange={edit('portfolio_currency')} list="currency-suggestions" maxLength={3} /></Field>
              <Field label="可用现金" source="输入" hint="未知可留空；0表示明确没有现金。" error={field('cash')}>
                <input name="cash" type="number" step="any" value={draft.cash} onChange={edit('cash')} /></Field>
            </div>
            {draft.portfolio_mode === 'positions' ? <><div className="position-rows">
              {draft.positions.map((row, index) => <div className="position-row" key={row.id}>
                <Field label={`持仓${index + 1}标的`} source="输入" error={field(`positions.${index}.ticker`)}>
                  <input value={row.ticker} onChange={e => position(index, { ticker: e.target.value })} maxLength={32} /></Field>
                <Field label={`持仓${index + 1}数量`} source="输入" error={field(`positions.${index}.quantity`)}>
                  <input type="number" step="any" value={row.quantity} onChange={e => position(index, { quantity: e.target.value })} /></Field>
                <Field label={`持仓${index + 1}平均成本`} source="输入" error={field(`positions.${index}.average_price`)}>
                  <input type="number" min={0} step="any" value={row.average_price} onChange={e => position(index, { average_price: e.target.value })} /></Field>
                <Button type="button" secondary onClick={() => update({ positions: draft.positions.filter(p => p.id !== row.id) })}>删除持仓{index + 1}</Button>
              </div>)}</div><Button type="button" secondary icon="plus" onClick={() => update({
                positions: [...draft.positions, { id: crypto.randomUUID(), ticker: '', quantity: '', average_price: '' }],
              })}>添加持仓</Button></> : <p className="small muted">将提交 positions: []，明确声明空仓。</p>}
          </> : null}
        </fieldset>
        {draft.purpose === 'portfolio_review' ? <fieldset className="research-section"><legend>账户估值 <span className="field-source">输入</span></legend>
          <p>标的 {draft.ticker} · 币种 {draft.currency} 来自本次研究。价格将与执行时留存的收盘价核验；演示收盘价为100。</p>
          <div className="form-grid">{[['equity', '账户净资产'], ['price', '估值价格'], ['current_units', '当前数量'], ['change_units', '建议变动数量']].map(([key, title]) =>
            <Field key={key} label={title} source="输入" error={field(key)}><input name={key} type="number" step="any"
              value={draft[key]} onChange={edit(key)} /></Field>)}
            <Field label="估值日期" source="预置 → 输入" hint="与研究日期一致，并使用同日已留存价格。" error={field('valuation_date')}>
              <input name="valuation_date" type="date" value={draft.valuation_date} onChange={edit('valuation_date')} /></Field>
          </div><Button type="button" secondary onClick={() => update({
            current_units: draft.positions.find(row => row.ticker.trim().toUpperCase() === draft.ticker.trim().toUpperCase())?.quantity || '0',
            valuation_date: draft.date,
          })}>同步持仓数量与研究日期</Button></fieldset> : null}
        </div>
        {!template?.execution.credentials_present ? <div className="notice">请进入模型配置保存模型与密钥，再开始研究。</div> : null}
        <ErrorLine error={error} />
        <div className="modal-footer"><Button secondary type="button" onClick={onClose}>取消</Button>
          <Button type="submit" disabled={busy || !template?.execution.credentials_present}>{busy ? '正在开始…' : '开始研究'}</Button></div>
      </fieldset>
    </form>
  </Modal>;
}
