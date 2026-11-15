from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .rules import RULE_VERSION, effective_filter, fresh_input

REQUIRED = {"request_id", "created_at", "app_type", "model", "provider_id", "input_tokens",
            "output_tokens", "cache_read_tokens", "cache_creation_tokens", "status_code"}
COMPAT_COLUMNS = {"data_source": "'proxy'", "input_token_semantics": "0", "pricing_model": "NULL",
                  "request_model": "NULL", "total_cost_usd": "'0'"}


@contextmanager
def open_database(path: str):
    location = Path(path).expanduser().resolve()
    if not location.is_file():
        raise ValueError(f"找不到 CC-Switch 数据库：{location}")
    connection = sqlite3.connect(location.as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA cache_size=-512")
        connection.execute("PRAGMA mmap_size=0")
        connection.execute("PRAGMA temp_store=FILE")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(proxy_request_logs)")}
        if not REQUIRED.issubset(columns):
            raise ValueError("数据库缺少请求统计字段，请检查路径或升级 CC-Switch。")
        yield connection, columns
    finally:
        connection.close()


def source_identity(path: str) -> str:
    # Detect path changes and replacement, without treating ordinary writes as replacement.
    location = Path(path).expanduser().resolve()
    info = location.stat()
    return f"{str(location).casefold()}:{info.st_dev}:{info.st_ino}"


def read_batch(path: str, start: int, end: int, after: tuple[int, str] | None, size: int) -> list[dict]:
    with open_database(path) as (connection, columns):
        where = "created_at >= ? AND created_at <= ?"
        arguments: list = [start, end]
        if after is not None:
            where += " AND (created_at, request_id) > (?, ?)"
            arguments.extend(after)
        arguments.append(size)
        rows = connection.execute(
            f"SELECT * FROM proxy_request_logs WHERE {where} ORDER BY created_at, request_id LIMIT ?",
            arguments,
        )
        return [dict(row) for row in rows]


def _view(connection, columns):
    additions = [f"{default} AS {key}" for key, default in COMPAT_COLUMNS.items() if key not in columns]
    projection = "*" + (", " + ", ".join(additions) if additions else "")
    # NOT MATERIALIZED preserves upstream indexes and avoids copying the log table
    # into a temporary structure when the dedup subquery references it a second time.
    return f"WITH logs AS NOT MATERIALIZED (SELECT {projection} FROM proxy_request_logs)"


def windows(now: int, offset_minutes: int) -> list[tuple[str, int, int]]:
    zone = timezone(timedelta(minutes=offset_minutes))
    midnight = datetime.fromtimestamp(now, zone).replace(hour=0, minute=0, second=0, microsecond=0)
    return [(key, int((midnight - timedelta(days=days)).timestamp()), now)
            for key, days in (("today", 0), ("7d", 6), ("30d", 29))]


def summarize(path: str, now: int, offset_minutes: int) -> dict:
    result = {"rule_version": RULE_VERSION, "computed_at": now,
              "offset_minutes": offset_minutes, "windows": [], "daily": []}
    ranges = windows(now, offset_minutes)
    zone = timezone(timedelta(minutes=offset_minutes))
    first_day = datetime.fromtimestamp(ranges[-1][1], zone).date()
    today = datetime.fromtimestamp(now, zone).date()
    daily_groups = {(first_day + timedelta(days=index)).isoformat(): {} for index in range(30)}

    def merge(groups, row):
        app = row["app_type"]
        if app not in groups:
            groups[app] = {"app_type": app, **{name: 0 for name in
                ("requests", "successes", "fresh_input", "output", "cache_read", "cache_write")}, "cost_usd": Decimal(0)}
        for name in ("requests", "successes", "fresh_input", "output", "cache_read", "cache_write"):
            groups[app][name] += int(row[name] or 0)
        groups[app]["cost_usd"] += Decimal(str(row["cost_usd"] or 0))

    def finish(groups):
        counts = ("requests", "successes", "fresh_input", "output", "cache_read", "cache_write")
        totals = {name: sum(group[name] for group in groups.values()) for name in counts}
        totals["cost_usd"] = format(sum((Decimal(str(g["cost_usd"])) for g in groups.values()), Decimal(0)), ".8f")
        totals["real_total"] = totals["fresh_input"] + totals["output"] + totals["cache_read"] + totals["cache_write"]
        items = [{**g, "cost_usd": format(Decimal(str(g["cost_usd"])), ".8f")} for g in groups.values()]
        return {"totals": totals, "by_app": items}

    with open_database(path) as (connection, columns):
        deadline = time.monotonic() + 120
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 20_000)
        connection.execute("BEGIN")
        cte = _view(connection, columns)
        predicate = effective_filter().replace("FROM proxy_request_logs p", "FROM logs p")
        fresh = fresh_input("l")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rollup_columns = {row[1] for row in connection.execute("PRAGMA table_info(usage_daily_rollups)")}
        has_rollups = "usage_daily_rollups" in tables and {"date", "app_type", "request_count", "success_count",
            "input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens", "total_cost_usd"}.issubset(rollup_columns)
        query = f"""{cte} SELECT date(l.created_at,'unixepoch',?) AS day,
                CASE WHEN l.app_type='claude-desktop' THEN 'claude' ELSE l.app_type END AS app_type,
                COUNT(*) AS requests,
                SUM(CASE WHEN l.status_code >= 200 AND l.status_code < 300 THEN 1 ELSE 0 END) AS successes,
                SUM({fresh}) AS fresh_input, SUM(l.output_tokens) AS output,
                SUM(l.cache_read_tokens) AS cache_read, SUM(l.cache_creation_tokens) AS cache_write,
                SUM(CAST(l.total_cost_usd AS REAL)) AS cost_usd
                FROM logs l WHERE l.created_at >= ? AND l.created_at <= ? AND {predicate}
                GROUP BY 1,2"""
        for row in connection.execute(query, (f"{offset_minutes:+} minutes", ranges[-1][1], now)):
            merge(daily_groups[row["day"]], row)
        if has_rollups:
            # Like upstream, only full days are eligible. Today is incomplete.
            rcolumns = "*" + (", 0 AS input_token_semantics" if "input_token_semantics" not in rollup_columns else "")
            rq = f"""WITH r AS (SELECT {rcolumns} FROM usage_daily_rollups)
                    SELECT date AS day, CASE WHEN app_type='claude-desktop' THEN 'claude' ELSE app_type END AS app_type,
                    SUM(request_count) AS requests, SUM(success_count) AS successes,
                    SUM({fresh_input('r')}) AS fresh_input, SUM(output_tokens) AS output,
                    SUM(cache_read_tokens) AS cache_read, SUM(cache_creation_tokens) AS cache_write,
                    SUM(CAST(total_cost_usd AS REAL)) AS cost_usd FROM r
                    WHERE date >= ? AND date < ? GROUP BY 1,2"""
            for row in connection.execute(rq, (first_day.isoformat(), today.isoformat())):
                merge(daily_groups[row["day"]], row)
    for day, groups in daily_groups.items():
        result["daily"].append({"day": day, **finish(groups)})
    for key, start, end in ranges:
        groups = {}
        start_day = datetime.fromtimestamp(start, zone).date().isoformat()
        for bucket in result["daily"]:
            if bucket["day"] >= start_day:
                for group in bucket["by_app"]:
                    merge(groups, group)
        result["windows"].append({"key": key, "start": start, "end": end, **finish(groups)})
    return result
