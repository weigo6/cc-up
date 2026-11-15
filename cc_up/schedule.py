from __future__ import annotations

import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path


def normalize_times(values: list[str]) -> list[str]:
    cleaned = sorted({value.strip() for value in values if value.strip()})
    if len(cleaned) > 24 or any(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value) for value in cleaned):
        raise ValueError("定时时间请使用 HH:MM，例如 09:00, 13:00, 18:00；最多 24 个。")
    return cleaned


def task_name(device_id: str) -> str:
    import hashlib
    return "CC-Up-" + hashlib.sha256(device_id.encode()).hexdigest()[:12]


def task_xml(config_path: Path, times: list[str], user: str, executable: str | None = None) -> str:
    times = normalize_times(times)
    if not times:
        raise ValueError("请至少填写一个定时时间。")
    python = Path(executable or sys.executable)
    if python.with_name("pythonw.exe").is_file():
        python = python.with_name("pythonw.exe")
    root_dir = Path(__file__).resolve().parent.parent
    namespace = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", namespace)
    element = lambda name: "{" + namespace + "}" + name
    root = ET.Element(element("Task"), version="1.2")
    registration = ET.SubElement(root, element("RegistrationInfo"))
    ET.SubElement(registration, element("Description")).text = "CC-Up：只读采集 CC-Switch 请求日志与近期用量"
    triggers = ET.SubElement(root, element("Triggers"))
    for value in times:
        trigger = ET.SubElement(triggers, element("CalendarTrigger"))
        ET.SubElement(trigger, element("StartBoundary")).text = f"{date.today().isoformat()}T{value}:00"
        ET.SubElement(trigger, element("Enabled")).text = "true"
        daily = ET.SubElement(trigger, element("ScheduleByDay"))
        ET.SubElement(daily, element("DaysInterval")).text = "1"
    principals = ET.SubElement(root, element("Principals"))
    principal = ET.SubElement(principals, element("Principal"), id="Author")
    ET.SubElement(principal, element("UserId")).text = user
    ET.SubElement(principal, element("LogonType")).text = "InteractiveToken"
    ET.SubElement(principal, element("RunLevel")).text = "LeastPrivilege"
    settings = ET.SubElement(root, element("Settings"))
    for key, value in {"MultipleInstancesPolicy": "IgnoreNew", "DisallowStartIfOnBatteries": "false",
                       "StopIfGoingOnBatteries": "false", "StartWhenAvailable": "true",
                       "RunOnlyIfNetworkAvailable": "true", "Enabled": "true",
                       "ExecutionTimeLimit": "PT1H"}.items():
        ET.SubElement(settings, element(key)).text = value
    retry = ET.SubElement(settings, element("RestartOnFailure"))
    ET.SubElement(retry, element("Interval")).text = "PT5M"
    ET.SubElement(retry, element("Count")).text = "3"
    actions = ET.SubElement(root, element("Actions"), Context="Author")
    action = ET.SubElement(actions, element("Exec"))
    ET.SubElement(action, element("Command")).text = str(python)
    ET.SubElement(action, element("Arguments")).text = subprocess.list2cmdline([
        str(root_dir / "cc_up_launcher.py"), "sync", "--config", str(config_path.resolve())])
    ET.SubElement(action, element("WorkingDirectory")).text = str(root_dir)
    # The file is written as UTF-16 with a BOM. Do not emit a conflicting UTF-8 declaration.
    return ET.tostring(root, encoding="unicode", xml_declaration=False)


def manage_schedule(config, config_path: Path, remove=False) -> str:
    if os.name != "nt":
        raise ValueError("自动安装定时任务仅支持 Windows。")
    name = task_name(str(config_path.resolve()).casefold())
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW}
    if remove:
        command = ["schtasks.exe", "/Delete", "/TN", name, "/F"]
    else:
        user = subprocess.check_output(["whoami.exe"], text=True, **flags).strip()
        xml_path = config_path.with_name("scheduled-task.xml")
        xml_path.parent.mkdir(parents=True, exist_ok=True)
        xml_path.write_text(task_xml(config_path, config.daily_times, user), encoding="utf-16")
        command = ["schtasks.exe", "/Create", "/TN", name, "/XML", str(xml_path), "/F"]
    process = subprocess.run(command, capture_output=True, **flags)
    if process.returncode:
        import locale
        detail = (process.stderr or process.stdout).decode(locale.getpreferredencoding(False), errors="replace").strip()
        raise ValueError("Windows 定时任务操作失败：" + detail)
    return "已移除定时任务。" if remove else "已安装每日定时任务，登录 Windows 后自动运行。"
