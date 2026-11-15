import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import worker from '../src/worker.mjs';

const TOKEN='S'.repeat(43);
const schema=readFileSync(new URL('../dashboard-schema.sql', import.meta.url), 'utf8');
const day=stamp=>new Date((stamp+480*60)*1000).toISOString().slice(0,10);
const totals=(requests=0)=>({requests,successes:requests,fresh_input:requests*100,output:requests*20,
  cache_read:requests*60,cache_write:requests*40,real_total:requests*220,cost_usd:(requests*.12345678).toFixed(8)});

function database(t) {
  const sqlite=new DatabaseSync(':memory:');
  sqlite.exec(schema);
  t.after(()=>sqlite.close());
  const DB={prepare(sql) {
    const statement=sqlite.prepare(sql);
    let params=[];
    return {
      bind(...values) { params=values; return this; },
      async all() { return {results:statement.all(...params)}; },
      async first() { return statement.get(...params) || null; },
      async run() { const result=statement.run(...params); return {meta:{changes:Number(result.changes)}}; },
    };
  }, async batch(statements) {
    sqlite.exec('BEGIN');
    try { const results=[]; for (const statement of statements) results.push(await statement.run()); sqlite.exec('COMMIT'); return results; }
    catch (error) { sqlite.exec('ROLLBACK'); throw error; }
  }};
  return {sqlite,env:{SYNC_TOKEN:TOKEN,DB}};
}

async function request(env,path,body,headers={}) {
  return worker.fetch(new Request('https://cc-up.example.workers.dev'+path,{
    method:body===undefined?'GET':'POST',
    headers:{Authorization:'Bearer '+TOKEN,'Content-Type':'application/json',...headers},
    ...(body===undefined?{}:{body:JSON.stringify(body)}),
  }),env);
}

function snapshot(count=2,now=Math.floor(Date.now()/1000)) {
  const midnight=Math.floor((now+480*60)/86400)*86400-480*60;
  return {device_id:'电脑 🖥',device_name:'工作台',report_seq:Date.now(),computed_at:now,offset_minutes:480,rule_version:'test',
    daily:Array.from({length:30},(_,i)=>({day:day(now-i*86400),totals:totals(i===0?count:0),
      by_app:i===0?[{app_type:'codex',...totals(count)}]:[]})),
    windows:[['today',0],['7d',6],['30d',29]].map(([key,days])=>({key,start:midnight-days*86400,end:now,
      totals:totals(count),by_app:[{app_type:'codex',...totals(count)}]}))};
}

test('dashboard schema and ordered migrations create identical tables and indexes',t=>{
  const {sqlite}=database(t),migrated=new DatabaseSync(':memory:');
  t.after(()=>migrated.close());
  for (const file of ['0001_initial.sql','0002_usage_history.sql']) {
    migrated.exec(readFileSync(new URL('../migrations/'+file,import.meta.url),'utf8'));
  }
  const query="SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name";
  assert.deepEqual(sqlite.prepare(query).all(),migrated.prepare(query).all());
});

test('snapshots keep numeric counters and decimal strings across every analytics grouping',async t=>{
  const {env,sqlite}=database(t),value=snapshot();
  assert.equal((await request(env,'/v1/snapshot',value)).status,200);
  const response=await request(env,'/v1/analytics?range=all&app_type=codex');
  assert.equal(response.status,200);
  const result=await response.json();
  for (const total of [result.totals,result.daily.at(-1).totals,result.by_device[0].totals,result.by_app[0].totals]) {
    assert.equal(total.requests,2);
    assert.equal(total.real_total,440);
    assert.equal(total.cost_usd,'0.24691356');
    assert.equal(total.cache_hit_rate,.3);
    assert.equal(total.success_rate,1);
  }
  const stale={...value,report_seq:value.report_seq-1};
  stale.daily=stale.daily.map(bucket=>({...bucket,totals:totals(),by_app:[]}));
  stale.windows=stale.windows.map(bucket=>({...bucket,totals:totals(),by_app:[]}));
  assert.equal((await request(env,'/v1/snapshot',stale)).status,200);
  assert.equal(JSON.parse(sqlite.prepare('SELECT payload FROM usage_snapshots').get().payload).windows[0].totals.requests,2);
  assert.equal(sqlite.prepare('SELECT COUNT(*) AS n FROM usage_daily').get().n,30);
});

test('invalid JSON shapes and malformed snapshot groups return 400 before writing data',async t=>{
  const {env,sqlite}=database(t);
  for (const value of [null,[],42,'text']) {
    assert.equal((await request(env,'/v1/logs',value)).status,400);
    assert.equal((await request(env,'/v1/snapshot',value)).status,400);
  }
  for (const modify of [value=>{value.windows[0]=null;},value=>{value.daily[0]=null;},
    value=>{value.daily[0].by_app=[null];},value=>{value.daily[0].totals=null;}]) {
    const value=snapshot(); modify(value);
    assert.equal((await request(env,'/v1/snapshot',value)).status,400);
  }
  assert.equal(sqlite.prepare('SELECT COUNT(*) AS n FROM devices').get().n,0);
});

test('usage aggregates compatible devices and excludes prior-day snapshots',async t=>{
  const {env}=database(t),now=Math.floor(Date.now()/1000);
  for (const [id,count,computed] of [['desktop',2,now],['laptop',1,now],['old-device',10,now-86400]]) {
    const value={...snapshot(count,computed),device_id:id,device_name:id};
    assert.equal((await request(env,'/v1/snapshot',value)).status,200);
  }
  const response=await request(env,'/v1/usage');
  assert.equal(response.status,200);
  const result=await response.json();
  for (const window of result.windows) {
    assert.equal(window.totals.requests,3);
    assert.equal(window.totals.real_total,660);
    assert.equal(window.totals.cost_usd,'0.37037034');
    assert.equal(window.totals.cache_hit_rate,.3);
  }
  assert.match(result.warning,/old-device/);
});

test('uploads are idempotent, expired logs stay absent, and filters use stored fields',async t=>{
  const {env,sqlite}=database(t),now=Math.floor(Date.now()/1000);
  const record={request_id:'请求 🚀',created_at:now-60,app_type:'claude-desktop',model:'Test-Model',
    input_tokens:100,output_tokens:20,cache_read_tokens:0,cache_creation_tokens:0,status_code:200};
  const body={device_id:'电脑',device_name:'工作台',records:[record,{...record,request_id:'expired',created_at:now-91*86400}]};
  assert.equal((await (await request(env,'/v1/logs',body)).json()).inserted,1);
  assert.equal((await (await request(env,'/v1/logs',body)).json()).inserted,0);
  assert.equal(sqlite.prepare('SELECT COUNT(*) AS n FROM request_logs').get().n,1);
  const response=await request(env,'/v1/logs?app_type=claude&status=2xx&q=test-model');
  assert.deepEqual((await response.json()).records.map(row=>row.request_id),['请求 🚀']);
  body.records=[{...record,latency_ms:Infinity}];
  // JSON.stringify maps Infinity to null; use a numeric JSON overflow to exercise validation.
  const overflow=new Request('https://cc-up.example.workers.dev/v1/logs',{method:'POST',
    headers:{Authorization:'Bearer '+TOKEN,'Content-Type':'application/json'},
    body:JSON.stringify(body).replace('"latency_ms":null','"latency_ms":1e400')});
  assert.equal((await worker.fetch(overflow,env)).status,400);
});

test('history and log pagination preserve Unicode identifiers without gaps',async t=>{
  const {env,sqlite}=database(t),now=Math.floor(Date.now()/1000);
  const putDay=sqlite.prepare('INSERT INTO usage_daily VALUES(?,?,?,?,?,?,?)');
  const putLog=sqlite.prepare('INSERT INTO request_logs VALUES(?,?,?,?)');
  for (let i=0;i<53;i++) {
    const id='设备 '+String(i).padStart(2,'0')+' 🚀';
    putDay.run(id,day(now),1,now,480,'test',JSON.stringify({day:day(now),totals:totals(),by_app:[]}));
    putLog.run(id,'请求 🚀',now,JSON.stringify({request_id:'请求 🚀',created_at:now}));
  }
  for (const path of ['/v1/history','/v1/logs']) {
    const first=await (await request(env,path)).json();
    assert.equal(first.records.length,50);
    assert.match(first.next_cursor,/^[A-Za-z0-9_-]+$/);
    const second=await (await request(env,path+'?cursor='+first.next_cursor)).json();
    assert.equal(second.records.length,3);
    assert.equal(second.next_cursor,null);
    assert.equal(new Set([...first.records,...second.records].map(row=>row.device_id)).size,53);
    for (const cursor of ['invalid','W10', 'x'.repeat(8193)]) {
      assert.equal((await request(env,path+'?cursor='+cursor)).status,400);
    }
  }
});

test('cleanup removes old request logs while retaining daily history',async t=>{
  const {env,sqlite}=database(t),now=Math.floor(Date.now()/1000);
  sqlite.prepare('INSERT INTO request_logs VALUES(?,?,?,?)').run('device','old',now-91*86400,'{}');
  sqlite.prepare('INSERT INTO usage_daily VALUES(?,?,?,?,?,?,?)').run('device','2020-01-01',1,now,480,'test','{}');
  let cleanup;
  await worker.scheduled({},env,{waitUntil:promise=>{cleanup=promise;}});
  await cleanup;
  assert.equal(sqlite.prepare('SELECT COUNT(*) AS n FROM request_logs').get().n,0);
  assert.equal(sqlite.prepare('SELECT COUNT(*) AS n FROM usage_daily').get().n,1);
});

test('CORS allows only configured origins and includes headers on API errors',async t=>{
  const {env}=database(t);
  env.ALLOWED_ORIGINS='https://dashboard.example';
  const allowed=await request(env,'/v1/unknown',undefined,{Origin:'https://dashboard.example'});
  assert.equal(allowed.status,404);
  assert.equal(allowed.headers.get('Access-Control-Allow-Origin'),'https://dashboard.example');
  const denied=await request(env,'/health',undefined,{Origin:'https://other.example'});
  assert.equal(denied.status,403);
  assert.equal(denied.headers.get('Access-Control-Allow-Origin'),null);
});
