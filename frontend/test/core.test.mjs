import test from 'node:test';
import assert from 'node:assert/strict';
import {dayKey,addDays,dateRange,rangeForPreset,timestampRange,normalizeLog,heatmapCells,heatLevel,heatThresholds,csvString,validateEndpoint,escapeHtml,appName,parseSiteConfig,safeStore} from '../assets/core.mjs';
import {createDemoStore} from '../assets/demo.mjs';

test('disabled browser storage cannot prevent the dashboard from starting',t=>{
  const name='ccUpBlockedStorage';
  Object.defineProperty(globalThis,name,{configurable:true,get(){throw new Error('Storage disabled');}});
  t.after(()=>{delete globalThis[name];});
  assert.equal(safeStore.get(name,'theme'),null);
  assert.doesNotThrow(()=>safeStore.set(name,'theme','light'));
  assert.doesNotThrow(()=>safeStore.remove(name,'theme'));
});

test('calendar windows preserve timezone and leap-day boundaries',()=>{
  assert.equal(dayKey(Date.parse('2026-11-14T17:00:00Z'),480),'2026-11-15');
  assert.equal(addDays('2024-03-01',-1),'2024-02-29');
  assert.equal(dateRange('2024-01-01','2024-12-31').length,366);
  assert.throws(()=>dateRange('2026-02-30','2026-03-01'));
  assert.throws(()=>dateRange('2020-01-01','2026-01-01'));
  const range=timestampRange('2026-11-15','2026-11-15',480);
  assert.equal(range.end-range.start,86399);
  assert.equal(new Date(range.start*1000).toISOString(),'2026-11-14T16:00:00.000Z');
});

test('request display applies the same fresh-input semantics as the collector',()=>{
  const record={app_type:'codex',input_tokens:1000,output_tokens:100,cache_read_tokens:300,cache_creation_tokens:200,input_token_semantics:1};
  assert.equal(normalizeLog(record).fresh_input,500);
  assert.equal(normalizeLog(record).real_total,1100);
  assert.equal(normalizeLog({...record,input_token_semantics:0}).fresh_input,700);
  assert.equal(normalizeLog({...record,input_token_semantics:2}).fresh_input,1000);
  assert.equal(normalizeLog({...record,input_tokens:100}).fresh_input,100);
});

test('heatmap covers every date once in complete Monday-first weeks',()=>{
  for(const year of [2024,2025,2026]){
    const cells=heatmapCells(year),inside=cells.filter(c=>!c.outside);
    assert.equal(inside[0].day,`${year}-01-01`);
    assert.equal(inside.at(-1).day,`${year}-12-31`);
    assert.equal(new Set(inside.map(c=>c.day)).size,year===2024?366:365);
    assert.equal(cells.length%7,0);
    assert.equal(new Date(cells[0].day+'T00:00:00Z').getUTCDay(),1);
  }
  const thresholds=heatThresholds([0,1,10,100,1000]);
  assert.equal(heatLevel(0,thresholds),0);
  assert.equal(heatLevel(1000,thresholds)>=3,true);
});

test('exports escape spreadsheet formulas and UI values escape markup',()=>{
  const csv=csvString(['字段'],[['=HYPERLINK("bad")'],['a,b'],['x"y'],[42]]);
  assert.ok(csv.startsWith('\ufeff'));assert.match(csv,/'=HYPERLINK/);assert.ok(csv.includes('"x""y"'));
  assert.equal(escapeHtml('<img onerror="bad">'),'&lt;img onerror=&quot;bad&quot;&gt;');
  assert.equal(appName('__proto__'),'__proto__');
});

test('connection validation keeps secrets out of URLs and rejects insecure remote endpoints',()=>{
  assert.equal(validateEndpoint('https://example.workers.dev/'),'https://example.workers.dev');
  assert.equal(validateEndpoint('http://127.0.0.1:8766'),'http://127.0.0.1:8766');
  for(const value of ['http://remote.example','https://user:pass@remote.example','https://remote.example/path','https://remote.example/?token=secret'])assert.throws(()=>validateEndpoint(value));
});

test('demo analytics and filters behave like the real data contract',async()=>{
  const demo=createDemoStore(),status=await demo.request('/v1/status');
  assert.equal(status.devices.length,2);
  const all=await demo.request('/v1/analytics');
  assert.equal(all.totals.requests,all.by_device.reduce((n,r)=>n+r.totals.requests,0));
  assert.equal(all.totals.real_total,all.by_app.reduce((n,r)=>n+r.totals.real_total,0));
  const filtered=await demo.request('/v1/analytics',{app_type:'codex',device_id:status.devices[0].device_id});
  assert.equal(filtered.by_app.length,1);assert.equal(filtered.by_device.length,1);
  const page=await demo.request('/v1/logs',{status:'429',q:'gpt'});
  assert.ok(page.records.every(r=>r.status_code===429&&r.model.includes('gpt')));
});

test('all-time preset preserves the full multi-year history range',()=>{
  const range=rangeForPreset('all',{start:'2020-01-01',end:'2026-11-15'},'2026-11-15');
  assert.deepEqual(range,{start:'2020-01-01',end:'2026-11-15',range:'all'});
  assert.ok(dateRange(range.start,range.end,36600).length>366);
  assert.equal(rangeForPreset(7,{},'2026-11-15').start,'2026-11-09');
  assert.deepEqual(rangeForPreset('all',{},'2026-11-15'),{start:'2026-11-15',end:'2026-11-15',range:'all'});
});

test('all-time demo includes more than a year and day detail remains a single day',async()=>{
  const demo=createDemoStore(),all=await demo.request('/v1/analytics',{range:'all'});
  assert.equal(dateRange(all.start,all.end,36600).length,450);
  assert.ok(all.daily.length>366);
  const day=all.daily[0].day,detail=await demo.request('/v1/analytics',{start:day,end:day});
  assert.equal(detail.daily.length,1);
  assert.ok(detail.totals.real_total<all.totals.real_total);
});

test('site config auto-connect only accepts a valid endpoint and token',()=>{
  const token='A'.repeat(43);
  assert.deepEqual(parseSiteConfig({endpoint:'https://cc-up.example.workers.dev/',token}),{endpoint:'https://cc-up.example.workers.dev',token});
  assert.deepEqual(parseSiteConfig({endpoint:' http://127.0.0.1:8787 ',token}),{endpoint:'http://127.0.0.1:8787',token});
  for(const value of [null,undefined,{},[],{endpoint:'https://x.workers.dev'},{endpoint:'https://x.workers.dev',token:'short'},{endpoint:'https://x.workers.dev',token:'A'.repeat(129)},{endpoint:'http://remote.example',token},{endpoint:'https://x.workers.dev/path',token},{endpoint:'https://x.workers.dev?token=1',token}])assert.equal(parseSiteConfig(value),null);
});
