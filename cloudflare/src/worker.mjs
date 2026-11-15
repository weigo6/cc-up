const RETENTION_SECONDS = 90 * 86400;
const MAX_BODY = 512 * 1024;
const COUNTERS = ['requests', 'successes', 'fresh_input', 'output', 'cache_read', 'cache_write'];

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
const fail = (condition, message, status = 400) => { if (!condition) throw new ApiError(status, message); };
const json = (value, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { 'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' }
});
const integer = value => Number.isSafeInteger(value) && value >= 0;
const text = (value, max = 1024) => typeof value === 'string' && value.length > 0 && value.length <= max;
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const nowSeconds = () => Math.floor(Date.now() / 1000);

export async function sha256(value) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))].map(v => v.toString(16).padStart(2, '0')).join('');
}

const TOKEN_PATTERN = /^[A-Za-z0-9_-]{32,128}$/;

// VIEWER_TOKENS holds optional plaintext read-only keys, separated by commas or
// newlines. They can only read; uploads still require SYNC_TOKEN.
function viewerTokens(env) {
  const raw = env.VIEWER_TOKENS;
  if (raw === undefined || raw === null || raw === '') return [];
  fail(typeof raw === 'string', 'VIEWER_TOKENS 须为文本', 503);
  const tokens = [...new Set(raw.split(/[\s,]+/).map(value => value.trim()).filter(Boolean))];
  fail(tokens.length > 0 && tokens.length <= 32, 'VIEWER_TOKENS 须包含 1～32 个密钥', 503);
  fail(tokens.every(value => TOKEN_PATTERN.test(value)),
    'VIEWER_TOKENS 里有格式无效的密钥：须为 32～128 位字母、数字、下划线或短横线，多把用英文逗号分隔', 503);
  return tokens;
}

export async function authorize(token, env) {
  fail(TOKEN_PATTERN.test(token || ''), '需要有效的同步密钥', 401);
  fail(typeof env.SYNC_TOKEN === 'string' && TOKEN_PATTERN.test(env.SYNC_TOKEN), '请配置有效的 SYNC_TOKEN 同步密钥', 503);
  const digest = await sha256(token);
  if (digest === await sha256(env.SYNC_TOKEN)) return { role: 'write', label: 'sync' };
  for (const viewer of viewerTokens(env)) {
    if (digest === await sha256(viewer)) return { role: 'read', label: 'viewer' };
  }
  throw new ApiError(401, '同步密钥无效');
}

async function authenticate(request, env) {
  const header = request.headers.get('Authorization') || '';
  fail(/^Bearer [A-Za-z0-9_-]{32,128}$/.test(header), '需要有效的同步密钥', 401);
  return authorize(header.slice(7), env);
}

const validDay = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString().startsWith(value);

function corsHeaders(request, env) {
  const origin = request.headers.get('Origin');
  if (!origin || origin === new URL(request.url).origin) return {};
  const allowed = (env.ALLOWED_ORIGINS || '').split(/[,\n]/).map(value => value.trim()).filter(Boolean);
  fail(allowed.includes(origin), '此网页来源不在 ALLOWED_ORIGINS 白名单中', 403);
  return { 'Access-Control-Allow-Origin': origin, 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type', 'Access-Control-Max-Age': '600', 'Vary': 'Origin' };
}

function withCors(response, headers) {
  const result = new Response(response.body, response);
  for (const [key, value] of Object.entries(headers)) result.headers.set(key, value);
  return result;
}

async function body(request) {
  fail((request.headers.get('Content-Type') || '').split(';')[0].trim() === 'application/json', '需要 JSON 内容', 415);
  const reader = request.body?.getReader();
  fail(reader, '缺少请求内容');
  const chunks = [];
  let size = 0;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_BODY) { await reader.cancel(); throw new ApiError(413, '批次过大'); }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  let value;
  try { value = JSON.parse(new TextDecoder().decode(bytes)); }
  catch { throw new ApiError(400, 'JSON 内容无效'); }
  fail(object(value), '请求内容须为 JSON 对象');
  return value;
}

function deviceStatement(env, id, name, now) {
  fail(text(name, 100), '设备名称无效');
  return env.DB.prepare(`INSERT INTO devices(device_id,device_name,last_seen) VALUES(?,?,?)
    ON CONFLICT(device_id) DO UPDATE SET device_name=excluded.device_name,last_seen=excluded.last_seen`)
    .bind(id, name, now);
}

async function uploadLogs(request, env, now) {
  const value = await body(request);
  fail(text(value?.device_id, 100), '设备 ID 无效');
  const id = value.device_id;
  fail(Array.isArray(value.records) && value.records.length >= 1 && value.records.length <= 100, '每批须为 1～100 条日志');
  const statements = [];
  for (const record of value.records) {
    fail(object(record) && text(record.request_id) && integer(record.created_at) && record.created_at <= now + 300,
      '请求 ID 或时间无效，请检查设备时间');
    fail(text(record.app_type, 100) && text(record.model, 512), '请求应用或模型无效');
    for (const field of ['input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_creation_tokens', 'status_code']) {
      fail(integer(record[field]), `请求字段 ${field} 无效`);
    }
    fail(Object.values(record).every(v => v === null || ['string', 'boolean'].includes(typeof v)
      || (typeof v === 'number' && Number.isFinite(v))), '日志只能包含有限的数据库标量字段');
    const payload = JSON.stringify(record);
    fail(new TextEncoder().encode(payload).length <= 256 * 1024, '单条日志超过 256 KB', 413);
    // Expired retries are acknowledged without restoring expired data.
    if (record.created_at >= now - RETENTION_SECONDS) {
      statements.push(env.DB.prepare(`INSERT OR IGNORE INTO request_logs(device_id,request_id,created_at,payload)
        VALUES(?,?,?,?)`).bind(id, record.request_id, record.created_at, payload));
    }
  }
  statements.push(deviceStatement(env, id, value.device_name, now));
  const results = await env.DB.batch(statements);
  return json({ accepted: value.records.length, inserted: results.slice(0, -1).reduce((n, r) => n + (r.meta?.changes || 0), 0),
    retention_days: 90 });
}

function validateCounts(value, total = false) {
  fail(object(value) && COUNTERS.every(key => integer(value[key])), '统计计数无效');
  fail(value.successes <= value.requests, '成功数超过请求数');
  fail(typeof value.cost_usd === 'string' && /^\d{1,24}(\.\d{1,12})?$/.test(value.cost_usd), '费用无效');
  if (total) fail(value.real_total === value.fresh_input + value.output + value.cache_read + value.cache_write && integer(value.real_total), 'Token 总数无效');
}

function validateBucket(bucket) {
  fail(object(bucket), '统计分组须为对象');
  validateCounts(bucket.totals, true);
  fail(Array.isArray(bucket.by_app) && bucket.by_app.length <= 128, '应用分组无效');
  const apps = new Set();
  for (const group of bucket.by_app) {
    fail(object(group) && text(group.app_type, 100) && !apps.has(group.app_type), '应用分组重复或无效');
    apps.add(group.app_type);
    validateCounts(group);
  }
  for (const key of COUNTERS) fail(bucket.by_app.reduce((n, group) => n + group[key], 0) === bucket.totals[key], '应用分组与总数不符');
  fail(Math.abs(bucket.by_app.reduce((n, group) => n + Number(group.cost_usd), 0) - Number(bucket.totals.cost_usd)) < 0.00001, '费用分组与总数不符');
}

function isoDay(timestamp, offset) { return new Date((timestamp + offset * 60) * 1000).toISOString().slice(0, 10); }

export function validateSnapshot(value, now) {
  fail(object(value) && integer(value.report_seq) && value.report_seq > 0 && integer(value.computed_at)
    && value.computed_at <= now + 300, '快照序号或时间无效');
  fail(Number.isInteger(value.offset_minutes) && value.offset_minutes >= -720 && value.offset_minutes <= 840, '时区无效');
  fail(text(value.rule_version, 100), '统计规则版本无效');
  fail(Array.isArray(value.windows) && value.windows.length === 3, '须完整上报今天、7 天、30 天');
  const days = { today: 0, '7d': 6, '30d': 29 };
  const seen = new Set();
  const midnight = Math.floor((value.computed_at + value.offset_minutes * 60) / 86400) * 86400 - value.offset_minutes * 60;
  for (const window of value.windows) {
    fail(object(window) && Object.hasOwn(days, window.key) && !seen.has(window.key), '统计窗口无效');
    seen.add(window.key);
    fail(window.start === midnight - days[window.key] * 86400 && window.end === value.computed_at, '统计窗口边界无效');
    validateBucket(window);
  }
  fail(Array.isArray(value.daily) && value.daily.length === 30, '须完整上报最近 30 个自然日用量');
  const dates = new Set();
  for (const bucket of value.daily) {
    fail(object(bucket) && validDay(bucket.day) && !dates.has(bucket.day), '日用量日期无效或重复');
    dates.add(bucket.day);
    validateBucket(bucket);
  }
  for (let i = 0; i < 30; i++) fail(dates.has(isoDay(value.computed_at - i * 86400, value.offset_minutes)), '日用量范围不完整');
  for (const window of value.windows) {
    const first = isoDay(window.start, value.offset_minutes);
    const buckets = value.daily.filter(bucket => bucket.day >= first);
    for (const key of [...COUNTERS, 'real_total']) fail(buckets.reduce((n, bucket) => n + bucket.totals[key], 0) === window.totals[key], '日用量与近期汇总不符');
    fail(Math.abs(buckets.reduce((n, bucket) => n + Number(bucket.totals.cost_usd), 0) - Number(window.totals.cost_usd)) < 0.00001, '日费用与近期汇总不符');
  }
}

async function uploadSnapshot(request, env, now) {
  const value = await body(request);
  fail(text(value?.device_id, 100), '设备 ID 无效');
  const id = value.device_id;
  validateSnapshot(value, now);
  await env.DB.batch([
    deviceStatement(env, id, value.device_name, now),
    ...value.daily.map(bucket => env.DB.prepare(`INSERT INTO usage_daily
      (device_id,day,report_seq,computed_at,offset_minutes,rule_version,payload) VALUES(?,?,?,?,?,?,?)
      ON CONFLICT(device_id,day) DO UPDATE SET report_seq=excluded.report_seq,computed_at=excluded.computed_at,
      offset_minutes=excluded.offset_minutes,rule_version=excluded.rule_version,payload=excluded.payload
      WHERE excluded.report_seq > usage_daily.report_seq`).bind(id, bucket.day, value.report_seq,
        value.computed_at, value.offset_minutes, value.rule_version, JSON.stringify(bucket))),
    env.DB.prepare(`INSERT INTO usage_snapshots(device_id,report_seq,computed_at,offset_minutes,rule_version,payload)
      VALUES(?,?,?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET
      report_seq=excluded.report_seq,computed_at=excluded.computed_at,offset_minutes=excluded.offset_minutes,
      rule_version=excluded.rule_version,payload=excluded.payload
      WHERE excluded.report_seq > usage_snapshots.report_seq`)
      .bind(id, value.report_seq, value.computed_at, value.offset_minutes, value.rule_version, JSON.stringify(value))
  ]);
  const current = await env.DB.prepare('SELECT report_seq FROM usage_snapshots WHERE device_id=?').bind(id).first();
  return json({ stored_seq: current.report_seq });
}

async function history(url, env) {
  const start = url.searchParams.get('start') || '1970-01-01';
  const end = url.searchParams.get('end') || '9999-12-31';
  fail(validDay(start) && validDay(end) && start <= end, '历史日期范围无效');
  const params = [start, end];
  const conditions = ['u.day >= ?', 'u.day <= ?'];
  if (url.searchParams.has('device_id')) { conditions.push('u.device_id = ?'); params.push(url.searchParams.get('device_id')); }
  if (url.searchParams.has('cursor')) {
    const cursor = decodeCursor(url.searchParams.get('cursor'));
    fail(cursor.length === 2 && validDay(cursor[0]) && text(cursor[1], 100), '历史分页游标无效');
    conditions.push('(u.day,u.device_id) < (?,?)'); params.push(...cursor);
  }
  const { results } = await env.DB.prepare(`SELECT u.*,d.device_name FROM usage_daily u
    LEFT JOIN devices d ON d.device_id=u.device_id WHERE ${conditions.join(' AND ')}
    ORDER BY u.day DESC,u.device_id DESC LIMIT 51`).bind(...params).all();
  const records = results.slice(0, 50).map(({ payload, ...row }) => ({ ...JSON.parse(payload), ...row }));
  const last = records.at(-1);
  return json({ records, next_cursor: results.length > 50 ? encodeCursor([last.day, last.device_id]) : null,
    retention: 'permanent' });
}

const encodeCursor = tuple => btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(tuple))))
  .replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
function decodeCursor(cursor) {
  try {
    fail(typeof cursor === 'string' && cursor.length <= 8192, '分页游标无效');
    const raw = cursor.replaceAll('-', '+').replaceAll('_', '/');
    const tuple = JSON.parse(new TextDecoder('utf-8', { fatal: true, ignoreBOM: false }).decode(Uint8Array.from(atob(raw), c => c.charCodeAt(0))));
    fail(Array.isArray(tuple), '分页游标无效');
    return tuple;
  } catch { throw new ApiError(400, '分页游标无效'); }
}

async function listLogs(url, env, now) {
  const limit = Number(url.searchParams.get('limit') || 50);
  fail(Number.isInteger(limit) && limit >= 1 && limit <= 100, '分页大小无效');
  const params = [now - RETENTION_SECONDS];
  const conditions = ['l.created_at >= ?'];
  const start = url.searchParams.get('start');
  const end = url.searchParams.get('end');
  if (start !== null) {
    fail(/^\d+$/.test(start) && integer(Number(start)), '请求开始时间无效');
    conditions.push('l.created_at >= ?'); params.push(Number(start));
  }
  if (end !== null) {
    fail(/^\d+$/.test(end) && integer(Number(end)), '请求结束时间无效');
    conditions.push('l.created_at <= ?'); params.push(Number(end));
  }
  fail(start === null || end === null || Number(start) <= Number(end), '请求时间范围无效');
  if (url.searchParams.has('device_id')) {
    conditions.push('l.device_id = ?'); params.push(url.searchParams.get('device_id'));
  }
  if (url.searchParams.has('cursor')) {
    const cursor = decodeCursor(url.searchParams.get('cursor'));
    fail(cursor.length === 3 && integer(cursor[0]) && text(cursor[1], 100) && text(cursor[2]), '分页游标无效');
    conditions.push('(l.created_at,l.device_id,l.request_id) < (?,?,?)');
    params.push(...cursor);
  }
  const app = url.searchParams.get('app_type');
  if (app) {
    fail(text(app, 100), '应用筛选无效');
    conditions.push("CASE WHEN json_extract(l.payload,'$.app_type')='claude-desktop' THEN 'claude' ELSE json_extract(l.payload,'$.app_type') END = ?");
    params.push(app);
  }
  const status = url.searchParams.get('status');
  if (status) {
    if (['2xx','4xx','5xx'].includes(status)) {
      conditions.push("CAST(json_extract(l.payload,'$.status_code') AS INTEGER) BETWEEN ? AND ?");
      const base = Number(status[0]) * 100; params.push(base, base + 99);
    } else {
      fail(/^[1-5]\d{2}$/.test(status), '状态筛选无效');
      conditions.push("json_extract(l.payload,'$.status_code') = ?"); params.push(Number(status));
    }
  }
  const search = url.searchParams.get('q');
  if (search) {
    fail(text(search, 200), '搜索内容过长');
    conditions.push(`(instr(LOWER(l.request_id),?) > 0
      OR instr(LOWER(COALESCE(json_extract(l.payload,'$.model'),'')),?) > 0
      OR instr(LOWER(COALESCE(json_extract(l.payload,'$.request_model'),'')),?) > 0
      OR instr(LOWER(COALESCE(json_extract(l.payload,'$.session_id'),'')),?) > 0
      OR instr(LOWER(COALESCE(json_extract(l.payload,'$.provider_id'),'')),?) > 0)`);
    params.push(...Array(5).fill(search.toLowerCase()));
  }
  // A bounded page stays comfortably below Worker memory and client response limits.
  const pageSize = Math.min(limit, 50);
  const { results } = await env.DB.prepare(`SELECT l.*,d.device_name FROM request_logs l
    LEFT JOIN devices d ON d.device_id=l.device_id WHERE ${conditions.join(' AND ')}
    ORDER BY l.created_at DESC,l.device_id DESC,l.request_id DESC LIMIT ?`).bind(...params, pageSize + 1).all();
  const records = [];
  let bytes = 0;
  for (const row of results.slice(0, pageSize)) {
    bytes += new TextEncoder().encode(row.payload).length;
    if (bytes > 1024 * 1024 && records.length) break;
    records.push({ ...JSON.parse(row.payload), device_id: row.device_id, device_name: row.device_name });
  }
  const last = records.at(-1);
  return json({ records, next_cursor: last && results.length > records.length
    ? encodeCursor([last.created_at, last.device_id, last.request_id]) : null });
}

function completeTotals(row = {}) {
  const result = Object.fromEntries(COUNTERS.map(key => [key, Number(row[key] || 0)]));
  return {
    ...result,
    real_total: result.fresh_input + result.output + result.cache_read + result.cache_write,
    cost_usd: Number(row.cost_usd || 0).toFixed(8),
    cache_hit_rate: result.fresh_input + result.cache_read + result.cache_write
      ? result.cache_read / (result.fresh_input + result.cache_read + result.cache_write) : 0,
    success_rate: result.requests ? result.successes / result.requests : 0,
  };
}

async function analytics(url, env, now) {
  const all = url.searchParams.get('range') === 'all';
  const device = url.searchParams.get('device_id');
  if (device) fail(text(device, 100), '设备筛选无效');
  const range = all ? await env.DB.prepare(`SELECT MIN(day) AS start,MAX(day) AS end FROM usage_daily
    ${device ? 'WHERE device_id=?' : ''}`).bind(...(device ? [device] : [])).first() : null;
  const end = (all ? range?.end : url.searchParams.get('end')) || isoDay(now, 480);
  const start = (all ? range?.start : url.searchParams.get('start')) || (all ? end : isoDay(now - 29 * 86400, 480));
  fail(validDay(start) && validDay(end) && start <= end && (Date.parse(end) - Date.parse(start)) / 86400000 < 36600,
    '统计日期范围无效或超过 100 年');
  const params = [start, end];
  const where = ['u.day >= ?', 'u.day <= ?'];
  if (device) { where.push('u.device_id = ?'); params.push(device); }
  const app = url.searchParams.get('app_type');
  if (app) fail(text(app, 100), '应用筛选无效');
  const joined = app ? "LEFT JOIN json_each(u.payload,'$.by_app') a ON json_extract(a.value,'$.app_type') = ?" : '';
  const values = app ? [app, ...params] : params;
  const root = app ? 'a.value' : 'u.payload';
  const prefix = app ? '$.' : '$.totals.';
  const sums = [...COUNTERS, 'cost_usd'].map(key =>
    `COALESCE(SUM(CAST(json_extract(${root},'${prefix}${key}') AS ${key === 'cost_usd' ? 'REAL' : 'INTEGER'})),0) AS ${key}`).join(',');
  const conditions = where.join(' AND ');
  const dailyRows = (await env.DB.prepare(`SELECT u.day,${sums},COUNT(DISTINCT u.device_id) AS devices,
    MAX(u.computed_at) AS computed_at FROM usage_daily u ${joined} WHERE ${conditions} GROUP BY u.day ORDER BY u.day`).bind(...values).all()).results;
  const deviceRows = (await env.DB.prepare(`SELECT u.device_id,COALESCE(d.device_name,u.device_id) AS device_name,
    ${sums},MAX(u.computed_at) AS computed_at FROM usage_daily u LEFT JOIN devices d ON u.device_id=d.device_id
    ${joined} WHERE ${conditions} GROUP BY u.device_id ORDER BY u.device_id`).bind(...values).all()).results;
  const appSums = [...COUNTERS, 'cost_usd'].map(key =>
    `COALESCE(SUM(CAST(json_extract(a.value,'$.${key}') AS ${key === 'cost_usd' ? 'REAL' : 'INTEGER'})),0) AS ${key}`).join(',');
  const appRows = (await env.DB.prepare(`SELECT json_extract(a.value,'$.app_type') AS app_type,${appSums}
    FROM usage_daily u JOIN json_each(u.payload,'$.by_app') a WHERE ${conditions}
    ${app ? "AND json_extract(a.value,'$.app_type') = ?" : ''} GROUP BY 1`).bind(...params, ...(app ? [app] : [])).all()).results;
  const versions = (await env.DB.prepare(`SELECT offset_minutes,rule_version,COUNT(*) AS days
    FROM usage_daily u WHERE ${conditions} GROUP BY offset_minutes,rule_version`).bind(...params).all()).results;
  const sum = Object.fromEntries([...COUNTERS, 'cost_usd'].map(key => [key, dailyRows.reduce((n, row) => n + Number(row[key]), 0)]));
  return json({ start, end, range: all ? 'all' : 'custom', totals: completeTotals(sum),
    daily: dailyRows.map(({ day, devices, computed_at, ...counts }) => ({ day, devices, computed_at, totals: completeTotals(counts) })),
    by_device: deviceRows.map(({ device_id, device_name, computed_at, ...counts }) => ({ device_id, device_name, computed_at, totals: completeTotals(counts) })),
    by_app: appRows.map(({ app_type, ...counts }) => ({ app_type, totals: completeTotals(counts) })),
    versions, warning: versions.length > 1 ? '此范围包含不同统计版本或时区的日记录，请核对口径。' : '' });
}

async function status(env) {
  const devices = (await env.DB.prepare(`SELECT d.*,s.computed_at,s.offset_minutes,s.rule_version
    FROM devices d LEFT JOIN usage_snapshots s ON d.device_id=s.device_id ORDER BY d.device_name`).all()).results;
  const range = await env.DB.prepare('SELECT MIN(day) AS start,MAX(day) AS end FROM usage_daily').first();
  const applications = (await env.DB.prepare(`SELECT DISTINCT json_extract(a.value,'$.app_type') AS app_type
    FROM usage_daily u JOIN json_each(u.payload,'$.by_app') a ORDER BY 1`).all()).results.map(row => row.app_type);
  return json({ retention_days: 90, devices, history_range: range, applications });
}

async function usage(env, now) {
  const { results } = await env.DB.prepare(`SELECT d.*,s.computed_at,s.payload FROM devices d
    LEFT JOIN usage_snapshots s ON s.device_id=d.device_id ORDER BY s.computed_at DESC`).all();
  const devices = results;
  const basis = devices.find(row => row.payload);
  const sample = basis ? JSON.parse(basis.payload) : null;
  const byKey = new Map();
  const excluded = [];
  const stale = [];
  for (const device of devices) {
    if (!device.payload) { excluded.push(device.device_name); continue; }
    const report = JSON.parse(device.payload);
    const expectedMidnight = Math.floor((now + report.offset_minutes * 60) / 86400) * 86400 - report.offset_minutes * 60;
    if (report.rule_version !== sample.rule_version || report.offset_minutes !== sample.offset_minutes ||
      report.windows.find(w => w.key === 'today').start !== expectedMidnight) {
      excluded.push(device.device_name); continue;
    }
    if (now - report.computed_at > 3600) stale.push(device.device_name);
    for (const window of report.windows) {
      if (!byKey.has(window.key)) byKey.set(window.key, { key: window.key, start: window.start, end: window.end,
        totals: Object.fromEntries([...COUNTERS, 'real_total', 'cost_usd'].map(key => [key, 0])) });
      const combined = byKey.get(window.key);
      combined.end = Math.max(combined.end, window.end);
      for (const key of [...COUNTERS, 'real_total']) combined.totals[key] += window.totals[key];
      combined.totals.cost_usd += Number(window.totals.cost_usd);
    }
  }
  for (const window of byKey.values()) {
    window.totals = completeTotals(window.totals);
  }
  const warnings = [];
  if (excluded.length) warnings.push('以下设备尚无当前日期的兼容快照，未计入总量：' + excluded.join('、'));
  if (stale.length) warnings.push('以下设备超过 1 小时未更新，显示最后上报值：' + stale.join('、'));
  return json({ retention_days: 90, windows: [...byKey.values()],
    devices: devices.map(({ payload, ...device }) => device), warning: warnings.join('。') });
}

export async function cleanup(env, now = nowSeconds()) {
  // Bounded deletes keep a backlog from monopolizing the free-tier daily write budget.
  const result = await env.DB.prepare(`DELETE FROM request_logs WHERE rowid IN
    (SELECT rowid FROM request_logs WHERE created_at < ? ORDER BY created_at LIMIT 2000)`)
    .bind(now - RETENTION_SECONDS).run();
  return result.meta?.changes || 0;
}

export default {
  async fetch(request, env) {
    let headers = {};
    try {
      headers = corsHeaders(request, env);
      const url = new URL(request.url);
      if (request.method === 'OPTIONS') return withCors(new Response(null, { status: 204 }), headers);
      if (url.pathname === '/health' && request.method === 'GET') return withCors(json({ service: 'cc-up', version: 1 }), headers);
      const auth = await authenticate(request, env);
      const now = nowSeconds();
      if (request.method === 'POST' && auth.role !== 'write') throw new ApiError(403, '只读密钥不能上传或修改数据');
      let response;
      if (url.pathname === '/v1/logs' && request.method === 'POST') response = await uploadLogs(request, env, now);
      else if (url.pathname === '/v1/logs' && request.method === 'GET') response = await listLogs(url, env, now);
      else if (url.pathname === '/v1/snapshot' && request.method === 'POST') response = await uploadSnapshot(request, env, now);
      else if (url.pathname === '/v1/usage' && request.method === 'GET') response = await usage(env, now);
      else if (url.pathname === '/v1/history' && request.method === 'GET') response = await history(url, env);
      else if (url.pathname === '/v1/analytics' && request.method === 'GET') response = await analytics(url, env, now);
      else if (url.pathname === '/v1/status' && request.method === 'GET') response = await status(env);
      else response = json({ error: '接口不存在' }, 404);
      return withCors(response, headers);
    } catch (error) {
      return withCors(json({ error: error instanceof ApiError ? error.message : '云端数据库操作失败，请检查配置和免费额度' }, error instanceof ApiError ? error.status : 503), headers);
    }
  },
  async scheduled(event, env, context) {
    context.waitUntil(cleanup(env));
  }
};
