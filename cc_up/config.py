from __future__ import annotations

import base64
import json
import os
import socket
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


def default_config_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "CC-Up" / "config.json"


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def protect_token(value: str, decrypt: bool = False) -> str:
    if not value:
        return ""
    if os.name != "nt":
        raise ValueError("此版本的凭据保护需要 Windows。")
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    raw = base64.b64decode(value, validate=True) if decrypt else value.encode("utf-8")
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    method = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    method.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    method.restype = wintypes.BOOL
    if not method(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError(ctypes.get_last_error(), "Windows 凭据保护失败；请重新填写设备密钥。")
    try:
        result = ctypes.string_at(target.data, target.size)
        return result.decode("utf-8") if decrypt else base64.b64encode(result).decode("ascii")
    finally:
        kernel.LocalFree(target.data)


@dataclass
class Config:
    database: str = field(default_factory=lambda: str(Path.home() / ".cc-switch" / "cc-switch.db"))
    endpoint: str = ""
    device_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    device_name: str = field(default_factory=socket.gethostname)
    token: str = field(default="", repr=False)
    batch_size: int = 80
    daily_times: list[str] = field(default_factory=lambda: ["09:00", "13:00", "18:00", "23:00"])
    statistics_offset_minutes: int = 480

    def validate(self, connection: bool = True) -> None:
        if not isinstance(self.database, str) or not self.database.strip():
            raise ValueError("数据库路径须为非空文本。")
        if not isinstance(self.device_id, str) or not self.device_id.strip() or len(self.device_id) > 100:
            raise ValueError("设备 ID 无效。")
        if not isinstance(self.device_name, str) or not self.device_name.strip() or len(self.device_name) > 100:
            raise ValueError("设备名称须为 1～100 个字符。")
        if type(self.batch_size) is not int or not 1 <= self.batch_size <= 100:
            raise ValueError("每批记录数须为 1～100。")
        if type(self.statistics_offset_minutes) is not int or not -720 <= self.statistics_offset_minutes <= 840:
            raise ValueError("统计时区偏移无效。")
        if not isinstance(self.daily_times, list) or any(not isinstance(value, str) for value in self.daily_times):
            raise ValueError("定时时间须为 HH:MM 文本列表。")
        from .schedule import normalize_times
        self.daily_times = normalize_times(self.daily_times)
        if connection:
            if not isinstance(self.endpoint, str) or not isinstance(self.token, str):
                raise ValueError("云端地址和同步密钥须为文本。")
            url = urlsplit(self.endpoint)
            # Accessing .port validates malformed or out-of-range ports as well.
            if url.port == 0:
                raise ValueError("云端地址端口须为 1～65535。")
            local = url.hostname in ("127.0.0.1", "localhost", "::1")
            if url.scheme != "https" and not (local and url.scheme == "http"):
                raise ValueError("云端地址须使用 HTTPS（本机开发可使用 HTTP）。")
            if not url.hostname or url.username or url.password or url.query or url.fragment or url.path.strip("/"):
                raise ValueError("请填写 Worker 的根地址，例如 https://cc-up.example.workers.dev。")
            import re
            if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", self.token):
                raise ValueError("请填写 32～128 位同步密钥，或点击“生成”创建密钥。")


def load_config(path: Path) -> Config:
    if not path.exists():
        return Config()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("配置文件须为 JSON 对象。")
    protected = value.pop("token_protected", "")
    if not isinstance(protected, str):
        raise ValueError("配置文件中的加密密钥须为文本，请重新保存设置。")
    allowed = Config.__dataclass_fields__
    config = Config(**{key: data for key, data in value.items() if key in allowed and key != "token"})
    config.token = protect_token(protected, decrypt=True)
    config.validate(connection=False)
    return config


def save_config(path: Path, config: Config) -> None:
    config.validate(connection=False)
    value = asdict(config)
    value.pop("token")
    value["token_protected"] = protect_token(config.token)
    atomic_json(path, value)
