import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,writeFileSync,existsSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {buildWebConfig} from '../build_web_config.mjs';

test('site build writes only valid configuration without logging the key',t=>{
  const root=mkdtempSync(join(tmpdir(),'cc-up-config-'));
  t.after(()=>rmSync(root,{recursive:true,force:true}));
  const target=join(root,'config.json'),token='A'.repeat(43),logs=[];
  const config=buildWebConfig({CC_UP_ENDPOINT:'https://example.workers.dev/',CC_UP_TOKEN:token},target,message=>logs.push(message));
  assert.deepEqual(JSON.parse(readFileSync(target,'utf8')),{endpoint:'https://example.workers.dev',token});
  assert.equal(config.token,token);
  assert.ok(logs.every(message=>!message.includes(token)));
});

test('removed or invalid environment variables cannot leave a previous key published',t=>{
  const root=mkdtempSync(join(tmpdir(),'cc-up-config-'));
  t.after(()=>rmSync(root,{recursive:true,force:true}));
  const target=join(root,'config.json');
  writeFileSync(target,'old secret');
  assert.equal(buildWebConfig({},target,()=>{}),null);
  assert.equal(existsSync(target),false);
  for (const env of [{CC_UP_TOKEN:'A'.repeat(43)}, {CC_UP_ENDPOINT:'https://example.workers.dev'},
    {CC_UP_ENDPOINT:'https://user:secret@example.workers.dev',CC_UP_TOKEN:'A'.repeat(43)},
    {CC_UP_ENDPOINT:'https://example.workers.dev',CC_UP_TOKEN:'short'}]) {
    writeFileSync(target,'old secret');
    assert.throws(()=>buildWebConfig(env,target,()=>{}));
    assert.equal(existsSync(target),false);
  }
});
