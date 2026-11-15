from __future__ import annotations

import json
import queue
import threading
import time
import tkinter as tk
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .config import Config, load_config, save_config
from . import __version__


def run_gui(config_path: Path):
    root = tk.Tk()
    root.title(f"CC-Up · 多设备用量同步 · {__version__}")
    root.geometry("800x780")
    root.minsize(720, 640)
    root.configure(background="#f4f6f8")
    style = ttk.Style()
    if "vista" in style.theme_names():
        style.theme_use("vista")
    style.configure("TFrame", background="#f4f6f8")
    style.configure("TLabel", background="#f4f6f8", font=("Microsoft YaHei UI", 10))
    style.configure("Title.TLabel", font=("Microsoft YaHei UI", 20, "bold"), foreground="#162b39")
    style.configure("Muted.TLabel", foreground="#5b6d79", font=("Microsoft YaHei UI", 9))
    style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(12, 6))
    style.configure("TEntry", padding=5)
    try:
        config = load_config(config_path)
    except Exception as error:
        messagebox.showwarning("读取设置", str(error), parent=root)
        config = Config()
    events = queue.Queue()
    busy = False
    fields = {key: tk.StringVar(value=str(getattr(config, key))) for key in
              ("database", "endpoint", "device_id", "device_name", "token", "batch_size")}
    fields["times"] = tk.StringVar(value=", ".join(config.daily_times))
    fields["offset"] = tk.StringVar(value=f"{config.statistics_offset_minutes / 60:g}")
    status = tk.StringVar(value="就绪 · 设置窗口可随时关闭，定时同步由 Windows 负责。")

    outer = ttk.Frame(root, padding=24)
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, text="CC-Up", style="Title.TLabel").pack(anchor="w")
    ttk.Label(outer, text="CC-Switch 多设备用量同步 · 按需运行，平时不占后台内存", style="Muted.TLabel").pack(anchor="w", pady=(2, 16))
    # Reserve the action/status bar before the expanding notebook, including at high DPI.
    footer = ttk.Frame(outer, padding=(0, 16, 0, 0))
    footer.pack(side="bottom", fill="x")
    notebook = ttk.Notebook(outer)
    notebook.pack(fill="both", expand=True)
    settings_page = ttk.Frame(notebook)
    canvas = tk.Canvas(settings_page, highlightthickness=0, background="#f4f6f8")
    settings_scroll = ttk.Scrollbar(settings_page, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=settings_scroll.set)
    settings_scroll.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    settings = ttk.Frame(canvas, padding=18)
    form = canvas.create_window((0, 0), window=settings, anchor="nw")
    settings.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(form, width=event.width))
    root.bind("<MouseWheel>", lambda event: canvas.yview_scroll(-int(event.delta / 120), "units")
              if notebook.select() == str(settings_page) else None)
    overview = ttk.Frame(notebook, padding=18)
    notebook.add(settings_page, text="  连接与定时  ")
    notebook.add(overview, text="  用量与请求  ")
    settings.columnconfigure(1, weight=1)

    def entry(row, title, key, secret=False):
        ttk.Label(settings, text=title).grid(row=row, column=0, sticky="w", pady=7, padx=(0, 14))
        control = ttk.Entry(settings, textvariable=fields[key], show="●" if secret else "")
        control.grid(row=row, column=1, sticky="ew", pady=7)
        return control

    entry(0, "设备名称", "device_name")
    entry(1, "数据库路径", "database")
    ttk.Button(settings, text="浏览", command=lambda: fields["database"].set(
        filedialog.askopenfilename(parent=root, filetypes=[("SQLite", "*.db *.sqlite *.sqlite3"), ("全部文件", "*.*")]) or fields["database"].get()
    )).grid(row=1, column=2, padx=(8, 0))
    entry(2, "Worker 地址", "endpoint")
    entry(3, "同步密钥", "token", True)
    token_buttons = ttk.Frame(settings)
    token_buttons.grid(row=3, column=2, padx=(8, 0))

    def generate_token():
        import secrets
        fields["token"].set(secrets.token_urlsafe(32))
        status.set("已生成密钥。将它设为 Worker 的 SYNC_TOKEN，两台电脑使用相同值。")

    def copy_token():
        if not fields["token"].get():
            generate_token()
        root.clipboard_clear()
        root.clipboard_append(fields["token"].get())
        status.set("同步密钥已复制。两台电脑使用相同密钥，设备身份会自动生成。")

    ttk.Button(token_buttons, text="生成", width=4, command=generate_token).pack(side="left")
    ttk.Button(token_buttons, text="复制", width=4, command=copy_token).pack(side="left", padx=(4, 0))
    ttk.Label(settings, text="两台电脑使用相同同步密钥，设备身份自动生成。", style="Muted.TLabel", wraplength=390).grid(row=4, column=1, sticky="w", pady=(0, 8))
    entry(5, "每天同步时间", "times")
    ttk.Label(settings, text="按 Windows 本地时间执行，例如 09:00, 13:00, 18:00。", style="Muted.TLabel").grid(row=6, column=1, sticky="w")
    entry(7, "每批请求数", "batch_size")
    entry(8, "统计时区 UTC 偏移", "offset")
    ttk.Label(settings, text="默认 8（北京时间），支持 5.5 等偏移；各设备与 CC-Switch 应一致。", style="Muted.TLabel").grid(row=9, column=1, sticky="w")
    entry(10, "设备 ID", "device_id")
    ttk.Label(settings, text="云端请求日志保留 90 天；按日 Token 用量长期保存。\n近期统计完整覆盖；只读数据库，不读取 Agent 会话文件。", style="Muted.TLabel").grid(row=11, column=0, columnspan=3, sticky="w", pady=5)
    buttons = ttk.Frame(settings)
    buttons.grid(row=12, column=0, columnspan=3, sticky="w", pady=12)

    def current(connection=True):
        from decimal import Decimal, InvalidOperation
        try:
            offset = Decimal(fields["offset"].get()) * 60
            if not offset.is_finite() or offset != offset.to_integral_value():
                raise ValueError
        except (InvalidOperation, ValueError):
            raise ValueError("统计时区请填写小时数，例如 8、5.5 或 -3.5，精确到分钟。") from None
        updated = replace(config, database=fields["database"].get().strip(), endpoint=fields["endpoint"].get().strip().rstrip("/"),
                          device_id=fields["device_id"].get().strip(),
                          device_name=fields["device_name"].get().strip(), token=fields["token"].get().strip(),
                          batch_size=int(fields["batch_size"].get()),
                          daily_times=fields["times"].get().replace("，", ",").split(","),
                          statistics_offset_minutes=int(offset))
        updated.validate(connection=connection)
        return updated

    def save():
        nonlocal config
        config = current()
        save_config(config_path, config)
        status.set("设置已保存。修改时间后，请点击“启用 / 更新定时”。")
        return config

    def background(function, callback=None):
        nonlocal busy
        if busy:
            messagebox.showinfo("正在处理", "请等待当前操作完成。", parent=root)
            return
        busy = True
        action.configure(state="disabled")

        def work():
            try:
                result = function()
                events.put(("done", (result, callback)))
            except Exception as error:
                events.put(("error", str(error)))
        threading.Thread(target=work, daemon=True).start()

    def guarded(function):
        def invoke():
            try:
                function()
            except Exception as error:
                messagebox.showerror("操作失败", str(error), parent=root)
        return invoke

    def schedule(remove=False):
        from .schedule import manage_schedule
        selected = config if remove else save()
        background(lambda: manage_schedule(selected, config_path, remove=remove), lambda result: status.set(result))

    ttk.Button(buttons, text="保存设置", command=guarded(save)).pack(side="left", padx=(0, 8))
    ttk.Button(buttons, text="启用 / 更新定时", command=guarded(schedule)).pack(side="left", padx=(0, 8))
    ttk.Button(buttons, text="停用定时", command=guarded(lambda: schedule(True))).pack(side="left")

    advanced_widgets = [widget for widget in settings.winfo_children() if 7 <= int(widget.grid_info().get("row", -1)) <= 10]
    for widget in advanced_widgets:
        widget.grid_remove()
    advanced_open = tk.BooleanVar(value=False)

    def toggle_advanced():
        for widget in advanced_widgets:
            widget.grid() if advanced_open.get() else widget.grid_remove()

    ttk.Checkbutton(settings, text="高级设置", variable=advanced_open, command=toggle_advanced).grid(row=6, column=0, sticky="w")

    summary = tk.Text(overview, height=12, wrap="word", font=("Microsoft YaHei UI", 10), relief="flat", padx=12, pady=12)
    summary.pack(fill="both", expand=True)
    summary.insert("end", "尚未读取云端用量。\n\n填写连接设置后，点击“刷新云端用量”。\n每台设备只上传自己的用量；总量来自各设备的最新快照。")
    summary.configure(state="disabled")

    def show_usage(result):
        text = ["请求日志保留 90 天；每日 Token 和费用长期保存。", ""]
        for window in result.get("windows", []):
            totals = window["totals"]
            name = {"today": "今天", "7d": "最近 7 个自然日", "30d": "最近 30 个自然日"}.get(window["key"], window["key"])
            text.append(f"{name}：{totals['requests']:,} 次请求 · {totals['real_total']:,} Token · ${totals['cost_usd']}")
        text.append("\n设备最近上报：")
        for device in result.get("devices", []):
            stamp = device.get("computed_at")
            when = datetime.fromtimestamp(stamp).strftime("%m-%d %H:%M") if stamp else "尚无快照"
            text.append(f"  {device['device_name']}    {when}")
        if result.get("warning"):
            text.append("\n" + result["warning"])
        summary.configure(state="normal")
        summary.delete("1.0", "end")
        summary.insert("end", "\n".join(text))
        summary.configure(state="disabled")
        status.set("已刷新云端用量。")

    def refresh():
        from .transport import Client
        selected = current()
        background(lambda: Client(selected.endpoint, selected.token).request("/v1/usage"), show_usage)

    def preview():
        from .database import summarize
        selected = current(connection=False)
        background(lambda: summarize(selected.database, int(time.time()), selected.statistics_offset_minutes),
                   lambda result: show_usage({"windows": result["windows"], "devices": [], "warning": "以上为本机预览，未上传。"}))

    def logs(history=False):
        from .transport import Client
        selected = current()
        client = Client(selected.endpoint, selected.token)

        def display(result):
            from .pagination import Pages
            pages = Pages()
            dialog = tk.Toplevel(root)
            dialog.title("历史日用量 · 长期保存" if history else "云端请求日志 · 最近 90 天")
            dialog.geometry("1000x520")
            dialog.minsize(720, 360)
            # Reserve navigation before allowing the data area to expand.
            bottom = ttk.Frame(dialog, padding=10)
            bottom.pack(side="bottom", fill="x")
            page_status = tk.StringVar(value="")
            ttk.Label(bottom, textvariable=page_status).pack(side="left")
            next_button = ttk.Button(bottom, text="下一页", command=lambda: change_page(1))
            next_button.pack(side="right")
            previous_button = ttk.Button(bottom, text="上一页", command=lambda: change_page(-1))
            previous_button.pack(side="right", padx=(0, 8))
            data_area = ttk.Frame(dialog, padding=(12, 12, 12, 0))
            data_area.pack(fill="both", expand=True)
            headers = (("time", "日期", 130), ("device", "设备", 140), ("app", "请求数", 100), ("model", "真实消耗 Token", 210), ("status", "新增输入 / 输出", 200)) if history else (
                ("time", "时间", 160), ("device", "设备", 140), ("app", "应用", 100), ("model", "模型", 260), ("status", "状态", 70))
            table = ttk.Treeview(data_area, columns=("time", "device", "app", "model", "status"), show="headings")
            for key, title, width in headers:
                table.heading(key, text=title)
                table.column(key, width=width)
            scroll = ttk.Scrollbar(data_area, orient="vertical", command=table.yview)
            table.configure(yscrollcommand=scroll.set)
            scroll.pack(side="right", fill="y")
            table.pack(fill="both", expand=True)
            records = {}

            def fill(page, index=0):
                if not dialog.winfo_exists():
                    return
                pages.accept(index, page)
                records.clear()
                for item in table.get_children():
                    table.delete(item)
                for index, record in enumerate(page["records"]):
                    records[str(index)] = record
                    values = (record["day"], record.get("device_name", record["device_id"]),
                        f"{record['totals']['requests']:,}", f"{record['totals']['real_total']:,}",
                        f"{record['totals']['fresh_input']:,} / {record['totals']['output']:,}") if history else (
                        datetime.fromtimestamp(record["created_at"]).strftime("%Y-%m-%d %H:%M:%S"),
                        record.get("device_name", record["device_id"]), record.get("app_type"), record.get("model"), record.get("status_code"))
                    table.insert("", "end", iid=str(index), values=values)
                next_button.configure(state="normal" if pages.next_cursor else "disabled")
                previous_button.configure(state="normal" if pages.index else "disabled")
                ending = "仍有更多" if pages.next_cursor else "已到最后一页"
                page_status.set(f"第 {pages.index + 1} 页 · 本页 {len(records)} 条 · {ending} · 双击查看详情")

            def detail(event=None):
                selection = table.selection()
                if selection:
                    popup = tk.Toplevel(dialog)
                    popup.title("请求详情")
                    control = tk.Text(popup, width=95, height=30, wrap="word")
                    control.pack(fill="both", expand=True)
                    control.insert("end", json.dumps(records[selection[0]], ensure_ascii=False, indent=2))
                    control.configure(state="disabled")

            def change_page(delta):
                index = pages.index + delta
                path = pages.path("/v1/history" if history else "/v1/logs", index)
                background(lambda: client.request(path), lambda page: fill(page, index))
            table.bind("<Double-1>", detail)
            fill(result)
        background(lambda: client.request("/v1/history" if history else "/v1/logs"), display)

    tools = ttk.Frame(overview)
    tools.pack(fill="x", pady=(12, 0))
    for title, fn in (("刷新云端用量", refresh), ("本机预览", preview), ("查看请求日志", logs), ("历史用量", lambda: logs(True))):
        ttk.Button(tools, text=title, command=guarded(fn)).pack(side="left", padx=(0, 8))

    def sync_now():
        from .sync import synchronize
        selected = save()
        background(lambda: synchronize(selected, config_path, progress=lambda value: events.put(("progress", value))),
                   lambda result: status.set("同步完成。可切换到“用量与请求”查看结果。"))

    action = ttk.Button(footer, text="立即同步", command=guarded(sync_now))
    action.pack(side="right")
    ttk.Label(footer, textvariable=status, wraplength=530, style="Muted.TLabel").pack(side="left", fill="x", expand=True)

    def poll():
        nonlocal busy
        try:
            while True:
                kind, value = events.get_nowait()
                if kind == "progress":
                    status.set(value)
                else:
                    busy = False
                    action.configure(state="normal")
                    if kind == "error":
                        status.set("操作失败：" + value)
                        messagebox.showerror("操作失败", value, parent=root)
                    elif value[1]:
                        value[1](value[0])
        except queue.Empty:
            pass
        root.after(150, poll)

    def close():
        if busy:
            messagebox.showinfo("操作尚未完成", "请等待当前同步或查询结束后再关闭窗口。", parent=root)
        else:
            root.destroy()
    root.protocol("WM_DELETE_WINDOW", close)
    poll()
    root.mainloop()
