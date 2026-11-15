"""Bounded-memory benchmark; creates only synthetic records in a temporary folder."""
from __future__ import annotations

import argparse
import ctypes
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cc_up.config import Config
from cc_up.sync import synchronize
from tests.fixtures import database


def peak_working_set():
    from ctypes import wintypes
    class Memory(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
                'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
    memory = Memory()
    memory.cb = ctypes.sizeof(memory)
    kernel = ctypes.WinDLL('kernel32')
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL('psapi')
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(memory), memory.cb):
        raise ctypes.WinError()
    return round(memory.PeakWorkingSetSize / 1024 / 1024, 2)


class Sink:
    def request(self, path, body):
        # Encode each batch to include real transport-buffer allocation, without network variance.
        json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()
        return {'accepted': len(body['records'])} if path.endswith('logs') else {'stored_seq': body['report_seq']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=100_000)
    options = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / 'source.db'
        database(source)
        now = int(time.time())
        connection = sqlite3.connect(source)
        connection.executemany('INSERT INTO proxy_request_logs(request_id,created_at,input_tokens,output_tokens,cache_read_tokens,input_token_semantics) VALUES(?,?,?,?,?,?)',
            ((f'request-{index:09}', now - 86400 + index // 10, 1000, 100, 600, 1) for index in range(options.rows)))
        connection.commit()
        connection.close()
        config = Config(database=str(source), endpoint='http://127.0.0.1:8787', token='A' * 43)
        started = time.perf_counter()
        state = synchronize(config, Path(directory) / 'config.json', client=Sink(), now=now)
        print(json.dumps({'records': options.rows, 'confirmed_records': state['last_uploaded'],
            'batch_size': config.batch_size, 'elapsed_seconds': round(time.perf_counter() - started, 2),
            'peak_working_set_mb': peak_working_set(), 'tkinter_loaded': 'tkinter' in sys.modules}, indent=2))
