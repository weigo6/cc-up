from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from cc_up.config import Config, load_config, save_config
from cc_up.database import open_database, read_batch, summarize, windows
from cc_up.schedule import normalize_times, task_xml
from cc_up.sync import state_path, sync_lock, synchronize
from tests.fixtures import database, insert

NOW = 1794729600 + 12 * 3600


class FakeCloud:
    def __init__(self):
        self.logs = {}
        self.snapshots = []
        self.calls = 0
        self.fail_at = None
        self.fail_snapshot = False

    def request(self, path, body):
        if path == '/v1/logs':
            self.calls += 1
            if self.calls == self.fail_at:
                raise ValueError('模拟断网')
            for row in body['records']:
                self.logs.setdefault((body['device_id'], row['request_id']), row)
            return {'accepted': len(body['records'])}
        if self.fail_snapshot:
            raise ValueError('模拟快照上传失败')
        self.snapshots.append(body)
        return {'stored_seq': body['report_seq']}


class CollectorTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.db = self.folder / 'cc-switch.db'
        database(self.db)
        self.config_path = self.folder / 'config.json'
        self.config = Config(database=str(self.db), device_id='a', endpoint='http://127.0.0.1:8787', token='A' * 43, batch_size=2)

    def row(self, rid, **values):
        insert(self.db, request_id=rid, created_at=values.pop('created_at', NOW - 10), **values)

    def totals(self, **kwargs):
        return summarize(str(self.db), NOW, 480)['windows'][0]['totals']

    def test_token_semantics_match_upstream(self):
        self.row('claude', app_type='claude', input_tokens=200, output_tokens=10, cache_read_tokens=5000)
        self.row('legacy', input_tokens=1000, output_tokens=100, cache_read_tokens=600)
        self.row('total', input_tokens=1000, output_tokens=100, cache_read_tokens=300, cache_creation_tokens=200, input_token_semantics=1)
        self.row('fresh', input_tokens=500, output_tokens=100, cache_read_tokens=300, cache_creation_tokens=200, input_token_semantics=2)
        result = self.totals()
        self.assertEqual(result['fresh_input'], 1600)
        self.assertEqual(result['real_total'], 8510)
        self.row('malformed', input_tokens=100, cache_read_tokens=999, input_token_semantics=1)
        self.assertEqual(self.totals()['fresh_input'], 1700)

    def test_dedup_codex_alias_and_missing_cache_write(self):
        self.row('proxy', model='actual-model', request_model='client-alias', input_tokens=1000,
                 output_tokens=100, cache_read_tokens=500, cache_creation_tokens=200, input_token_semantics=1)
        self.row('session', model='client-alias', input_tokens=1000, output_tokens=100,
                 cache_read_tokens=500, data_source='codex_session')
        self.assertEqual(self.totals()['requests'], 1)
        self.assertEqual(self.totals()['fresh_input'], 300)

    def test_costs_use_stored_billing_and_multiplier_exactly_once(self):
        self.row('proxy-billed', model='response-model', request_model='client-alias',
                 pricing_model='billing-model', input_tokens=1000, output_tokens=100,
                 cache_read_tokens=600, input_token_semantics=1,
                 input_cost_usd='0.001', output_cost_usd='0.001', cache_read_cost_usd='0.001',
                 cache_creation_cost_usd='0', cost_multiplier='3.0', total_cost_usd='0.009')
        self.row('duplicate-session', model='client-alias', input_tokens=1000, output_tokens=100,
                 cache_read_tokens=600, data_source='codex_session', total_cost_usd='0.888')
        result = summarize(str(self.db), NOW, 480)
        self.assertEqual(result['windows'][0]['totals']['cost_usd'], '0.00900000')
        self.assertEqual(result['daily'][-1]['totals']['cost_usd'], '0.00900000')
        self.assertEqual(result['windows'][0]['totals']['fresh_input'], 400)
        cloud = FakeCloud()
        synchronize(self.config, self.config_path, client=cloud, now=NOW)
        uploaded = cloud.logs[('a', 'proxy-billed')]
        self.assertEqual(uploaded['total_cost_usd'], '0.009')
        self.assertEqual(uploaded['cost_multiplier'], '3.0')
        self.assertEqual(uploaded['pricing_model'], 'billing-model')
        self.assertEqual(uploaded['input_cost_usd'], '0.001')

    def test_missing_prices_remain_zero_and_window_costs_sum_daily_values(self):
        self.row('no-price', input_tokens=1000, total_cost_usd='0')
        self.row('yesterday', created_at=NOW - 86400, input_tokens=50, total_cost_usd='0.12345678')
        result = summarize(str(self.db), NOW, 480)
        self.assertEqual(result['windows'][0]['totals']['cost_usd'], '0.00000000')
        self.assertEqual(result['windows'][1]['totals']['cost_usd'], '0.12345678')
        from decimal import Decimal
        self.assertEqual(sum(Decimal(bucket['totals']['cost_usd']) for bucket in result['daily']),
                         Decimal(result['windows'][2]['totals']['cost_usd']))

    def test_dedup_looks_outside_statistical_window(self):
        midnight = windows(NOW, 480)[0][1]
        self.row('proxy', created_at=midnight - 100, app_type='claude-desktop', input_tokens=200)
        self.row('session', created_at=midnight + 10, app_type='claude', input_tokens=200, data_source='session_log')
        self.assertEqual(self.totals()['requests'], 0)

    def test_failed_proxy_does_not_hide_session_and_desktop_folds(self):
        self.row('failed', app_type='claude-desktop', status_code=500, input_tokens=100)
        self.row('session', app_type='claude', data_source='session_log', input_tokens=100)
        result = summarize(str(self.db), NOW, 480)['windows'][0]
        self.assertEqual(result['totals']['requests'], 2)
        self.assertEqual(result['totals']['successes'], 1)
        self.assertEqual(len(result['by_app']), 1)
        self.assertEqual(result['by_app'][0]['app_type'], 'claude')

    def test_read_only_and_small_batches(self):
        for index in range(8):
            self.row(f'r{index}', error_message='完整错误信息', duration_ms=987)
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        with open_database(str(self.db)) as (connection, _):
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute('DELETE FROM proxy_request_logs')
        rows = read_batch(str(self.db), NOW - 100, NOW, None, 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['duration_ms'], 987)
        self.totals()
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)

    def test_same_second_replay_with_lower_request_id(self):
        self.row('z', created_at=NOW)
        cloud = FakeCloud()
        synchronize(self.config, self.config_path, client=cloud, now=NOW)
        self.row('a', created_at=NOW)
        synchronize(self.config, self.config_path, client=cloud, now=NOW + 1)
        self.assertEqual({key[1] for key in cloud.logs}, {'a', 'z'})
        self.assertEqual(cloud.snapshots[-1]['windows'][0]['totals']['requests'], 2)

    def test_network_failure_resumes_after_last_acknowledged_batch(self):
        for index in range(6):
            self.row(str(index), created_at=NOW - 10 + index)
        cloud = FakeCloud()
        cloud.fail_at = 2
        with self.assertRaisesRegex(ValueError, '断网'):
            synchronize(self.config, self.config_path, client=cloud, now=NOW)
        state = json.loads(state_path(self.config_path).read_text(encoding='utf-8'))
        self.assertEqual(state['cursor_second'], NOW - 9)
        synchronize(self.config, self.config_path, client=cloud, now=NOW + 1)
        self.assertEqual(len(cloud.logs), 6)

    def test_snapshot_failure_does_not_lose_logs_and_recovers(self):
        self.row('request')
        cloud = FakeCloud()
        cloud.fail_snapshot = True
        with self.assertRaises(ValueError):
            synchronize(self.config, self.config_path, client=cloud, now=NOW)
        cloud.fail_snapshot = False
        state = synchronize(self.config, self.config_path, client=cloud, now=NOW + 10)
        self.assertEqual(len(cloud.logs), 1)
        self.assertEqual(state['last_success'], NOW + 10)

    def test_old_agent_backfill_is_deliberately_not_uploaded(self):
        cloud = FakeCloud()
        synchronize(self.config, self.config_path, client=cloud, now=NOW)
        self.row('late-old-session', created_at=NOW - 86400, data_source='codex_session', input_tokens=100)
        synchronize(self.config, self.config_path, client=cloud, now=NOW + 10)
        self.assertEqual(len(cloud.logs), 0)
        self.assertEqual(cloud.snapshots[-1]['windows'][1]['totals']['requests'], 1)

    def test_destination_change_gets_its_own_cursor(self):
        self.row('request')
        synchronize(self.config, self.config_path, client=FakeCloud(), now=NOW)
        self.config.endpoint = 'http://localhost:1234'
        cloud = FakeCloud()
        synchronize(self.config, self.config_path, client=cloud, now=NOW + 20)
        self.assertEqual(len(cloud.logs), 1)

    def test_full_days_include_normalized_rollups(self):
        stamp = windows(NOW, 480)[1][1]
        from datetime import datetime, timedelta, timezone
        day = datetime.fromtimestamp(stamp, timezone(timedelta(hours=8))).date().isoformat()
        connection = sqlite3.connect(self.db)
        try:
            connection.execute('INSERT INTO usage_daily_rollups(date,app_type,request_count,success_count,input_tokens,cache_read_tokens) VALUES(?,?,?,?,?,?)',
                               (day, 'codex', 10, 10, 500, 600))
            connection.commit()
        finally:
            connection.close()
        result = summarize(str(self.db), NOW, 480)['windows']
        self.assertEqual(result[0]['totals']['requests'], 0)
        self.assertEqual(result[1]['totals']['requests'], 10)
        self.assertEqual(result[1]['totals']['fresh_input'], 500)

    def test_concurrent_manual_and_scheduled_runs_are_excluded(self):
        lock = state_path(self.config_path).with_suffix('.lock')
        with sync_lock(lock):
            with self.assertRaisesRegex(ValueError, '已有同步'):
                synchronize(self.config, self.config_path, client=FakeCloud(), now=NOW)

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_credentials_are_encrypted_and_round_trip(self):
        save_config(self.config_path, self.config)
        raw = self.config_path.read_text(encoding='utf-8')
        self.assertNotIn(self.config.token, raw)
        self.assertEqual(load_config(self.config_path).token, self.config.token)

    def test_windows_task_uses_current_user_without_password_and_safe_paths(self):
        path = self.folder / '目录 & 空格' / 'config.json'
        xml = task_xml(path, ['23:00', '09:00', '09:00'], 'DOMAIN\\user', executable='C:\\Program Files\\Python\\python.exe')
        root = ET.fromstring(xml)
        ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
        self.assertEqual(len(root.findall('t:Triggers/t:CalendarTrigger', ns)), 2)
        self.assertIn(str(path.resolve()).casefold(), root.find('.//t:Arguments', ns).text.casefold())
        self.assertEqual(root.find('.//t:LogonType', ns).text, 'InteractiveToken')
        self.assertEqual(root.find('.//t:MultipleInstancesPolicy', ns).text, 'IgnoreNew')
        with self.assertRaises(ValueError):
            normalize_times(['24:00'])


if __name__ == '__main__':
    unittest.main()
