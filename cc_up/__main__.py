from __future__ import annotations

import argparse
import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import default_config_path, load_config


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CC-Up：低内存 CC-Switch 多设备用量同步")
    parser.add_argument("command", nargs="?", choices=("settings", "sync", "preview", "status", "install-schedule", "remove-schedule"), default="settings")
    parser.add_argument("--config", type=Path, default=default_config_path())
    options = parser.parse_args(argv)
    if options.command == "settings":
        from .gui import run_gui
        run_gui(options.config)
        return 0
    options.config.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("cc_up")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(options.config.parent / "sync.log", maxBytes=128 * 1024, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)

    def report(message):
        logger.info(message)
        if sys.stdout:
            print(message, flush=True)

    try:
        config = load_config(options.config)
        if not options.config.exists() and options.command != "preview":
            raise ValueError("请先双击“CC-Up.pyw”，保存云端地址和设备密钥。")
        if options.command == "preview":
            import time
            from .database import summarize
            result = summarize(config.database, int(time.time()), config.statistics_offset_minutes)
            if sys.stdout:
                print(json.dumps(result, ensure_ascii=False, indent=2))
        elif options.command == "sync":
            from .sync import synchronize
            synchronize(config, options.config, progress=report)
        elif options.command == "status":
            from .transport import Client
            config.validate()
            result = Client(config.endpoint, config.token).request("/v1/status")
            if sys.stdout:
                print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            from .schedule import manage_schedule
            report(manage_schedule(config, options.config, remove=options.command == "remove-schedule"))
        return 0
    except Exception as error:
        report("操作失败：" + str(error))
        return 1
    finally:
        logger.removeHandler(handler)
        handler.close()


if __name__ == "__main__":
    raise SystemExit(main())
