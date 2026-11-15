from __future__ import annotations

import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from . import __version__


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("云端地址发生重定向，请直接填写正确的 HTTPS Worker 地址。")


class Client:
    def __init__(self, endpoint: str, token: str):
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        # A system-wide proxy must never receive loopback development traffic.
        handlers = [NoRedirect()]
        if urlsplit(endpoint).hostname in ("localhost", "127.0.0.1", "::1"):
            handlers.append(ProxyHandler({}))
        self.opener = build_opener(*handlers)

    def request(self, path: str, body: dict | None = None) -> dict:
        encoded = None if body is None else json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if encoded is not None and len(encoded) > 512 * 1024:
            raise ValueError("上传批次超过 512 KB，请在设置中减小每批记录数。")
        request = Request(self.endpoint + path, data=encoded, headers={
            "Authorization": "Bearer " + self.token, "Content-Type": "application/json", "User-Agent": "CC-Up/" + __version__})
        for attempt in range(3):
            try:
                with self.opener.open(request, timeout=30) as response:
                    raw = response.read(2 * 1024 * 1024 + 1)
                    if len(raw) > 2 * 1024 * 1024:
                        raise ValueError("云端返回内容过大。")
                    return json.loads(raw)
            except HTTPError as error:
                error.close()
                if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    # Never surface server/proxy pages that might echo credentials.
                    messages = {401: "同步密钥无效", 403: "设备无权访问", 413: "批次过大，请减小每批记录数",
                                409: "统计口径或时间范围不一致", 429: "云端请求过多或免费额度已用尽"}
                    raise ValueError(f"云端返回 {error.code}：{messages.get(error.code, '请检查服务端配置或稍后重试')}") from None
            except (URLError, TimeoutError, ConnectionError):
                if attempt == 2:
                    raise ValueError("无法连接云端，请检查网络与 Worker 地址。") from None
            time.sleep(2 ** attempt)
        raise RuntimeError("unreachable")
