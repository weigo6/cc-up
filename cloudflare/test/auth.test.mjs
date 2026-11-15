import test from 'node:test';
import assert from 'node:assert/strict';
import worker, {authorize} from '../src/worker.mjs';

const SYNC = 'S'.repeat(43);
const VIEWER = 'V'.repeat(43);
const PHONE = 'W'.repeat(43);
const THIRD = 'U'.repeat(43);

const env = (viewers = VIEWER) => ({SYNC_TOKEN: SYNC, VIEWER_TOKENS: viewers});

test('sync key stays writable while a plaintext viewer key only reads', async () => {
  assert.equal((await authorize(SYNC, env())).role, 'write');
  assert.equal((await authorize(VIEWER, env())).role, 'read');
});

test('several viewer keys coexist, separated by commas or newlines', async () => {
  const shared = env(`${VIEWER}, ${PHONE}\n${THIRD}`);
  assert.equal((await authorize(VIEWER, shared)).role, 'read');
  assert.equal((await authorize(PHONE, shared)).role, 'read');
  assert.equal((await authorize(THIRD, shared)).role, 'read');
  await assert.rejects(() => authorize('Z'.repeat(43), shared), /同步密钥无效/);
});

test('invalid viewer configuration fails loudly', async () => {
  await assert.rejects(() => authorize('X'.repeat(43), env('too-short')), /格式无效/);
  const many = Array.from({length: 33}, (_, i) => 'A'.repeat(41) + String(i).padStart(2, '0')).join(',');
  await assert.rejects(() => authorize('X'.repeat(43), env(many)), /1～32/);
  await assert.rejects(() => authorize('X'.repeat(43), {SYNC_TOKEN: SYNC, VIEWER_TOKENS: 42}), /须为文本/);
});

test('without VIEWER_TOKENS only the sync key is accepted', async () => {
  await assert.rejects(() => authorize(VIEWER, {SYNC_TOKEN: SYNC}), /同步密钥无效/);
  assert.equal((await authorize(SYNC, {SYNC_TOKEN: SYNC})).role, 'write');
  await assert.rejects(() => authorize(SYNC, {}), /请配置有效的 SYNC_TOKEN/);
  await assert.rejects(() => authorize(SYNC, {SYNC_TOKEN: 'too-short'}), /请配置有效的 SYNC_TOKEN/);
});

test('a read-only key cannot upload logs and does not reach the database', async () => {
  const response = await worker.fetch(new Request('https://cc-up.example.workers.dev/v1/logs', {
    method: 'POST',
    headers: {Authorization: 'Bearer ' + VIEWER, 'Content-Type': 'application/json'},
    body: '{"device_id":"a"}',
  }), env());
  assert.equal(response.status, 403);
  assert.match((await response.json()).error, /只读密钥/);
});

test('a read-only key can still query read endpoints', async () => {
  const db = {prepare: () => ({bind() { return this; }, all: async () => ({results: []}), first: async () => null})};
  const response = await worker.fetch(new Request('https://cc-up.example.workers.dev/v1/status', {
    headers: {Authorization: 'Bearer ' + PHONE},
  }), {...env(`${VIEWER},${PHONE}`), DB: db});
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {retention_days: 90, devices: [], history_range: null, applications: []});
});

test('the sync key still routes normally without a viewer key configured', async () => {
  const response = await worker.fetch(new Request('https://cc-up.example.workers.dev/v1/unknown', {
    method: 'GET',
    headers: {Authorization: 'Bearer ' + SYNC},
  }), {SYNC_TOKEN: SYNC});
  assert.equal(response.status, 404);
});
