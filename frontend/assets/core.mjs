export const COUNTERS = ['requests','successes','fresh_input','output','cache_read','cache_write'];
export const APP_NAMES = {claude:'Claude Code',codex:'Codex',gemini:'Gemini CLI',grokbuild:'Grok Build',opencode:'OpenCode',pi:'Pi',agy:'Antigravity',kimi:'Kimi Code',copilot:'Copilot CLI',mcode:'MiniMax Code',workbuddy:'WorkBuddy',dsh:'DeepSeek Harness',omp:'Oh My Pi'};
export const appName = key => Object.hasOwn(APP_NAMES,key) ? APP_NAMES[key] : String(key || '未知应用');
export const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const safeStore = {
  get(name,key){try{return globalThis[name]?.getItem(key) ?? null;}catch{return null;}},
  set(name,key,value){try{globalThis[name]?.setItem(key,value);}catch{}},
  remove(name,key){try{globalThis[name]?.removeItem(key);}catch{}},
};
export function dayKey(timestamp=Date.now(),offset=480){return new Date(timestamp+offset*60000).toISOString().slice(0,10);}
export function addDays(day,delta){return new Date(Date.parse(day+'T00:00:00Z')+delta*86400000).toISOString().slice(0,10);}
export function validDay(day){return typeof day==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(day)&&!Number.isNaN(Date.parse(day))&&new Date(day).toISOString().startsWith(day);}
export function dateRange(start,end,max=366){if(!validDay(start)||!validDay(end)||start>end)throw new Error('请选择有效的开始和结束日期。');const count=Math.round((Date.parse(end)-Date.parse(start))/86400000)+1;if(count>max)throw new Error(`一次最多查询 ${max} 个自然日。`);return Array.from({length:count},(_,i)=>addDays(start,i));}
export function timestampRange(start,end,offset=480){dateRange(start,end,36600);return {start:Math.floor(Date.parse(start+'T00:00:00Z')/1000)-offset*60,end:Math.floor(Date.parse(end+'T00:00:00Z')/1000)-offset*60+86399};}
export function rangeForPreset(preset,history={},today=dayKey()){if(preset==='all')return {start:history?.start||today,end:history?.end||today,range:'all'};const days=Number(preset);if(!Number.isInteger(days)||days<1||days>36600)throw new Error('时间范围无效。');return {start:addDays(today,1-days),end:today};}
export function completeTotals(counts={}){
  const t=Object.fromEntries(COUNTERS.map(k=>[k,Number(counts[k]||0)]));
  const input=t.fresh_input+t.cache_read+t.cache_write;
  return {...t,real_total:input+t.output,cost_usd:Number(counts.cost_usd||0).toFixed(8),
    cache_hit_rate:input?t.cache_read/input:0,success_rate:t.requests?t.successes/t.requests:0};
}
export function sumTotals(items){return completeTotals(Object.fromEntries([...COUNTERS,'cost_usd'].map(k=>[k,items.reduce((s,t)=>s+Number(t[k]||0),0)])));}
export function compact(value,digits=1){const n=Number(value||0);for(const [unit,size] of [['B',1e9],['M',1e6],['K',1e3]])if(Math.abs(n)>=size)return {value:(n/size).toLocaleString('en-US',{maximumFractionDigits:digits}),unit};return {value:n.toLocaleString('en-US',{maximumFractionDigits:digits}),unit:''};}
export function short(value){const f=compact(value);return f.value+f.unit;}
export const number = value => Number(value||0).toLocaleString('en-US',{maximumFractionDigits:0});
export const percent = value => (Number(value||0)*100).toFixed(1)+'%';
export function money(value){const n=Number(value||0);return '$'+n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:n>0&&n<.01?6:2});}
export function timeLabel(stamp,offset=480){return new Date(Number(stamp)*1000+offset*60000).toISOString().slice(0,19).replace('T',' ');}
export function normalizeLog(record){const input=Number(record.input_tokens||0),read=Number(record.cache_read_tokens||0),write=Number(record.cache_creation_tokens||0),output=Number(record.output_tokens||0);let fresh=input;if(Number(record.input_token_semantics)!==2&&['codex','gemini','grokbuild'].includes(record.app_type)){const subtract=Number(record.input_token_semantics)===1?read+write:read;if(input>=subtract)fresh=input-subtract;}return {fresh_input:fresh,output,cache_read:read,cache_write:write,real_total:fresh+output+read+write};}
export function heatmapCells(year){if(!Number.isInteger(year)||year<1970||year>9998)throw new Error('年份无效');const first=`${year}-01-01`,last=`${year}-12-31`;const offset=(new Date(first+'T00:00:00Z').getUTCDay()+6)%7;const start=addDays(first,-offset);const length=Math.ceil((offset+dateRange(first,last).length)/7)*7;return Array.from({length},(_,i)=>{const day=addDays(start,i);return {day,outside:day<first||day>last,index:i,column:Math.floor(i/7),row:i%7};});}
export function heatThresholds(values){const sorted=values.map(Number).filter(v=>v>0).sort((a,b)=>a-b);return [.25,.5,.75].map(q=>sorted.length?sorted[Math.min(sorted.length-1,Math.floor(sorted.length*q))]:0);}
export function heatLevel(value,thresholds){if(!value)return 0;return 1+thresholds.filter(t=>value>t).length;}
export function csvString(headers,rows){const cell=value=>{let text=String(value??'');if(typeof value==='string'&&/^[\s]*[=+\-@]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"';};return '\ufeff'+[headers,...rows].map(row=>row.map(cell).join(',')).join('\r\n');}
export function validateEndpoint(value){let url;try{url=new URL(value.trim());}catch{throw new Error('请填写有效的 Worker 根地址。');}if(url.protocol!=='https:'&&!(url.protocol==='http:'&&['127.0.0.1','localhost','[::1]'].includes(url.hostname)))throw new Error('Worker 地址须使用 HTTPS，本机预览可使用 HTTP。');if(url.username||url.password||url.search||url.hash||url.pathname.replaceAll('/',''))throw new Error('请填写 Worker 根地址，不包含路径、参数或登录信息。');return url.origin;}
export function queryString(values){const params=new URLSearchParams();for(const [key,value] of Object.entries(values))if(value!==''&&value!==undefined&&value!==null)params.set(key,String(value));return params.toString();}
export function parseSiteConfig(value){if(!value||typeof value!=='object'||Array.isArray(value))return null;const endpoint=typeof value.endpoint==='string'?value.endpoint.trim():'',token=typeof value.token==='string'?value.token.trim():'';if(!endpoint||!/^[A-Za-z0-9_-]{32,128}$/.test(token))return null;try{return {endpoint:validateEndpoint(endpoint),token};}catch{return null;}}
