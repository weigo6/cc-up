import {COUNTERS,addDays,dayKey,completeTotals,sumTotals,timestampRange} from './core.mjs';

export function createDemoStore(){
  const now=Math.floor(Date.now()/1000),today=dayKey(),apps=['claude','codex','gemini'];
  let seed=20837;const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
  const devices=[{device_id:'demo-desktop',device_name:'工作台 · Windows',computed_at:now-120,last_seen:now-120,offset_minutes:480,rule_version:'demo'},
    {device_id:'demo-laptop',device_name:'随行本 · Windows',computed_at:now-720,last_seen:now-720,offset_minutes:480,rule_version:'demo'}];
  const buckets=[];
  for(let i=449;i>=0;i--){const day=addDays(today,-i),weekday=new Date(day+'T00:00:00Z').getUTCDay();for(let d=0;d<2;d++){
    if(random()<.06)continue;
    const activity=random()>.14;const scale=(weekday===0||weekday===6?.36:1)*(d?.48:1)*(i<50?1.4:1);
    const requests=activity?Math.floor((80+random()*260)*scale):0;
    const fresh=activity?Math.floor((200000+random()*1700000)*scale):0;
    const t=completeTotals({requests,successes:Math.floor(requests*(.97+random()*.025)),fresh_input:fresh,
      output:Math.floor(fresh*(.07+random()*.15)),cache_read:Math.floor(fresh*(1.5+random()*3.5)),
      cache_write:Math.floor(fresh*random()*.16),cost_usd:activity?(1.4+random()*8.5)*scale:0});
    const groups=apps.map((app_type,j)=>{const weight=j===0?.43:j===1?.39:.18;const group={app_type};for(const key of COUNTERS)group[key]=Math.floor(t[key]*weight);group.cost_usd=(Number(t.cost_usd)*weight).toFixed(8);return group;});
    for(const key of COUNTERS)groups[2][key]+=t[key]-groups.reduce((sum,g)=>sum+g[key],0);
    groups[2].cost_usd=(Number(t.cost_usd)-Number(groups[0].cost_usd)-Number(groups[1].cost_usd)).toFixed(8);
    buckets.push({day,device_id:devices[d].device_id,totals:t,by_app:requests?groups:[],computed_at:now-120});
  }}
  const models={claude:['claude-sonnet-4-5','claude-opus-4-5'],codex:['gpt-5.1-codex','gpt-5.2'],gemini:['gemini-2.5-pro','gemini-2.5-flash']};
  const records=Array.from({length:300},(_,i)=>{const app_type=apps[i%3],day=addDays(today,-Math.floor(i/5)),device=devices[i%2],input=Math.floor(2000+random()*58000),read=Math.floor(input*.7),output=Math.floor(100+random()*4500),created_at=Math.min(timestampRange(day,day).start+Math.floor(random()*85000),now-i*20);return {request_id:`demo-${300-i}-${Math.floor(random()*9999)}`,created_at,device_id:device.device_id,device_name:device.device_name,app_type,model:models[app_type][i%2],request_model:models[app_type][i%2],pricing_model:models[app_type][i%2],provider_id:i%2?'provider-primary':'provider-backup',input_tokens:input,output_tokens:output,cache_read_tokens:read,cache_creation_tokens:0,input_token_semantics:app_type==='claude'?2:1,total_cost_usd:(random()*.16+.002).toFixed(8),input_cost_usd:'0.0012',output_cost_usd:'0.0048',cache_read_cost_usd:'0.0003',cache_creation_cost_usd:'0',cost_multiplier:'1.0',status_code:i%23===0?429:i%37===0?502:200,latency_ms:Math.floor(600+random()*9500),first_token_ms:Math.floor(120+random()*900),session_id:`demo-session-${Math.floor(i/5)}`,data_source:i%4===0?'codex_session':'proxy',error_message:i%23===0?'示例：上游暂时限流':null};}).sort((a,b)=>b.created_at-a.created_at||b.request_id.localeCompare(a.request_id));
  function analytics(params){
    const all=params.range==='all',start=all?addDays(today,-449):(params.start||addDays(today,-29)),end=all?today:(params.end||today);
    const selected=buckets.filter(b=>b.day>=start&&b.day<=end&&(!params.device_id||b.device_id===params.device_id)).map(b=>({...b,totals:params.app_type?completeTotals(b.by_app.find(g=>g.app_type===params.app_type)||{}):b.totals}));
    const daily=new Map(),byDevice=new Map(),byApp=new Map();
    for(const b of selected){if(!daily.has(b.day))daily.set(b.day,[]);daily.get(b.day).push(b);if(!byDevice.has(b.device_id))byDevice.set(b.device_id,[]);byDevice.get(b.device_id).push(b.totals);for(const group of b.by_app)if(!params.app_type||params.app_type===group.app_type){if(!byApp.has(group.app_type))byApp.set(group.app_type,[]);byApp.get(group.app_type).push(group);}}
    return {start,end,range:params.range==='all'?'all':'custom',totals:sumTotals(selected.map(b=>b.totals)),daily:[...daily].sort(([a],[b])=>a.localeCompare(b)).map(([day,rows])=>({day,devices:rows.length,computed_at:now-120,totals:sumTotals(rows.map(b=>b.totals))})),
      by_device:[...byDevice].map(([device_id,items])=>({...devices.find(d=>d.device_id===device_id),totals:sumTotals(items)})),by_app:[...byApp].map(([app_type,items])=>({app_type,totals:sumTotals(items)})),versions:[{offset_minutes:480,rule_version:'demo'}],warning:''};
  }
  return {async request(path,params={}){
    if(path==='/v1/status')return {retention_days:90,devices,applications:apps,history_range:{start:addDays(today,-449),end:today}};
    if(path==='/v1/analytics')return analytics(params);
    if(path==='/v1/logs'){
      let rows=records.filter(r=>(!params.start||r.created_at>=Number(params.start))&&(!params.end||r.created_at<=Number(params.end))&&(!params.device_id||r.device_id===params.device_id)&&(!params.app_type||r.app_type===params.app_type));
      if(params.status)rows=rows.filter(r=>params.status.endsWith('xx')?Math.floor(r.status_code/100)===Number(params.status[0]):r.status_code===Number(params.status));
      if(params.q)rows=rows.filter(r=>[r.model,r.request_model,r.request_id,r.session_id,r.provider_id].some(v=>v.toLowerCase().includes(params.q.toLowerCase())));
      const offset=Number(params.cursor||0),size=Number(params.limit||25);return {records:rows.slice(offset,offset+size),next_cursor:rows.length>offset+size?String(offset+size):null};
    }
    throw new Error('演示接口不存在');
  }};
}
