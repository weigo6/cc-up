"""One-off daily-usage backfill using the existing Worker snapshot protocol.

Never uploads old request logs or opens Agent session files. Historical report
sequences remain below the current snapshot so its overview cannot be replaced.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cc_up.config import default_config_path, load_config
from cc_up.database import open_database, summarize, windows
from cc_up.transport import Client


def history_start(database: str, offset: int) -> str | None:
    with open_database(database) as (connection, _):
        stamp = connection.execute('SELECT MIN(created_at) FROM proxy_request_logs').fetchone()[0]
        first = datetime.fromtimestamp(stamp, timezone(timedelta(minutes=offset))).date().isoformat() if stamp is not None else None
        columns = {row[1] for row in connection.execute('PRAGMA table_info(usage_daily_rollups)')}
        if 'date' in columns:
            rollup = connection.execute('SELECT MIN(date) FROM usage_daily_rollups').fetchone()[0]
            if rollup and (first is None or rollup < first):
                first = rollup
        return first


def backfill(config, *, apply=False, now=None, client=None, progress=print):
    config.validate()
    now = int(time.time() if now is None else now)
    zone = timezone(timedelta(minutes=config.statistics_offset_minutes))
    recent_start = datetime.fromtimestamp(windows(now, config.statistics_offset_minutes)[-1][1], zone).date()
    first = history_start(config.database, config.statistics_offset_minutes)
    if first is None or first >= recent_start.isoformat():
        progress('没有需要单独补传的历史日期。')
        return {'days': 0}
    start = datetime.fromisoformat(first).date()
    progress(f'历史补传范围：{start} 至 {recent_start - timedelta(days=1)}；仅上传日汇总。')
    if not apply:
        progress('当前为预览。加 --apply 才会写入云端。')
        return {'start': first, 'end': (recent_start - timedelta(days=1)).isoformat(), 'days': (recent_start-start).days}
    client = client or Client(config.endpoint, config.token)
    before = client.request('/v1/status')
    device = next((d for d in before['devices'] if d['device_id'] == config.device_id), None)
    if not device or not device.get('computed_at') or device['computed_at'] < int(datetime.combine(recent_start, datetime.min.time(), zone).timestamp()):
        raise ValueError('请先成功执行一次正常同步，再补传历史，确保近期快照已经存在。')
    latest = client.request('/v1/history?' + urlencode({'device_id':config.device_id}))
    recent_sequences = [row['report_seq'] for row in latest['records'] if row['day'] >= recent_start.isoformat()]
    if not recent_sequences:
        raise ValueError('云端缺少近期日用量，请先成功执行一次正常同步。')
    floor = min(recent_sequences)
    end = recent_start - timedelta(days=1)
    totals = {'days':0, 'requests':0, 'real_total':0, 'cost_usd':Decimal(0)}
    while start <= end:
        stop = min(start + timedelta(days=28), end)
        boundary = datetime.combine(stop + timedelta(days=1), datetime.min.time(), zone)
        computed = int(boundary.timestamp())
        sequence = computed * 1000
        if sequence >= floor:
            raise ValueError('历史序号无法安全低于已有近期快照，已停止补传。')
        snapshot = summarize(config.database, computed, config.statistics_offset_minutes)
        snapshot.update(device_id=config.device_id, device_name=config.device_name, report_seq=sequence)
        reply = client.request('/v1/snapshot', snapshot)
        if reply.get('stored_seq', 0) < sequence:
            raise ValueError('云端没有确认历史批次。')
        page = client.request('/v1/history?' + urlencode({'device_id':config.device_id, 'start':start.isoformat(),'end':stop.isoformat()}))
        actual = {row['day']:row for row in page['records']}
        expected = [row for row in snapshot['daily'] if start.isoformat() <= row['day'] <= stop.isoformat()]
        for row in expected:
            stored = actual.get(row['day'])
            if stored is None or stored['totals'] != row['totals']:
                raise ValueError(f"{row['day']} 云端读回校验不一致，已停止；可以安全重试。")
            for key in ('requests','real_total'):
                totals[key] += row['totals'][key]
            totals['cost_usd'] += Decimal(row['totals']['cost_usd'])
            totals['days'] += 1
        progress(f'已写入并读回校验：{start} 至 {stop}，{len(expected)} 天。')
        start = stop + timedelta(days=1)
    after = client.request('/v1/status')
    current = next(d for d in after['devices'] if d['device_id'] == config.device_id)
    if current['computed_at'] < device['computed_at']:
        raise ValueError('近期快照时间异常，请执行正常同步。')
    totals['cost_usd'] = f"{totals['cost_usd']:.8f}"
    progress('补传完成；近期快照保留。')
    return totals


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='单独补传数据库中最近 30 天之前的每日 Token 和费用；不上传旧请求。')
    parser.add_argument('--config', type=Path, default=default_config_path())
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        result = backfill(load_config(args.config), apply=args.apply)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        print('补传失败：' + str(error))
        raise SystemExit(1)
