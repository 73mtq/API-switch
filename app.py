"""API Switch —— CC Switch 模型导入桌面版（tkinter，零第三方依赖）。

双击运行：拉取 /v1/models 列表 → 勾选要接入的模型 → 写入 CC Switch。
"""

from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

import ccs_models as core

APP_BG = "#f5f5f7"
CARD = "#ffffff"
BORDER = "#e5e5ea"
LINE = "#d2d2d7"
TEXT = "#1d1d1f"
SEC = "#6e6e73"
TER = "#8e8e93"
ACC = "#007aff"
ACC_H = "#0a84ff"
PICK = "#f2f7ff"
SEL = "#e6f1ff"
GREEN = "#248a3d"
RED = "#d70015"
HOVER = "#f2f2f7"

PAD = 18
DEFAULT_CONTEXT = 1000000
DEFAULT_OUTPUT = 131072


def _as_tokens(text: str, fallback: int) -> int:
    raw = (text or "").strip().lower().replace(",", "").replace("_", "")
    try:
        if raw.endswith("k"):
            n = int(float(raw[:-1]) * 1000)
        elif raw.endswith("m"):
            n = int(float(raw[:-1]) * 1_000_000)
        else:
            n = int(float(raw))
    except Exception:
        return fallback
    return n if n > 0 else fallback


def _fmt_ctx(n: int) -> str:
    n = int(n or 0)
    if not n:
        return ""
    if n >= 1_000_000:
        return f"{n / 1_000_000:g}M"
    if n >= 1000:
        return f"{n / 1000:g}K"
    return str(n)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("API Switch")
        h = min(980, max(680, self.winfo_screenheight() - 110))
        w = min(1020, max(900, self.winfo_screenwidth() - 80))
        self.geometry(f"{w}x{h}+{(self.winfo_screenwidth() - w) // 2}+{max(0, (self.winfo_screenheight() - h) // 3)}")
        self.minsize(900, 560)
        self.configure(bg=APP_BG)

        self.models: list[core.Model] = []
        self.picked: set[int] = set()
        self.visible: list[int] = []
        self.provider_ids: list[str] = []
        self.last_backup: str | None = None
        self.q: queue.Queue = queue.Queue()

        self._fonts()
        self._style()
        self._build()
        self.after(120, self._pump)
        self.after(300, self._refresh_status)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # ---------- 基础样式 ----------

    def _fonts(self) -> None:
        fams = set(tkfont.families())
        name = next(
            (f for f in ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI") if f in fams),
            "TkDefaultFont",
        )
        self.F_TITLE = (name, 15, "bold")
        self.F_H3 = (name, 10, "bold")
        self.F_BODY = (name, 10)
        self.F_SM = (name, 9)

    def _style(self) -> None:
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except Exception:
            pass

        self.option_add("*TCombobox*Listbox.background", CARD)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", ACC)
        self.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        self.option_add("*TCombobox*Listbox.font", self.F_BODY)

        s.configure(
            ".", background=CARD, foreground=TEXT, fieldbackground=CARD,
            bordercolor=LINE, lightcolor=CARD, darkcolor=CARD, troughcolor=APP_BG,
        )
        s.configure("TFrame", background=CARD)
        s.configure("TLabel", background=CARD, foreground=TEXT, font=self.F_BODY)
        s.configure("Small.TLabel", foreground=SEC, font=self.F_SM)
        s.configure("Head.TLabel", font=self.F_H3)

        s.configure(
            "TButton", background=CARD, foreground=TEXT, bordercolor=LINE, borderwidth=1,
            relief="flat", padding=(12, 6), font=self.F_BODY,
        )
        s.map(
            "TButton",
            background=[("disabled", "#fafafa"), ("pressed", "#e8e8ed"), ("active", HOVER)],
            foreground=[("disabled", TER)],
            bordercolor=[("disabled", BORDER)],
        )
        s.configure("Primary.TButton", background=ACC, foreground="#ffffff", bordercolor=ACC, padding=(14, 6))
        s.map(
            "Primary.TButton",
            background=[("disabled", "#c7c7cc"), ("pressed", "#0060df"), ("active", ACC_H)],
            foreground=[("disabled", "#ffffff")],
            bordercolor=[("disabled", "#c7c7cc")],
        )
        s.configure("Danger.TButton", foreground=RED, bordercolor="#e3c8c7")
        s.map("Danger.TButton", background=[("active", "#fff5f4")])

        s.configure(
            "TEntry", fieldbackground=CARD, foreground=TEXT, bordercolor=LINE, borderwidth=1,
            relief="flat", padding=(8, 6), insertcolor=TEXT,
        )
        s.map("TEntry", bordercolor=[("focus", ACC), ("hover", "#c7c7cc")])
        s.configure("Ghost.TEntry", foreground=TER)

        s.configure("TCombobox", fieldbackground=CARD, foreground=TEXT, bordercolor=LINE, arrowcolor=SEC, padding=(8, 6))
        s.map("TCombobox", bordercolor=[("focus", ACC)], arrowcolor=[("active", TEXT)])

        s.configure("TCheckbutton", background=CARD, foreground=TEXT, padding=(2, 4), font=self.F_SM)
        s.configure("TRadiobutton", background=CARD, foreground=TEXT, padding=(2, 4), font=self.F_SM)

        s.configure(
            "Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT, borderwidth=0,
            relief="flat", rowheight=32, font=self.F_BODY,
        )
        s.configure("Treeview.Heading", background="#fafafa", foreground=SEC, font=self.F_SM,
                    bordercolor=BORDER, relief="flat")
        s.map("Treeview", background=[("selected", SEL)], foreground=[("selected", TEXT)])

        s.configure("TScrollbar", background="#d8d8dd", troughcolor=CARD, bordercolor=CARD,
                    arrowcolor=SEC, arrowsize=11, relief="flat", borderwidth=0)
        s.map("TScrollbar", background=[("active", "#b9b9c0")])

        s.configure("TProgressbar", background=ACC, troughcolor="#ececed", bordercolor="#ececed", thickness=3)

    # ---------- 布局小工具 ----------

    def _card(self, parent, title: str, subtitle: str = "", expand: bool = False):
        outer = tk.Frame(parent, bg=APP_BG)
        outer.pack(fill="both" if expand else "x", expand=expand, pady=(0, 10))
        box = tk.Frame(outer, bg=CARD, highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER)
        box.pack(fill="both", expand=True)
        head = tk.Frame(box, bg=CARD)
        head.pack(fill="x", padx=PAD, pady=(12, 7))
        tk.Label(head, text=title, font=self.F_H3, bg=CARD, fg=TEXT).pack(side="left")
        if subtitle:
            tk.Label(head, text=subtitle, font=self.F_SM, bg=CARD, fg=SEC).pack(side="left", padx=(10, 0))
        body = tk.Frame(box, bg=CARD)
        body.pack(fill="both", expand=True, padx=PAD, pady=(0, 13))
        return box, head, body

    def _field(self, parent, text: str, width: int = 8) -> None:
        tk.Label(parent, text=text, font=self.F_SM, bg=CARD, fg=SEC,
                 width=width, anchor="e").pack(side="left", padx=(0, 8))

    def _divider(self, parent) -> None:
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=9)

    def _center(self, win: tk.Toplevel, w: int, h: int) -> None:
        win.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - w) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - h) // 2)
        win.geometry(f"{w}x{h}+{x}+{y}")

    # ---------- 界面 ----------

    def _build(self) -> None:
        self._build_header()

        shell = tk.Frame(self, bg=APP_BG)
        shell.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(shell, bg=APP_BG, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb = ttk.Scrollbar(shell, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)

        page = tk.Frame(self.canvas, bg=APP_BG)
        self.page_id = self.canvas.create_window((0, 0), window=page, anchor="nw")
        body = tk.Frame(page, bg=APP_BG)
        body.pack(fill="both", expand=True, padx=PAD, pady=(14, 16))

        self._build_conn(body)
        self._build_models(body)
        self._build_target(body)
        self._build_log(body)
        self.sync_mode()

        page.bind("<Configure>", lambda _e: self.after_idle(self._sync_scroll))
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.bind_all("<MouseWheel>", self._on_wheel)

    def _on_canvas_resize(self, event) -> None:
        self.canvas.itemconfigure(self.page_id, width=event.width)
        self.after_idle(self._sync_scroll)

    def _sync_scroll(self) -> None:
        bbox = self.canvas.bbox("all")
        need = bool(bbox) and (bbox[3] - bbox[1]) > self.canvas.winfo_height() + 2
        if need and not self.vsb.winfo_ismapped():
            self.vsb.pack(side="right", fill="y")
        elif not need and self.vsb.winfo_ismapped():
            self.vsb.pack_forget()
        if bbox:
            self.canvas.configure(scrollregion=bbox)

    @staticmethod
    def _scrollable(widget) -> bool:
        try:
            first, last = widget.yview()
        except Exception:
            return False
        return first > 0.0 or last < 1.0

    def _on_wheel(self, event) -> None:
        step = int(-1 * (event.delta / 120)) or (-1 if event.delta > 0 else 1)
        widget = event.widget
        while widget is not None:
            if widget is self.tree or widget is self.log:
                if self._scrollable(widget):
                    return  # 让列表 / 日志自己滚
                break
            widget = getattr(widget, "master", None)
        if not self.vsb.winfo_ismapped():
            return
        self.canvas.yview_scroll(step, "units")

    def _build_header(self) -> None:
        bar = tk.Frame(self, bg=CARD)
        bar.pack(fill="x")
        inner = tk.Frame(bar, bg=CARD)
        inner.pack(fill="x", padx=PAD, pady=11)
        tk.Label(inner, text="API Switch", font=self.F_TITLE, bg=CARD, fg=TEXT).pack(side="left")
        tk.Label(inner, text="CC Switch 模型导入", font=self.F_SM, bg=CARD, fg=SEC).pack(
            side="left", padx=(10, 0), pady=(3, 0), anchor="s"
        )
        self.status = tk.Label(inner, text="● 检查中…", font=self.F_SM, bg=CARD, fg=SEC)
        self.status.pack(side="right", pady=(4, 0))
        tk.Label(inner, text="只发送 GET /v1/models，不产生推理费用", font=self.F_SM,
                 bg=CARD, fg=TER).pack(side="right", padx=(0, 16), pady=(4, 0))
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

    def _build_conn(self, parent) -> None:
        _box, _head, f = self._card(parent, "连接", "填入中转端点和 Key，拉取可用模型")

        r1 = tk.Frame(f, bg=CARD)
        r1.pack(fill="x")
        self._field(r1, "端点")
        self.base = ttk.Entry(r1)
        self.base.pack(side="left", fill="x", expand=True)
        self._field(r1, "鉴权", 6)
        self.fmt = ttk.Combobox(
            r1, width=20, state="readonly",
            values=["Bearer（OpenAI 兼容）", "x-api-key（Anthropic）", "x-goog-api-key（Google）"],
        )
        self.fmt.current(0)
        self.fmt.pack(side="left")

        r2 = tk.Frame(f, bg=CARD)
        r2.pack(fill="x", pady=(8, 0))
        self._field(r2, "API Key")
        self.key = ttk.Entry(r2, width=34, show="•")
        self.key.pack(side="left")
        self.show_key = tk.BooleanVar(value=False)
        self.eye_btn = ttk.Button(r2, text="显示", width=6, command=self._toggle_key)
        self.eye_btn.pack(side="left", padx=(8, 0))
        self.fetch_btn = ttk.Button(r2, text="拉取模型列表", style="Primary.TButton", command=self.do_fetch)
        self.fetch_btn.pack(side="right")

        r3 = tk.Frame(f, bg=CARD)
        r3.pack(fill="x", pady=(8, 0))
        self._field(r3, "UA")
        self.ua = ttk.Entry(r3, width=24)
        self.ua.pack(side="left")
        self._field(r3, "models 地址", 12)
        self.murl = ttk.Entry(r3, width=28)
        self.murl.pack(side="left")
        self.full_url = tk.BooleanVar(value=False)
        ttk.Checkbutton(r3, text="完整 URL 模式", variable=self.full_url).pack(side="left", padx=(14, 0))

    def _build_models(self, parent) -> None:
        _box, head, f = self._card(parent, "模型", expand=True)

        bar = tk.Frame(f, bg=CARD)
        bar.pack(fill="x")
        self.q_var = tk.StringVar()
        self.q_var.trace_add("write", lambda *_: self.render())
        self.search = ttk.Entry(bar, textvariable=self.q_var, width=26)
        self.search.pack(side="left")
        self.search.bind("<FocusIn>", self._search_in)
        self.search.bind("<FocusOut>", self._search_out)
        for text, kind in (("全选", "all"), ("全不选", "none"), ("反选", "inv"), ("仅 Claude / Anthropic", "gw")):
            ttk.Button(bar, text=text, command=lambda k=kind: self.sel(k)).pack(side="left", padx=(8, 0))
        self.count = ttk.Label(bar, text="共 0 个模型", style="Small.TLabel")
        self.count.pack(side="right")

        self.prog = ttk.Progressbar(f, mode="indeterminate", maximum=20)

        listbox = tk.Frame(f, bg=CARD, highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER)
        listbox.pack(fill="both", expand=True, pady=(10, 0))
        self.tree = ttk.Treeview(
            listbox, columns=("sel", "no", "id", "name", "by", "ctx"), show="headings", height=8
        )
        self.tree.heading("sel", text="")
        self.tree.heading("no", text="#")
        self.tree.heading("id", text="模型 ID")
        self.tree.heading("name", text="名称")
        self.tree.heading("by", text="提供方")
        self.tree.heading("ctx", text="上下文")
        self.tree.column("sel", width=38, anchor="center", stretch=False)
        self.tree.column("no", width=52, anchor="center", stretch=False)
        self.tree.column("id", width=340)
        self.tree.column("name", width=200)
        self.tree.column("by", width=120)
        self.tree.column("ctx", width=90, anchor="e", stretch=False)
        self.tree.tag_configure("picked", background=PICK)
        sb = ttk.Scrollbar(listbox, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<MouseWheel>", self._tree_wheel)
        self.tree.bind("<ButtonRelease-1>", self._on_row_click)
        self.tree.bind("<space>", self._on_space)
        self.tree.bind("<Double-1>", self._on_row_click)
        self.empty = tk.Label(listbox, text="还没有模型，先在上方拉取列表", font=self.F_SM, bg=CARD, fg=TER)
        self._ph = "搜索模型 ID 或名称"
        self._search_out()
        self.render()

    def _build_target(self, parent) -> None:
        _box, _head, f = self._card(parent, "写入目标")

        r1 = tk.Frame(f, bg=CARD)
        r1.pack(fill="x")
        self.mode = tk.StringVar(value="list")
        for text, val in (("一张卡 + 模型列表", "list"), ("每个模型一张卡", "fanout")):
            ttk.Radiobutton(r1, text=text, value=val, variable=self.mode, command=self.sync_mode).pack(
                side="left", padx=(0, 18)
            )
        tk.Label(r1, text="卡 = 一套完整配置（端点 + Key + 模型）", font=self.F_SM, bg=CARD, fg=TER).pack(side="left")

        r2 = tk.Frame(f, bg=CARD)
        r2.pack(fill="x", pady=(9, 0))
        self._field(r2, "应用")
        self.app = ttk.Combobox(r2, width=10, state="readonly", values=["claude", "codex", "opencode"])
        self.app.set("claude")
        self.app.bind("<<ComboboxSelected>>", lambda _e: self.sync_mode())
        self.app.pack(side="left")
        self._field(r2, "供应商卡", 8)
        self.provider = ttk.Combobox(r2, width=40, state="readonly")
        self.provider.pack(side="left", fill="x", expand=True)
        self._field(r2, "卡名前缀", 8)
        self.prefix = ttk.Entry(r2, width=14)
        self.prefix.pack(side="left")

        r3 = tk.Frame(f, bg=CARD)
        r3.pack(fill="x", pady=(7, 0))
        self.replace = tk.BooleanVar(value=True)
        self.opt_replace = ttk.Checkbutton(r3, text="只显示我选的模型", variable=self.replace)
        self.opt_replace.pack(side="left", padx=(0, 18))
        self.disc = tk.BooleanVar(value=False)
        self.opt_disc = ttk.Checkbutton(r3, text="同时开启网关模型发现", variable=self.disc)
        self.opt_disc.pack(side="left", padx=(0, 18))
        self.merge = tk.BooleanVar(value=False)
        self.opt_merge = ttk.Checkbutton(r3, text="合并到已有模型列表", variable=self.merge)
        self.opt_merge.pack(side="left")

        r4 = tk.Frame(f, bg=CARD)
        r4.pack(fill="x", pady=(4, 0))
        self._field(r4, "上下文", 8)
        self.ctx_var = tk.StringVar(value=str(DEFAULT_CONTEXT))
        self.ctx_entry = ttk.Entry(r4, width=11, textvariable=self.ctx_var)
        self.ctx_entry.pack(side="left")
        ttk.Button(r4, text="取接口最大值", command=self._fill_max_ctx).pack(side="left", padx=(8, 0))
        self._field(r4, "最大输出", 8)
        self.out_var = tk.StringVar(value=str(DEFAULT_OUTPUT))
        self.out_entry = ttk.Entry(r4, width=11, textvariable=self.out_var)
        self.out_entry.pack(side="left")
        tk.Label(r4, text="接口没给上下文时用这里的值（token）", font=self.F_SM, bg=CARD, fg=TER).pack(
            side="left", padx=(14, 0)
        )

        r4b = tk.Frame(f, bg=CARD)
        r4b.pack(fill="x", pady=(4, 0))
        self.roles = tk.BooleanVar(value=True)
        self.opt_roles = ttk.Checkbutton(r4b, text="同时填 Sonnet / Opus / Haiku 槽位", variable=self.roles)
        self.opt_roles.pack(side="left")

        self._divider(f)

        r5 = tk.Frame(f, bg=CARD)
        r5.pack(fill="x")
        self.backup_lbl = tk.Label(r5, text="", font=self.F_SM, bg=CARD, fg=TER)
        self.backup_lbl.pack(side="right")
        ttk.Button(r5, text="删除卡…", style="Danger.TButton", command=self.delete_card_dialog).pack(side="right")
        ttk.Button(r5, text="新建卡…", command=self.new_card_dialog).pack(side="right", padx=(0, 8))
        ttk.Button(r5, text="预览变更", command=self.do_preview).pack(side="left")
        self.apply_btn = ttk.Button(r5, text="写入（自动备份）", style="Primary.TButton", command=self.do_apply)
        self.apply_btn.pack(side="left", padx=(8, 0))
        self.undo_btn = ttk.Button(r5, text="回滚上一次写入", style="Danger.TButton", command=self.do_rollback,
                                   state="disabled")
        self.undo_btn.pack(side="left", padx=(8, 0))

    def _build_log(self, parent) -> None:
        _box, head, f = self._card(parent, "日志")
        ttk.Button(head, text="清空", command=self._clear_log).pack(side="right")
        self.log = tk.Text(
            f, height=5, bg=CARD, fg=SEC, insertbackground=ACC, relief="flat",
            wrap="word", font=self.F_SM, padx=10, pady=8, spacing1=2, spacing3=2,
            highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER,
        )
        sb = ttk.Scrollbar(f, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")

    # ---------- 交互 ----------

    def logln(self, msg: str) -> None:
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    def _clear_log(self) -> None:
        self.log.delete("1.0", "end")

    def _toggle_key(self) -> None:
        show = not self.show_key.get()
        self.show_key.set(show)
        self.key.configure(show="" if show else "•")
        self.eye_btn.configure(text="隐藏" if show else "显示")

    def _search_in(self, _event=None) -> None:
        if self.q_var.get() == self._ph:
            self.q_var.set("")
            self.search.configure(style="TEntry")

    def _search_out(self, _event=None) -> None:
        if not self.q_var.get().strip():
            self.q_var.set(self._ph)
            self.search.configure(style="Ghost.TEntry")

    def _pump(self) -> None:
        try:
            while True:
                kind, payload, extra = self.q.get_nowait()
                if kind == "log":
                    self.logln(payload)
                elif kind == "err":
                    self.logln("错误：" + payload)
                    messagebox.showerror("出错", payload)
                elif kind == "status":
                    self._set_status(bool(payload))
                elif kind == "done" and extra:
                    extra(payload)
                elif kind == "done":
                    self.logln(str(payload))
        except queue.Empty:
            pass
        self.after(120, self._pump)

    def _work(self, fn, on_done=None) -> None:
        def target():
            try:
                res = fn()
                self.q.put(("done", res, on_done))
            except Exception as exc:
                self.q.put(("err", str(exc), None))

        threading.Thread(target=target, daemon=True).start()

    def _refresh_status(self) -> None:
        def job():
            try:
                self.q.put(("status", core.cc_switch_running(), None))
            except Exception:
                pass

        threading.Thread(target=job, daemon=True).start()
        self.after(8000, self._refresh_status)

    def _set_status(self, running: bool) -> None:
        if running:
            self.status.configure(text="● CC Switch 正在运行 · 请先退出再写入", fg=RED)
            self.apply_btn.configure(state="disabled")
        else:
            self.status.configure(text="● CC Switch 未运行 · 可以写入", fg=GREEN)
            self.apply_btn.configure(state="normal")

    def do_fetch(self) -> None:
        base = self.base.get().strip()
        if not base:
            messagebox.showwarning("缺少信息", "请填写端点地址")
            return
        key = self.key.get()
        fmt = ["openai", "anthropic", "google"][self.fmt.current()]
        ua = self.ua.get().strip() or None
        murl = self.murl.get().strip() or None
        full = self.full_url.get()
        self.fetch_btn.configure(state="disabled", text="拉取中…")
        self.prog.pack(fill="x", pady=(10, 0))
        self.prog.start(14)

        def job():
            models, _ = core.fetch_models(
                base, key, is_full_url=full, models_url=murl, user_agent=ua, api_format=fmt,
                log=lambda m: self.q.put(("log", core.redact(m, [key] if key else []), None)),
            )
            core.save_models(models)
            return models

        def done(models):
            self.models = models
            self.picked.clear()
            self.render()
            self.logln(f"共 {len(models)} 个模型")
            known = [int(getattr(m, "context", 0) or 0) for m in models]
            known = [n for n in known if n > 0]
            if known:
                self.ctx_var.set(str(max(known)))
                self.logln(f"接口返回了 {len(known)} 个模型的上下文，已按最大值 {max(known)}（{_fmt_ctx(max(known))}）填入")
            else:
                self.logln("接口没返回上下文长度，可在「写入目标」里手动填（默认 1M / 128K）")
            self.prog.stop()
            self.prog.pack_forget()
            self.fetch_btn.configure(state="normal", text="拉取模型列表")

        self._work(job, done)

    def render(self) -> None:
        if not hasattr(self, "tree"):
            return
        q = self.q_var.get().strip().lower()
        if q == self._ph.lower():
            q = ""
        self.visible = [
            i for i, m in enumerate(self.models)
            if not q or q in m.id.lower() or q in (m.display_name or "").lower()
        ]
        self.tree.delete(*self.tree.get_children())
        for i in self.visible:
            m = self.models[i]
            picked = i in self.picked
            self.tree.insert(
                "", "end", iid=str(i), tags=("picked",) if picked else (),
                values=("✓" if picked else "", i + 1, m.id, m.display_name, m.owned_by, _fmt_ctx(m.context)),
            )
        total = len(self.models)
        shown = len(self.visible)
        known = sum(1 for m in self.models if getattr(m, "context", 0))
        self.count.configure(
            text=f"已选 {len(self.picked)}"
            + (f" · 显示 {shown} / {total} 个模型" if shown != total else f" · 共 {total} 个模型")
            + (f" · 接口给出 {known} 个上下文" if known else "")
        )
        if total:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.5, anchor="center")
            self.empty.lift()

    def _tree_wheel(self, event):
        if not self._scrollable(self.tree):
            return  # 没有可滚内容时交给页面滚动
        step = int(-1 * (event.delta / 120)) or (-1 if event.delta > 0 else 1)
        self.tree.yview_scroll(step, "units")
        return "break"

    def _on_row_click(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if not row:
            return
        i = int(row)
        if i in self.picked:
            self.picked.discard(i)
        else:
            self.picked.add(i)
        self.render()

    def _on_space(self, _event) -> None:
        for row in self.tree.selection():
            i = int(row)
            if i in self.picked:
                self.picked.discard(i)
            else:
                self.picked.add(i)
        self.render()

    def sel(self, kind: str) -> None:
        idx = self.visible
        if kind == "all":
            self.picked.update(idx)
        elif kind == "none":
            self.picked.difference_update(idx)
        elif kind == "inv":
            for i in idx:
                self.picked.remove(i) if i in self.picked else self.picked.add(i)
        elif kind == "gw":
            for i in idx:
                if "claude" in self.models[i].id.lower() or "anthropic" in self.models[i].id.lower():
                    self.picked.add(i)
                else:
                    self.picked.discard(i)
        self.render()

    def sync_mode(self) -> None:
        m = self.mode.get()
        app = self.app.get()
        if m == "fanout" and app == "opencode":
            self.app.set("claude")
            app = "claude"
        self.opt_replace.configure(
            state="normal" if (m == "list" and app == "claude") else "disabled"
        )
        self.opt_disc.configure(
            state="normal" if (m == "list" and app == "claude") else "disabled"
        )
        self.opt_merge.configure(
            state="normal" if (m == "list" and app in ("opencode",)) else "disabled"
        )
        self.ctx_entry.configure(state="normal" if (m == "list" and app in ("opencode", "codex")) else "disabled")
        self.out_entry.configure(state="normal" if (m == "list" and app == "opencode") else "disabled")
        self.opt_roles.configure(state="normal" if m == "fanout" else "disabled")
        self.load_providers()

    def load_providers(self) -> None:
        app = self.app.get()

        def job():
            try:
                return core.list_providers(app)
            except Exception as exc:
                self.q.put(("log", f"读取供应商卡失败：{exc}", None))
                return []

        def done(rows):
            self.provider_ids = [r["id"] for r in rows]
            self.provider.configure(values=[f"{r['name']}（{r['id']}）" for r in rows])
            if self.provider_ids:
                self.provider.current(0)

        self._work(job, done)

    def chosen(self) -> list[core.Model]:
        return [self.models[i] for i in sorted(self.picked)]

    def payload(self) -> dict:
        idx = self.provider.current()
        return {
            "mode": self.mode.get(),
            "app": self.app.get(),
            "providerId": self.provider_ids[idx] if idx >= 0 and idx < len(self.provider_ids) else None,
            "models": [m.to_dict() for m in self.chosen()],
            "replaceBuiltIn": self.replace.get(),
            "gatewayDiscovery": self.disc.get(),
            "merge": self.merge.get(),
            "fillRoles": self.roles.get(),
            "namePrefix": self.prefix.get().strip(),
            "context": _as_tokens(self.ctx_var.get(), DEFAULT_CONTEXT),
            "output": _as_tokens(self.out_var.get(), DEFAULT_OUTPUT),
        }

    def _fill_max_ctx(self) -> None:
        known = [int(getattr(m, "context", 0) or 0) for m in self.models]
        known = [n for n in known if n > 0]
        if not known:
            messagebox.showinfo("上下文", "接口没有返回任何上下文长度，已填入默认值，可手动修改。")
            self.ctx_var.set(str(DEFAULT_CONTEXT))
            return
        top = max(known)
        self.ctx_var.set(str(top))
        self.logln(f"已取接口返回的最大上下文：{top}（{_fmt_ctx(top)}）")

    def do_preview(self) -> None:
        if not self.picked:
            messagebox.showwarning("未选择", "请先勾选模型")
            return
        body = self.payload()
        self._work(lambda: _preview_text(body), self._show_preview)

    def _show_preview(self, text: str) -> None:
        win = tk.Toplevel(self)
        win.title("变更预览")
        win.configure(bg=APP_BG)
        win.transient(self)
        outer = tk.Frame(win, bg=APP_BG)
        outer.pack(fill="both", expand=True, padx=16, pady=16)
        box = tk.Frame(outer, bg=CARD, highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER)
        box.pack(fill="both", expand=True)
        head = tk.Frame(box, bg=CARD)
        head.pack(fill="x", padx=PAD, pady=(12, 7))
        tk.Label(head, text="变更预览", font=self.F_H3, bg=CARD, fg=TEXT).pack(side="left")
        body = tk.Frame(box, bg=CARD)
        body.pack(fill="both", expand=True, padx=PAD, pady=(0, 12))

        view = tk.Text(
            body, bg=CARD, fg=TEXT, relief="flat", wrap="word", font=self.F_SM,
            padx=10, pady=8, highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER,
        )
        sb = ttk.Scrollbar(body, orient="vertical", command=view.yview)
        view.configure(yscrollcommand=sb.set)
        view.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        view.insert("end", text)
        view.configure(state="disabled")

        bar = tk.Frame(box, bg=CARD)
        bar.pack(fill="x", padx=PAD, pady=(0, 14))
        ttk.Button(bar, text="关闭", command=win.destroy).pack(side="right")
        self._center(win, 760, 560)

    def do_apply(self) -> None:
        if not self.picked:
            messagebox.showwarning("未选择", "请先勾选模型")
            return
        body = self.payload()
        if body["mode"] != "codex" and not body["providerId"]:
            messagebox.showwarning("未选择", "请选择目标供应商卡")
            return
        if not messagebox.askyesno("确认写入", f"将写入 {len(self.picked)} 个模型，写入前自动备份。继续？"):
            return
        self._work(lambda: _apply(body), self._after_apply)

    def _after_apply(self, res: dict) -> None:
        self.logln("写入成功：" + res.get("summary", ""))
        backup = res.get("backup") or res.get("dbBackup")
        if backup:
            self.last_backup = backup
            self.backup_lbl.configure(text="上次备份：" + backup)
            self.undo_btn.configure(state="normal")
        self._refresh_status()

    def new_card_dialog(self) -> None:
        win = tk.Toplevel(self)
        win.title("新建供应商卡")
        win.configure(bg=APP_BG)
        win.transient(self)
        outer = tk.Frame(win, bg=APP_BG)
        outer.pack(fill="both", expand=True, padx=16, pady=16)
        box = tk.Frame(outer, bg=CARD, highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER)
        box.pack(fill="both", expand=True)
        head = tk.Frame(box, bg=CARD)
        head.pack(fill="x", padx=PAD, pady=(12, 7))
        tk.Label(head, text="新建供应商卡", font=self.F_H3, bg=CARD, fg=TEXT).pack(side="left")
        f = tk.Frame(box, bg=CARD)
        f.pack(fill="both", expand=True, padx=PAD, pady=(4, 15))
        f.columnconfigure(1, weight=1)

        app_var = tk.StringVar(value=self.app.get())
        name_var = tk.StringVar(value="")
        url_var = tk.StringVar(value=self.base.get().strip())
        key_var = tk.StringVar(value=self.key.get())
        model_var = tk.StringVar(value="")

        fields = (
            ("应用", None),
            ("名称", None),
            ("端点", None),
            ("Key", None),
            ("默认模型", None),
        )
        for r, (label, _w) in enumerate(fields):
            tk.Label(f, text=label, font=self.F_SM, bg=CARD, fg=SEC, width=8,
                     anchor="e").grid(row=r, column=0, sticky="e", padx=(0, 10), pady=7)

        ttk.Combobox(f, width=14, state="readonly", textvariable=app_var,
                     values=["claude", "codex", "opencode"]).grid(row=0, column=1, sticky="w")
        ttk.Entry(f, textvariable=name_var).grid(row=1, column=1, sticky="ew")
        ttk.Entry(f, textvariable=url_var).grid(row=2, column=1, sticky="ew")
        ttk.Entry(f, textvariable=key_var, show="•").grid(row=3, column=1, sticky="ew")
        ttk.Entry(f, textvariable=model_var).grid(row=4, column=1, sticky="ew")
        tk.Label(f, text="留空则先建卡，再用上面的模型列表写入", font=self.F_SM, bg=CARD, fg=TER).grid(
            row=5, column=1, sticky="w", pady=(2, 0)
        )

        def submit() -> None:
            body = {
                "app": app_var.get(),
                "name": name_var.get().strip(),
                "baseUrl": url_var.get().strip(),
                "apiKey": key_var.get().strip(),
                "model": model_var.get().strip(),
            }

            def job():
                res = core.create_provider(
                    body["app"], body["name"], body["baseUrl"], body["apiKey"], model=body["model"]
                )
                res["summary"] = f"已新建 {res['app']} 卡「{res['name']}」"
                return res

            def done(res):
                self.logln("新建成功：" + res["summary"])
                if res.get("backup"):
                    self.last_backup = res["backup"]
                    self.undo_btn.configure(state="normal")
                self.app.set(res["app"])
                self.sync_mode()
                self.after(600, lambda: self._select_provider(res["id"]))
                win.destroy()

            self._work(job, done)

        bar = tk.Frame(f, bg=CARD)
        bar.grid(row=6, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(bar, text="取消", command=win.destroy).pack(side="right")
        ttk.Button(bar, text="创建", style="Primary.TButton", command=submit).pack(side="right", padx=(8, 0))
        self._center(win, 560, 360)

    def _select_provider(self, pid: str) -> None:
        if pid in self.provider_ids:
            self.provider.current(self.provider_ids.index(pid))

    def delete_card_dialog(self) -> None:
        try:
            rows = core.list_providers(self.app.get())
        except Exception as exc:
            messagebox.showwarning("读取失败", f"读取供应商卡失败：{exc}")
            return
        win = tk.Toplevel(self)
        win.title(f"删除 {self.app.get()} 卡")
        win.configure(bg=APP_BG)
        win.transient(self)
        outer = tk.Frame(win, bg=APP_BG)
        outer.pack(fill="both", expand=True, padx=16, pady=16)
        box = tk.Frame(outer, bg=CARD, highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER)
        box.pack(fill="both", expand=True)
        head = tk.Frame(box, bg=CARD)
        head.pack(fill="x", padx=PAD, pady=(12, 7))
        tk.Label(head, text=f"删除 {self.app.get()} 卡", font=self.F_H3, bg=CARD, fg=TEXT).pack(side="left")
        f = tk.Frame(box, bg=CARD)
        f.pack(fill="both", expand=True, padx=PAD, pady=(0, 15))

        tk.Label(f, text="可多选；默认拒绝删除正在使用的卡", font=self.F_SM, bg=CARD, fg=SEC).pack(anchor="w")
        holder = tk.Frame(f, bg=CARD, highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER)
        holder.pack(fill="both", expand=True, pady=(8, 0))
        lst = tk.Listbox(
            holder, selectmode="extended", bg=CARD, fg=TEXT, relief="flat", font=self.F_BODY,
            highlightthickness=0, borderwidth=0, selectbackground=ACC, selectforeground="#ffffff",
            activestyle="none",
        )
        sb = ttk.Scrollbar(holder, orient="vertical", command=lst.yview)
        lst.configure(yscrollcommand=sb.set)
        lst.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        sb.pack(side="right", fill="y")
        for r in rows:
            mark = " · 当前" if int(r["is_current"] or 0) else ""
            lst.insert("end", f"{r['name']}（{r['id']}）{mark}")

        force = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="强制删除（含当前卡）", variable=force).pack(anchor="w", pady=(10, 0))

        def submit() -> None:
            idx = lst.curselection()
            if not idx:
                messagebox.showwarning("未选择", "请选择要删除的卡")
                return
            ids = [rows[i]["id"] for i in idx]
            names = [rows[i]["name"] for i in idx]
            if not messagebox.askyesno("确认删除", f"删除 {len(ids)} 张卡？\n" + "\n".join(names)):
                return

            def job():
                res = core.delete_providers(self.app.get(), ids, force=force.get())
                res["summary"] = f"已删除 {res['deleted']} 张卡：" + "、".join(res["names"])
                return res

            def done(res):
                self.logln(res["summary"])
                if res.get("backup"):
                    self.last_backup = res["backup"]
                    self.undo_btn.configure(state="normal")
                self.load_providers()
                win.destroy()

            self._work(job, done)

        bar = tk.Frame(f, bg=CARD)
        bar.pack(fill="x", pady=(14, 0))
        ttk.Button(bar, text="取消", command=win.destroy).pack(side="right")
        ttk.Button(bar, text="删除", style="Danger.TButton", command=submit).pack(side="right", padx=(8, 0))
        self._center(win, 620, 440)

    def do_rollback(self) -> None:
        if not self.last_backup:
            return
        if not messagebox.askyesno("回滚", "回滚到上一次写入前的备份？"):
            return
        backup = self.last_backup

        def job():
            return core.rollback(backup, "db")

        def done(res):
            self.logln("已回滚：" + res["restored"])
            self.undo_btn.configure(state="disabled")

        self._work(job, done)


def _models_from(body: dict) -> list[core.Model]:
    out = []
    for item in body.get("models") or []:
        if isinstance(item, str):
            out.append(core.Model(id=item))
        else:
            out.append(
                core.Model(
                    id=str(item.get("id") or ""),
                    display_name=str(item.get("display_name") or ""),
                    description=str(item.get("description") or ""),
                    owned_by=str(item.get("owned_by") or ""),
                    context=int(item.get("context") or 0),
                    output=int(item.get("output") or 0),
                )
            )
    return [m for m in out if m.id]


def _preview_text(body: dict) -> str:
    models = _models_from(body)
    if not models:
        raise ValueError("没有选择任何模型")
    mode = body.get("mode", "list")
    app = body.get("app", "claude")

    if mode == "list" and app == "opencode":
        prov = core.get_provider("opencode", body.get("providerId"))
        if not prov:
            raise ValueError("找不到 OpenCode 供应商卡")
        existing = json.loads(prov["settings_config"]).get("models") or {}
        built = core.build_opencode_models(
            models,
            existing=existing if isinstance(existing, dict) else None,
            merge=bool(body.get("merge")),
            context=int(body.get("context") or DEFAULT_CONTEXT),
            output=int(body.get("output") or DEFAULT_OUTPUT),
        )
        head = dict(list(built.items())[:6])
        text = json.dumps({"models": head, "…": f"共 {len(built)} 个"}, ensure_ascii=False, indent=2)
        action = "合并进" if body.get("merge") else "覆盖为"
        known = sum(1 for m in models if getattr(m, "context", 0))
        note = f"上下文 {_fmt_ctx(int(body.get('context') or 0))}" + (
            f"（其中 {known} 个模型用接口返回值）" if known else "（接口未返回，使用手动值）"
        )
        return f"把 OpenCode 卡「{prov['name']}」的模型列表{action} {len(built)} 个模型；{note}\n\n" + text

    if mode == "list" and app == "codex":
        catalog = core.build_codex_catalog(models, context=int(body.get("context") or 0))
        text = json.dumps(
            {"models": catalog["models"][:2], "…": f"共 {len(catalog['models'])} 条"},
            ensure_ascii=False, indent=2,
        )
        return f"写入 {core.CODEX_CATALOG}\n\n" + text

    if mode == "fanout":
        template = core.get_provider(app, body.get("providerId"))
        if not template:
            raise ValueError("找不到模板卡")
        cards = core.build_fanout_cards(
            template, models, app_type=app,
            endpoints=core.get_endpoints(app, body["providerId"]),
            fill_roles=bool(body.get("fillRoles", True)),
            name_prefix=str(body.get("namePrefix") or ""),
        )
        names = [c["name"] for c in cards]
        text = json.dumps(
            {"将新建": len(names), "卡片": names[:30], "…": f"共 {len(names)} 张" if len(names) > 30 else ""},
            ensure_ascii=False, indent=2,
        )
        return f"以「{template['name']}」为模板，在 {app} 下新建 {len(names)} 张卡\n\n" + text

    prov = core.get_provider("claude", body.get("providerId"))
    if not prov:
        raise ValueError("找不到 Claude 供应商卡")
    picker = core.build_model_picker(models, bool(body.get("replaceBuiltIn", True)))
    shown = picker["options"][:12]
    text = json.dumps(
        {"options": shown, "…": f"共 {len(picker['options'])} 行",
         "replaceBuiltInOptions": picker["replaceBuiltInOptions"]},
        ensure_ascii=False, indent=2,
    )
    target = f"写入 Claude 卡「{prov['name']}」的 modelPicker"
    if body.get("gatewayDiscovery"):
        target += "\n并开启 CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1"
    return target + "\n\n" + text


def _apply(body: dict) -> dict:
    models = _models_from(body)
    if not models:
        raise ValueError("没有选择任何模型")
    if core.cc_switch_running():
        raise RuntimeError("CC Switch 正在运行，请先完全退出后再写入")

    mode = body.get("mode", "list")
    app = body.get("app", "claude")
    pid = body.get("providerId")

    if mode == "fanout":
        res = core.apply_fanout(
            pid, models, app_type=app,
            fill_roles=bool(body.get("fillRoles", True)),
            name_prefix=str(body.get("namePrefix") or ""),
        )
        res["summary"] = f"已在 {res['app']} 下新建 {res['rows']} 张供应商卡"
        return res

    if app == "opencode":
        res = core.apply_opencode(
            pid, models, merge=bool(body.get("merge")),
            context=int(body.get("context") or DEFAULT_CONTEXT),
            output=int(body.get("output") or DEFAULT_OUTPUT),
        )
        res["summary"] = f"已把 {res['rows']} 个模型写入 OpenCode 卡「{res['provider']}」的模型列表"
        return res

    if app == "codex":
        res = core.apply_codex(models, pid, context=int(body.get("context") or 0))
        res["summary"] = f"已把 {res['rows']} 个模型写入 Codex 模型目录 {res['catalog']}"
        return res

    res = core.apply_claude(
        pid, models,
        replace_builtin=bool(body.get("replaceBuiltIn", True)),
        gateway_discovery=bool(body.get("gatewayDiscovery")),
    )
    res["summary"] = f"已把 {res['rows']} 个模型写入 Claude 卡「{res['provider']}」的 modelPicker"
    return res


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
