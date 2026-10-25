import React from 'react';
import { usd } from './api';
import { analystNames } from './research-form';

export function InputSummary({ inputs }) {
  if (!inputs) return null;
  const portfolio = inputs.portfolio;
  const value = inputs.allocation_valuation;
  return <details className="input-summary"><summary>查看提交时的研究输入 · 来源：固定任务</summary>
    <div className="input-summary-body">
      {inputs.execution_mode ? <p>研究路线：{inputs.execution_mode === 'guided_stock' ? '股票快捷研究（最多8次调用，含重试）' : '完整研究'}
        {inputs.display_currency ? ` · 显示货币：${inputs.display_currency}` : ''}</p> : null}
      {inputs.execution_mode === 'guided_stock' ? <p>固定环节：资料分析、多方理由、反方理由、风险综合。</p>
        : <p>分析团队：{inputs.analysts.map(name => analystNames[name] || name).join('、')}</p>}
      {inputs.models?.quick ? <p>快速模型：{inputs.models.quick} · 深度模型：{inputs.models.deep}</p> : null}
      {inputs.limits ? <p>调用上限：{inputs.limits.max_calls} · 时长：{inputs.limits.max_seconds}秒 ·
        输出：{inputs.limits.max_output_tokens} tokens · 预算：{usd(inputs.limits.budget_microusd)}</p> : null}
      <p>持仓上下文：{portfolio === null ? '未提供' : portfolio.positions.length ? '有持仓' : '明确空仓'}</p>
      {portfolio ? <><p>币种：{portfolio.currency || '未提供'} · 可用现金：{portfolio.cash ?? '未提供'}</p>
        {portfolio.positions.length ? <ul>{portfolio.positions.map(row => <li key={row.ticker}>
          {row.ticker} · 数量 {row.quantity} · 平均成本 {row.average_price ?? '未提供'}
        </li>)}</ul> : null}</> : null}
      {value ? <p>账户估值：净资产 {value.equity} {value.currency} · {value.valuation_date} 价格 {value.price} ·
        当前 {value.current_units} · 建议变动 {value.change_units}</p> : null}
      <p>模板来源：{inputs.template_revision === '预置' ? '运营预置' : `保存版本 ${inputs.template_revision}`}</p>
    </div>
  </details>;
}
