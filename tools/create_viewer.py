"""Generate a read-only viewer key; the same plaintext goes to the Worker and the web page."""
from __future__ import annotations

import argparse
import re
import secrets

TOKEN = re.compile(r"[A-Za-z0-9_-]{32,128}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成网页使用的只读密钥；Worker 与网页填同一串明文。")
    parser.add_argument("--token", help="使用已有密钥；默认随机生成。")
    options = parser.parse_args(argv)

    token = options.token or secrets.token_urlsafe(32)
    if not TOKEN.fullmatch(token):
        raise SystemExit("密钥须为 32～128 位字母、数字、下划线或短横线。")

    print("只读密钥（Worker 的 VIEWER_TOKENS 与网页 / Netlify 的 CC_UP_TOKEN 填同一串）：")
    print(token)
    print()
    print("已经配过其它只读密钥时，用英文逗号接到 VIEWER_TOKENS 后面；只有这一把就只填这一串。")
    print("只读密钥只能查询，POST 上传会返回 403；采集器仍使用 SYNC_TOKEN。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
