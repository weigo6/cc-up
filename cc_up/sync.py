from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from .config import Config, atomic_json
from .database import read_batch, source_identity, summarize
from .transport import Client


@contextmanager
def sync_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("已有同步正在运行，请稍后再试。") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def state_path(config_path: Path) -> Path:
    return config_path.with_name(config_path.stem + ".state.json")


def synchronize(config: Config, config_path: Path, progress=lambda message: None, client=None, now=None) -> dict:
    config.validate()
    client = client or Client(config.endpoint, config.token)
    path = state_path(config_path)
    with sync_lock(path.with_suffix(".lock")):
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        identity = source_identity(config.database)
        # Reset only when the destination/device/source changes. Never carry another
        # cloud's cursor over, or a new destination would silently lose its history.
        scope = [identity, config.endpoint.rstrip("/"), config.device_id]
        if state.get("scope") != scope:
            state = {"scope": scope, "sequence": 0}
        cutoff = int(time.time() if now is None else now)
        start = max(int(state.get("cursor_second", 0)), cutoff - 90 * 86400)
        if start > cutoff:
            raise ValueError("系统时间早于上次同步时间，请先校准 Windows 时间。")
        after = None
        uploaded = 0
        progress("正在上传新增请求日志…")
        try:
            while True:
                rows = read_batch(config.database, start, cutoff, after, config.batch_size)
                if not rows:
                    break
                reply = client.request("/v1/logs", {"device_id": config.device_id,
                    "device_name": config.device_name, "records": rows})
                if reply.get("accepted") != len(rows):
                    raise ValueError("云端未完整确认这一批记录，已保留进度供下次重试。")
                after = (rows[-1]["created_at"], rows[-1]["request_id"])
                state["cursor_second"] = after[0]
                atomic_json(path, state)
                uploaded += len(rows)
                progress(f"已确认 {uploaded} 条记录（含同秒幂等重传）…")
            # Every new run replays the complete final second, even after a crash.
            state["cursor_second"] = cutoff
            atomic_json(path, state)
            progress("正在计算近期用量…")
            snapshot = summarize(config.database, cutoff, config.statistics_offset_minutes)
            sequence = max(int(state.get("sequence", 0)) + 1, time.time_ns() // 1_000_000)
            state["sequence"] = sequence
            atomic_json(path, state)
            snapshot.update(device_id=config.device_id, device_name=config.device_name, report_seq=sequence)
            reply = client.request("/v1/snapshot", snapshot)
            if reply.get("stored_seq", 0) < sequence:
                raise ValueError("云端未确认最新用量快照，请重新同步。")
            state.update(last_success=cutoff, last_error="", last_uploaded=uploaded,
                         windows=snapshot["windows"])
            atomic_json(path, state)
            progress(f"同步完成：已确认 {uploaded} 条记录，近期统计已覆盖。")
            return state
        except Exception as error:
            state["last_error"] = str(error)
            atomic_json(path, state)
            raise
