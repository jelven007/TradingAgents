export class ApiError extends Error {
  constructor(status, requestId, fields = []) {
    super({
      400: '请求未被接受，请核对输入、任务状态和研究规则。',
      401: '账号或密码不正确，或登录已过期，请重新登录。',
      403: '当前账号不能执行此操作。',
      404: '没有找到该记录。',
      409: '配置已被更新，请点击刷新，重新载入后再保存或测试。',
      429: '已达到预算或执行容量上限，请稍后重试。',
    }[status] || '服务暂时不可用，请稍后重试。');
    this.status = status;
    this.requestId = requestId;
    this.fields = fields;
    if (fields.length) this.message = '请修正标出的字段后重新提交。';
  }
}

let sessionCsrf = '';
export const setSessionCsrf = value => { sessionCsrf = value || ''; };

export async function request(token, path, { method = 'GET', body, key, signal } = {}) {
  const headers = { 'X-Workbench-Client': 'web' };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (!token && sessionCsrf && method !== 'GET') headers['X-Workbench-CSRF'] = sessionCsrf;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (key) headers['Idempotency-Key'] = key;
  const response = await fetch(path, {
    method, headers, signal, cache: 'no-store', credentials: token ? 'omit' : 'same-origin',
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok) throw new ApiError(response.status, value.request_id, value.fields || []);
  return value.data;
}

export const labels = {
  queued: '等待执行', running: '研究中', succeeded: '已完成', failed: '失败',
  cancelled: '已取消', timed_out: '已超时', draft: '待复核', approved: '已批准',
  published: '已发布', withdrawn: '已撤回', rejected: '已退回',
  needs_review: '需人工核验', blocked: '规则阻断', passed: '检查通过',
  prospective: '前瞻观察', diagnostic: '历史诊断', interim: '中期观察',
  final: '完整期限', pending: '待观察', not_submitted: '未提交',
  Buy: '买入', Overweight: '增持', Hold: '持有', Underweight: '减持',
  Sell: '卖出', Insufficient: '资料不足，暂不判断', REVIEW: '待判断',
};
export const label = value => labels[value] || value || '—';
export const shortId = id => id ? `${id.slice(0, 8)}…` : '—';
export const dateTime = value => value
  ? new Date(typeof value === 'number' ? value * 1000 : value).toLocaleString('zh-CN', { hour12: false })
  : '—';
export const usd = amount => amount == null ? '待对账'
  : `$${(amount / 1000000).toFixed(amount > 0 && amount < 10000 ? 6 : 2)}`;
export const today = () => {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
};
export const futureDate = days => {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
};

const qualityText = {
  insufficient_research: ['资料不足，暂不判断', '关键行情或完整模型结论不可用；保留已取得资料，更新研究后再判断。'],
  out_of_scope: ['标的未获准研究', '标的不在当前批准的研究范围内。'],
  identity_mismatch: ['研究身份或日期不一致', '决策标的或日期与固定研究契约不一致。'],
  mandate_mismatch: ['研究契约缺失或变化', '决策未完整携带已固定的研究契约。'],
  unparsed_rating: ['评级无法确认', '无法解析为支持的研究评级，需解决后再生成新版本。'],
  missing_decision: ['缺少研究结论', '报告没有有效的决策正文。'],
  vendor_failure: ['供应商调用失败', '部分来源调用失败，需核验信息缺口和影响。'],
  unknown_license: ['来源使用许可未确认', '尚未声明来源存储与使用许可，发布被阻断。'],
  unknown_publication_time: ['首次公开时间未知', '已留存的来源内容不能证明信息最早何时公开。'],
  unavailable_source: ['来源数据不可用', '部分来源返回不可用，需核验是否影响结论。'],
  missing_verified_prices: ['缺少结构化价格证据', '没有留存可验证的开盘、最高、最低、收盘和成交量数据。'],
  future_price: ['价格晚于研究日', '存在研究日之后的价格数据。'],
  stale_price: ['价格超过时效', '最新价格超过配置允许的日历天时效。'],
  unverified_currency: ['价格币种待核验', '来源适配器未提供可核验的价格币种。'],
  currency_mismatch: ['价格币种不一致', '行情币种与固定研究契约不同。'],
  invalid_market_facts: ['结构化行情不符合规则', '价格身份、日期、有限值、成交量或高低区间不符合规则。'],
  conflicting_prices: ['同日收盘价冲突', '来源对同一天的收盘价不一致。'],
  invalid_proposed_price: ['建议价格无效', '明确的目标价、入场价或止损价不是有限正数。'],
  unverified_proposed_price: ['建议价格缺少估值依据', '明确价格字段未关联可验证的估值模型。'],
  allocation_input_mismatch: ['仓位估值输入不匹配', '标的、币种、日期或证据引用不能相互匹配。'],
  allocation_price_mismatch: ['仓位价格未经核验', '仓位计算使用的价格或币种与证据不同。'],
  short_position: ['违反只做多约束', '目标持仓数量违反当前只做多策略。'],
  concentration: ['仓位超过集中度', '目标仓位超过批准的权益占比。'],
  missing_account_valuation: ['缺少账户估值', '持仓复核需要显式、经过核验的仓位估值输入。'],
  account_not_assessed: ['未评估账户配置', '一般研究结论不构成可执行的账户仓位安排。'],
  unverified_narrative: ['研究论据待人工核验', '需人工核验结论、引用、研究期限和结论失效条件。'],
};
export const qualityIssue = issue => ({
  title: qualityText[issue.code]?.[0] || issue.code,
  description: qualityText[issue.code]?.[1] || issue.detail,
});
