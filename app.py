"""API Switch —— CC Switch 模型导入桌面版（tkinter，零第三方依赖）。

双击运行：拉取 /v1/models 列表 → 勾选要接入的模型 → 写入 CC Switch。
"""

from __future__ import annotations

import json
import math
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk

import ccs_models as core

if sys.platform == "win32":
    import ctypes
    import winreg

APP_NAME = "API Switch"

# ---------------------------------------------------------------- 配色

LIGHT = {
    "bg": "#f3f3f3",
    "card": "#ffffff",
    "subtle": "#fafafa",
    "hover": "#f5f5f5",
    "border": "#e2e2e2",
    "divider": "#ececec",
    "control_border": "#8a8a8a",
    "button_border": "#c9c9c9",
    "text": "#1b1b1b",
    "text2": "#5c5c5c",
    "text3": "#6f6f6f",
    "accent": "#0067c0",
    "accent_hover": "#005a9e",
    "accent_press": "#004e8c",
    "accent_text": "#ffffff",
    "accent_tint": "#e8f1fb",
    "select": "#d9d9d9",
    "row_hover": "#f6f6f6",
    "success": "#0f7b0f",
    "danger": "#c42b1c",
    "danger_tint": "#fdf3f2",
    "disabled_bg": "#f5f5f5",
    "disabled_border": "#e5e5e5",
    "disabled_text": "#9a9a9a",
    "scroll": "#c9c9c9",
    "scroll_hover": "#a8a8a8",
}

DARK = {
    "bg": "#202020",
    "card": "#2b2b2b",
    "subtle": "#303030",
    "hover": "#353535",
    "border": "#3d3d3d",
    "divider": "#383838",
    "control_border": "#8f8f8f",
    "button_border": "#4f4f4f",
    "text": "#f2f2f2",
    "text2": "#c8c8c8",
    "text3": "#a0a0a0",
    "accent": "#4cc2ff",
    "accent_hover": "#6ccfff",
    "accent_press": "#3ab0ec",
    "accent_text": "#0b0b0b",
    "accent_tint": "#16324a",
    "select": "#3a3a3a",
    "row_hover": "#323232",
    "success": "#6ccb5f",
    "danger": "#ff99a4",
    "danger_tint": "#3b2526",
    "disabled_bg": "#2a2a2a",
    "disabled_border": "#383838",
    "disabled_text": "#767676",
    "scroll": "#4d4d4d",
    "scroll_hover": "#6a6a6a",
}

SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24}
CARD_RADIUS = 8
CONTROL_RADIUS = 4

PAGE_PAD = 16
LEFT_WIDTH = 404
DEFAULT_CONTEXT = 1_000_000
DEFAULT_OUTPUT = 131_072

UI_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "API-Switch"
UI_CONFIG = UI_DIR / "ui.json"

THEME_LABELS = (("跟随系统", "system"), ("浅色", "light"), ("深色", "dark"))

_TOKENS_RE = re.compile(r"^(\d+(?:\.\d+)?)([km]?)$")
_SORTABLE = ("id", "name", "by", "ctx")
_HEADINGS = (
    ("sel", ""),
    ("no", "#"),
    ("id", "模型 ID"),
    ("name", "名称"),
    ("by", "提供方"),
    ("ctx", "上下文"),
)


# ---------------------------------------------------------------- 小工具


def _srgb_channel(value: int) -> float:
    c = value / 255.0
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    raw = color.lstrip("#")
    r, g, b = (int(raw[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _srgb_channel(r) + 0.7152 * _srgb_channel(g) + 0.0722 * _srgb_channel(b)


def contrast_ratio(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def parse_tokens(text: str, *, field: str) -> int:
    raw = (text or "").strip().lower().replace(",", "").replace("_", "")
    if not raw:
        raise ValueError(f"{field}不能为空")
    match = _TOKENS_RE.match(raw)
    if not match:
        raise ValueError(f"{field}请填写数字，或 256K / 1M 这样的写法")
    scale = {"": 1, "k": 1000, "m": 1_000_000}[match.group(2)]
    value = int(float(match.group(1)) * scale)
    if value <= 0:
        raise ValueError(f"{field}必须大于 0")
    return value


def _fmt_ctx(n: int) -> str:
    n = int(n or 0)
    if not n:
        return ""
    if n >= 1_000_000:
        return f"{n / 1_000_000:g}M"
    if n >= 1000:
        return f"{n / 1000:g}K"
    return str(n)


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = max(1, limit - 12)
    return text[:head] + "…" + text[-10:]


def _system_theme() -> str:
    if sys.platform != "win32":
        return "light"
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
    return "light" if value else "dark"


def palette_for(mode: str) -> dict[str, str]:
    if mode == "light":
        return dict(LIGHT)
    if mode == "dark":
        return dict(DARK)
    return dict(LIGHT if _system_theme() == "light" else DARK)


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    ctypes.windll.shcore.SetProcessDpiAwareness(1)


def load_ui_config(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"theme": "system", "geometry": "", "log_collapsed": False}


def save_ui_config(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def model_sort_value(model: core.Model, column: str):
    if column == "id":
        return model.id.lower()
    if column == "name":
        return (model.display_name or "").lower()
    if column == "by":
        return (model.owned_by or "").lower()
    if column == "ctx":
        return int(getattr(model, "context", 0) or 0)
    return ""


def sort_indices(models: list[core.Model], column: str, descending: bool) -> list[int]:
    order = list(range(len(models)))
    order.sort(key=lambda i: (model_sort_value(models[i], column), i), reverse=descending)
    return order


def filter_indices(models: list[core.Model], order: list[int], query: str) -> list[int]:
    q = (query or "").strip().lower()
    if not q:
        return list(order)
    return [
        i
        for i in order
        if q in models[i].id.lower() or q in (models[i].display_name or "").lower()
    ]


def rounded_rect(canvas: tk.Canvas, x1, y1, x2, y2, radius, **kwargs):
    r = max(0.0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    steps = 6
    points: list[float] = []
    centers = (
        (x2 - r, y1 + r, -90.0),
        (x2 - r, y2 - r, 0.0),
        (x1 + r, y2 - r, 90.0),
        (x1 + r, y1 + r, 180.0),
    )
    for cx, cy, start in centers:
        for i in range(steps + 1):
            angle = math.radians(start + 90.0 * i / steps)
            points.append(cx + r * math.cos(angle))
            points.append(cy + r * math.sin(angle))
    return canvas.create_polygon(points, **kwargs)


# ---------------------------------------------------------------- 自定义部件


class FluentButton(tk.Canvas):
    """圆角按钮：primary / secondary / subtle / danger 四种样式。"""

    def __init__(
        self,
        parent,
        text: str,
        command,
        pal: dict[str, str],
        *,
        kind: str = "secondary",
        font: tkfont.Font,
        height: int = 32,
        padx: int = 14,
        bg_role: str = "card",
        width: int | None = None,
    ) -> None:
        self.pal = pal
        self.kind = kind
        self.text = text
        self.command = command
        self.font = font
        self._height = height
        self._padx = padx
        self._bg_role = bg_role
        self._width = width or (font.measure(text) + padx * 2)
        self._enabled = True
        self._hover = False
        self._pressed = False
        self._focused = False
        super().__init__(
            parent, width=self._width, height=height, highlightthickness=0, bd=0,
            bg=pal[bg_role], takefocus=1,
        )
        self.bind("<Configure>", self._on_configure)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<FocusIn>", self._on_focus)
        self.bind("<FocusOut>", self._on_blur)
        self.bind("<Return>", self._on_key)
        self.bind("<space>", self._on_key)
        self._draw()

    # -- 状态 --

    def set_enabled(self, enabled: bool) -> None:
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if not enabled:
            self._hover = self._pressed = False
            self.configure(takefocus=0)
        else:
            self.configure(takefocus=1)
        self._draw()

    def set_text(self, text: str) -> None:
        if text == self.text:
            return
        self.text = text
        self._width = self.font.measure(text) + self._padx * 2
        self.configure(width=self._width)
        self._draw()

    def set_palette(self, pal: dict[str, str]) -> None:
        self.pal = pal
        self.configure(bg=pal[self._bg_role])
        self._draw()

    def invoke(self) -> None:
        if self._enabled and self.command is not None:
            self.command()

    # -- 事件 --

    def _on_configure(self, event) -> None:
        self._width = event.width
        self._height = event.height
        self._draw()

    def _on_enter(self, _event) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _event) -> None:
        self._hover = self._pressed = False
        self._draw()

    def _on_press(self, _event) -> None:
        if not self._enabled:
            return
        self._pressed = True
        self.focus_set()
        self._draw()

    def _on_release(self, event) -> None:
        if not self._enabled:
            return
        inside = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        self._pressed = False
        self._draw()
        if inside:
            self.invoke()

    def _on_focus(self, _event) -> None:
        self._focused = True
        self._draw()

    def _on_blur(self, _event) -> None:
        self._focused = False
        self._draw()

    def _on_key(self, _event) -> str:
        self.invoke()
        return "break"

    # -- 绘制 --

    def _bg_of(self) -> str:
        if self.kind == "primary":
            base = self.pal["accent"]
        elif self.kind == "subtle":
            base = self.pal[self._bg_role]
        else:
            base = self.pal["card"]
        if not self._enabled:
            base = self.pal["disabled_bg"]
        elif self._pressed:
            base = self.pal["accent_press"] if self.kind == "primary" else self.pal["hover"]
        elif self._hover:
            base = self.pal["accent_hover"] if self.kind == "primary" else self.pal["hover"]
        return base

    def _draw(self) -> None:
        self.delete("all")
        p = self.pal
        w = self._width
        h = self._height
        bg = self._bg_of()
        if self.kind == "primary":
            fg = p["accent_text"] if self._enabled else p["disabled_text"]
            border = ""
        elif self.kind == "danger":
            fg = p["danger"] if self._enabled else p["disabled_text"]
            border = p["button_border"] if self._enabled else p["disabled_border"]
        elif self.kind == "subtle":
            fg = p["text2"] if self._enabled else p["disabled_text"]
            border = ""
        else:
            fg = p["text"] if self._enabled else p["disabled_text"]
            border = p["button_border"] if self._enabled else p["disabled_border"]
        if self._focused and self._enabled:
            rounded_rect(self, 1, 1, w - 1, h - 1, CONTROL_RADIUS + 1, fill="", outline=p["text"], width=1)
        self._shape = rounded_rect(
            self, 2, 2, w - 2, h - 2, CONTROL_RADIUS, fill=bg, outline=border or bg, width=1,
        )
        self.create_text(w / 2, h / 2 + 1, text=self.text, fill=fg, font=self.font)


class Card(tk.Frame):
    """带 8px 圆角与 1px 边框的卡片容器，内容放在 .body。"""

    def __init__(self, parent, pal: dict[str, str], *, expand: bool = False) -> None:
        super().__init__(parent, bg=pal["bg"])
        self.pal = pal
        self.expand = expand
        self.canvas = tk.Canvas(self, bg=pal["bg"], highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=pal["card"])
        self._win = self.canvas.create_window(4, 4, window=self.body, anchor="nw")
        self._shape = None
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        if not expand:
            self.body.bind("<Configure>", self._on_body_configure)

    def _on_canvas_configure(self, event) -> None:
        self._draw(event.width, event.height)
        self.canvas.itemconfigure(self._win, width=max(1, event.width - 8))
        if self.expand:
            self.canvas.itemconfigure(self._win, height=max(1, event.height - 8))

    def _on_body_configure(self, _event) -> None:
        self.canvas.configure(height=self.body.winfo_reqheight() + 8)

    def _draw(self, width: int, height: int) -> None:
        if self._shape is not None:
            self.canvas.delete(self._shape)
        self._shape = rounded_rect(
            self.canvas, 1, 1, max(2, width - 1), max(2, height - 1), CARD_RADIUS,
            fill=self.pal["card"], outline=self.pal["border"],
        )
        self.canvas.tag_lower(self._shape)

    def refresh(self, pal: dict[str, str]) -> None:
        self.pal = pal
        self.configure(bg=pal["bg"])
        self.canvas.configure(bg=pal["bg"])
        self.body.configure(bg=pal["card"])
        self._draw(self.canvas.winfo_width(), self.canvas.winfo_height())


class ScrollColumn(tk.Frame):
    """固定宽度、内容超出时出现滚动条的纵向容器。"""

    def __init__(self, parent, pal: dict[str, str], width: int) -> None:
        super().__init__(parent, bg=pal["bg"], width=width)
        self.pal = pal
        self.pack_propagate(False)
        self.canvas = tk.Canvas(self, bg=pal["bg"], highlightthickness=0, bd=0)
        self.inner = tk.Frame(self.canvas, bg=pal["bg"])
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)

    def _on_inner(self, _event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._sync_scrollbar()

    def _on_canvas(self, event) -> None:
        self.canvas.itemconfigure(self._win, width=event.width)
        self._sync_scrollbar()

    def _sync_scrollbar(self) -> None:
        box = self.canvas.bbox("all")
        need = bool(box) and (box[3] - box[1]) > self.canvas.winfo_height() + 2
        if need and not self.scroll.winfo_ismapped():
            self.scroll.pack(side="right", fill="y")
        elif not need and self.scroll.winfo_ismapped():
            self.scroll.pack_forget()

    def can_scroll(self) -> bool:
        first, last = self.canvas.yview()
        return first > 0.0 or last < 1.0

    def refresh(self, pal: dict[str, str]) -> None:
        self.pal = pal
        self.configure(bg=pal["bg"])
        self.canvas.configure(bg=pal["bg"])
        self.inner.configure(bg=pal["bg"])


# ---------------------------------------------------------------- 界面


class App(tk.Tk):
    def __init__(self, config_path: Path | None = None) -> None:
        super().__init__()
        self._config_path = Path(config_path) if config_path else UI_CONFIG
        self._config = load_ui_config(self._config_path)
        self._theme_mode = str(self._config.get("theme") or "system")
        self.pal = palette_for(self._theme_mode)

        self._setup_scaling()
        self._fonts()
        self._style()

        self.models: list[core.Model] = []
        self.picked: set[int] = set()
        self.visible: list[int] = []
        self.provider_ids: list[str] = []
        self.last_backups: list[tuple[str, str]] = []
        self.q: queue.Queue = queue.Queue()
        self._sort: tuple[str, bool] | None = None
        self._anchor: int | None = None
        self._hover_row: str | None = None
        self._search_after: str | None = None
        self._busy = False
        self._fetching = False
        self._suppress_click = False
        self._last_press = (0.0, "")
        self._cc_running: bool | None = None
        self._ctx_ok = True
        self._out_ok = True
        self._themed: list[tuple[tk.Widget, dict[str, str]]] = []
        self._cards: list[Card] = []
        self._buttons: list[FluentButton] = []

        self._build()
        self._apply_theme()
        self._restore_geometry()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.logln("就绪。填写端点后点「拉取模型列表」。")
        self.after(120, self._pump)
        self.after(200, self._refresh_status)
        self.after(4000, self._watch_system_theme)

    # ---------- 基础 ----------

    def _setup_scaling(self) -> None:
        if sys.platform != "win32":
            return
        dpi = ctypes.windll.user32.GetDpiForSystem()
        self.tk.call("tk", "scaling", max(1.0, dpi / 72.0))

    def _fonts(self) -> None:
        families = set(tkfont.families())
        name = next(
            (f for f in ("Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI") if f in families),
            "TkDefaultFont",
        )
        self.f_title = tkfont.Font(family=name, size=15, weight="bold")
        self.f_head = tkfont.Font(family=name, size=12, weight="bold")
        self.f_body = tkfont.Font(family=name, size=11)
        self.f_small = tkfont.Font(family=name, size=10)
        self.f_mono = tkfont.Font(family="Cascadia Mono", size=10)

    def _style(self) -> None:
        p = self.pal
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass

        self.option_add("*TCombobox*Listbox.background", p["card"])
        self.option_add("*TCombobox*Listbox.foreground", p["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", p["accent"])
        self.option_add("*TCombobox*Listbox.selectForeground", p["accent_text"])
        self.option_add("*TCombobox*Listbox.font", self.f_body)

        s.configure(
            ".", background=p["card"], foreground=p["text"], fieldbackground=p["card"],
            bordercolor=p["control_border"], lightcolor=p["card"], darkcolor=p["card"],
            troughcolor=p["bg"],
        )
        s.configure("TFrame", background=p["card"])
        s.configure("TLabel", background=p["card"], foreground=p["text"], font=self.f_body)
        s.configure("Title.TLabel", font=self.f_title, foreground=p["text"])
        s.configure("Sub.TLabel", font=self.f_small, foreground=p["text2"])
        s.configure("CardTitle.TLabel", font=self.f_head, foreground=p["text"])
        s.configure("Section.TLabel", font=self.f_small, foreground=p["text2"])
        s.configure("Form.TLabel", font=self.f_small, foreground=p["text2"])
        s.configure("Hint.TLabel", font=self.f_small, foreground=p["text3"])
        s.configure("Chip.TLabel", font=self.f_small, foreground=p["text2"])
        s.configure("Error.TLabel", font=self.f_small, foreground=p["danger"])
        s.configure("Success.TLabel", font=self.f_small, foreground=p["success"])

        s.configure(
            "TEntry", fieldbackground=p["card"], foreground=p["text"],
            bordercolor=p["control_border"], lightcolor=p["control_border"],
            darkcolor=p["control_border"], borderwidth=1, relief="flat",
            padding=(8, 5), insertcolor=p["text"],
        )
        s.map(
            "TEntry",
            bordercolor=[("focus", p["accent"]), ("disabled", p["disabled_border"])],
            lightcolor=[("focus", p["accent"]), ("disabled", p["disabled_border"])],
            darkcolor=[("focus", p["accent"]), ("disabled", p["disabled_border"])],
            fieldbackground=[("disabled", p["disabled_bg"])],
            foreground=[("disabled", p["disabled_text"])],
        )
        s.configure(
            "Error.TEntry", fieldbackground=p["card"], foreground=p["text"],
            bordercolor=p["danger"], lightcolor=p["danger"], darkcolor=p["danger"],
            borderwidth=1, relief="flat", padding=(8, 5), insertcolor=p["text"],
        )
        s.map(
            "Error.TEntry",
            bordercolor=[("focus", p["danger"])],
            lightcolor=[("focus", p["danger"])],
            darkcolor=[("focus", p["danger"])],
        )

        s.configure(
            "TCombobox", fieldbackground=p["card"], background=p["card"], foreground=p["text"],
            bordercolor=p["control_border"], lightcolor=p["control_border"],
            darkcolor=p["control_border"], arrowcolor=p["text2"], padding=(8, 5),
        )
        s.map(
            "TCombobox",
            bordercolor=[("focus", p["accent"]), ("disabled", p["disabled_border"])],
            lightcolor=[("focus", p["accent"]), ("disabled", p["disabled_border"])],
            darkcolor=[("focus", p["accent"]), ("disabled", p["disabled_border"])],
            fieldbackground=[("disabled", p["disabled_bg"])],
            foreground=[("disabled", p["disabled_text"])],
            arrowcolor=[("disabled", p["disabled_text"])],
        )

        for name in ("TCheckbutton", "TRadiobutton"):
            s.configure(
                name, background=p["card"], foreground=p["text"], font=self.f_small,
                indicatorbackground=p["card"], indicatorforeground=p["accent_text"],
                upperbordercolor=p["control_border"], lowerbordercolor=p["control_border"],
                focuscolor=p["accent"], focusthickness=1, padding=(2, 4),
            )
            s.map(
                name,
                background=[("active", p["card"])],
                foreground=[("disabled", p["disabled_text"])],
                indicatorbackground=[
                    ("pressed", p["accent_press"]),
                    ("!disabled", "alternate", p["accent"]),
                    ("disabled", "alternate", p["disabled_border"]),
                    ("disabled", p["disabled_bg"]),
                ],
                upperbordercolor=[("disabled", p["disabled_border"])],
                lowerbordercolor=[("disabled", p["disabled_border"])],
            )

        s.configure(
            "Treeview", background=p["card"], fieldbackground=p["card"],
            foreground=p["text"], borderwidth=0, relief="flat",
            rowheight=34, font=self.f_body,
        )
        s.map("Treeview", background=[("selected", p["select"])], foreground=[("selected", p["text"])])
        s.configure(
            "Treeview.Heading", background=p["subtle"], foreground=p["text2"],
            font=self.f_small, relief="flat", padding=(8, 6), borderwidth=0,
            lightcolor=p["subtle"], darkcolor=p["subtle"], bordercolor=p["divider"],
        )
        s.map(
            "Treeview.Heading",
            background=[("active", p["hover"])],
            lightcolor=[("active", p["hover"])],
            darkcolor=[("active", p["hover"])],
        )

        s.configure(
            "TScrollbar", background=p["scroll"], troughcolor=p["card"], bordercolor=p["card"],
            lightcolor=p["card"], darkcolor=p["card"], arrowcolor=p["text2"],
            relief="flat", borderwidth=0, arrowsize=11, width=12,
        )
        s.map("TScrollbar", background=[("active", p["scroll_hover"])])
        s.configure(
            "TProgressbar", background=p["accent"], troughcolor=p["divider"],
            bordercolor=p["divider"], lightcolor=p["accent"], darkcolor=p["accent"],
            thickness=3,
        )

    def _watch(self, widget: tk.Widget, **roles: str) -> None:
        self._themed.append((widget, roles))
        self._apply_widget(widget, roles)

    def _apply_widget(self, widget: tk.Widget, roles: dict[str, str]) -> None:
        widget.configure(**{option: self.pal[key] for option, key in roles.items()})

    def _frame(self, parent, role: str = "card", **kwargs) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.pal[role], **kwargs)
        self._watch(frame, bg=role)
        return frame

    def _card(self, parent, *, expand: bool = False) -> Card:
        card = Card(parent, self.pal, expand=expand)
        self._cards.append(card)
        return card

    def _button(
        self, parent, text, command, *, kind="secondary", height=32, width=None, bg_role="card", padx=14,
    ) -> FluentButton:
        button = FluentButton(
            parent, text, command, self.pal, kind=kind, font=self.f_small,
            height=height, width=width, bg_role=bg_role, padx=padx,
        )
        self._buttons.append(button)
        return button

    def _apply_theme(self) -> None:
        self._prune_registry()
        self.pal = palette_for(self._theme_mode)
        self._style()
        for widget, roles in self._themed:
            self._apply_widget(widget, roles)
        for card in self._cards:
            card.refresh(self.pal)
        for button in self._buttons:
            button.set_palette(self.pal)
        for column in (self.left,):
            column.refresh(self.pal)
        self.tree.tag_configure("picked", background=self.pal["accent_tint"])
        self.tree.tag_configure("hover", background=self.pal["row_hover"])
        self.log_text.configure(
            bg=self.pal["card"], fg=self.pal["text2"], insertbackground=self.pal["accent"],
        )
        self.log_text.tag_configure("ts", foreground=self.pal["text3"])
        self.log_text.tag_configure("info", foreground=self.pal["text2"])
        self.log_text.tag_configure("ok", foreground=self.pal["success"])
        self.log_text.tag_configure("err", foreground=self.pal["danger"])
        self._draw_status_dot()

    def _prune_registry(self) -> None:
        self._themed = [(widget, roles) for widget, roles in self._themed if widget.winfo_exists()]
        self._cards = [card for card in self._cards if card.winfo_exists()]
        self._buttons = [button for button in self._buttons if button.winfo_exists()]

    def _watch_system_theme(self) -> None:
        if self._theme_mode == "system":
            current = palette_for("system")
            if current != self.pal:
                self._apply_theme()
        self.after(4000, self._watch_system_theme)

    # ---------- 布局 ----------

    def _build(self) -> None:
        self.title(APP_NAME)
        self.minsize(940, 620)
        self.configure(bg=self.pal["bg"])
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()

        main = self._frame(self, "bg")
        main.grid(row=1, column=0, sticky="nsew", padx=PAGE_PAD, pady=(PAGE_PAD, 0))
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=1)

        self.left = ScrollColumn(main, self.pal, LEFT_WIDTH)
        self.left.grid(row=0, column=0, sticky="ns")
        self._build_conn()
        self._build_target()

        self._build_models(main)

        self._build_log()
        self.bind_all("<MouseWheel>", self._on_wheel)
        self.bind_all("<Control-Return>", lambda _e: self.do_apply())
        self.bind_all("<Control-f>", lambda _e: self.search.focus_set())
        self.bind_all("<Control-F>", lambda _e: self.search.focus_set())
        self.bind_all("<F5>", lambda _e: self._reload())
        self.sync_mode()

    def _reload(self) -> None:
        self.load_providers()
        self._refresh_status()
        self.logln("已刷新供应商卡与 CC Switch 状态")

    def _build_header(self) -> None:
        bar = self._frame(self, "card")
        bar.grid(row=0, column=0, sticky="ew")
        inner = self._frame(bar, "card")
        inner.pack(fill="x", padx=PAGE_PAD, pady=(10, 9))

        title = tk.Label(inner, text=APP_NAME, font=self.f_title, bg=self.pal["card"], fg=self.pal["text"])
        title.pack(side="left")
        self._watch(title, bg="card", fg="text")
        subtitle = tk.Label(
            inner, text="CC Switch 模型导入", font=self.f_small, bg=self.pal["card"], fg=self.pal["text2"],
        )
        subtitle.pack(side="left", padx=(10, 0), pady=(4, 0), anchor="s")
        self._watch(subtitle, bg="card", fg="text2")

        self.status = tk.Label(inner, text="● 检查中…", font=self.f_small, bg=self.pal["card"], fg=self.pal["text3"])
        self.status.pack(side="right", pady=(2, 0))
        self._watch(self.status, bg="card")

        self.theme_box = ttk.Combobox(
            inner, width=9, state="readonly", values=[label for label, _mode in THEME_LABELS],
        )
        self.theme_box.pack(side="right", padx=(0, 14), pady=(1, 0))
        self.theme_box.bind("<<ComboboxSelected>>", self._on_theme_selected)
        index = next((n for n, (_label, mode) in enumerate(THEME_LABELS) if mode == self._theme_mode), 0)
        self.theme_box.current(index)

        divider = tk.Frame(self, height=1, bg=self.pal["border"])
        divider.grid(row=0, column=0, sticky="sew")
        self._watch(divider, bg="border")

    def _build_conn(self) -> None:
        card = self._card(self.left.inner)
        card.pack(fill="x", pady=(0, SPACE["md"]))
        head = self._frame(card.body, "card")
        head.pack(fill="x", padx=PAGE_PAD, pady=(12, 2))
        ttk.Label(head, text="连接", style="CardTitle.TLabel").pack(side="left")

        body = self._frame(card.body, "card")
        body.pack(fill="x", padx=PAGE_PAD, pady=(4, 14))
        body.columnconfigure(1, weight=1)

        self.base_var = tk.StringVar()
        ttk.Label(body, text="端点", style="Form.TLabel").grid(row=0, column=0, sticky="w", pady=(6, 0))
        self.base = ttk.Entry(body, textvariable=self.base_var)
        self.base.grid(row=0, column=1, sticky="ew", pady=(6, 0))
        self.base_err = ttk.Label(body, text="", style="Error.TLabel")
        self.base_err.grid(row=1, column=1, sticky="w")
        self._set_error(self.base_err, "")

        self.full_url = tk.BooleanVar(value=False)
        full_row = self._frame(body, "card")
        full_row.grid(row=2, column=1, sticky="w", pady=(4, 0))
        ttk.Checkbutton(full_row, text="完整 URL 模式", variable=self.full_url).pack(side="left")
        ttk.Label(full_row, text="端点填的是完整对话地址时勾选", style="Hint.TLabel").pack(
            side="left", padx=(10, 0)
        )

        self.key_var = tk.StringVar()
        ttk.Label(body, text="API Key", style="Form.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 0))
        key_row = self._frame(body, "card")
        key_row.grid(row=3, column=1, sticky="ew", pady=(8, 0))
        self.key = ttk.Entry(key_row, textvariable=self.key_var, show="•")
        self.key.pack(side="left", fill="x", expand=True)
        self.key_btn = self._button(key_row, "显示", self._toggle_key, kind="subtle", height=26, padx=8, bg_role="card")
        self.key_btn.pack(side="left", padx=(6, 0))

        self.fmt = ttk.Combobox(
            body, state="readonly",
            values=["Bearer（OpenAI 兼容）", "x-api-key（Anthropic）", "x-goog-api-key（Google）"],
        )
        self.fmt.current(0)
        ttk.Label(body, text="鉴权", style="Form.TLabel").grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.fmt.grid(row=4, column=1, sticky="ew", pady=(8, 0))

        self.ua_var = tk.StringVar()
        ttk.Label(body, text="UA", style="Form.TLabel").grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(body, textvariable=self.ua_var).grid(row=5, column=1, sticky="ew", pady=(8, 0))

        self.murl_var = tk.StringVar()
        ttk.Label(body, text="models 地址", style="Form.TLabel").grid(row=6, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(body, textvariable=self.murl_var).grid(row=6, column=1, sticky="ew", pady=(8, 0))

        self.fetch_btn = self._button(body, "拉取模型列表", self.do_fetch, kind="primary", height=34)
        self.fetch_btn.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Label(body, text="只发送 GET /v1/models，不产生推理费用", style="Hint.TLabel").grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

    def _build_target(self) -> None:
        card = self._card(self.left.inner)
        card.pack(fill="x")
        head = self._frame(card.body, "card")
        head.pack(fill="x", padx=PAGE_PAD, pady=(12, 2))
        ttk.Label(head, text="写入目标", style="CardTitle.TLabel").pack(side="left")

        body = self._frame(card.body, "card")
        body.pack(fill="x", padx=PAGE_PAD, pady=(4, 14))
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="模式", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(6, 2))
        self.mode = tk.StringVar(value="list")
        mode_row = self._frame(body, "card")
        mode_row.grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(mode_row, text="一张卡 + 模型列表", value="list", variable=self.mode,
                        command=self.sync_mode).pack(side="left", padx=(0, 14))
        ttk.Radiobutton(mode_row, text="每个模型一张卡", value="fanout", variable=self.mode,
                        command=self.sync_mode).pack(side="left")

        ttk.Label(body, text="目标", style="Section.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 2))
        self.app = ttk.Combobox(body, state="readonly", values=["claude", "codex", "opencode"])
        self.app.set("claude")
        self.app.bind("<<ComboboxSelected>>", lambda _e: self.sync_mode())
        ttk.Label(body, text="应用", style="Form.TLabel").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.app.grid(row=3, column=1, sticky="ew", pady=(6, 0))

        provider_row = self._frame(body, "card")
        provider_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        provider_row.columnconfigure(1, weight=1)
        ttk.Label(provider_row, text="供应商卡", style="Form.TLabel").grid(row=0, column=0, sticky="w", padx=(0, SPACE["sm"]))
        self.provider = ttk.Combobox(provider_row, state="readonly")
        self.provider.grid(row=0, column=1, sticky="ew")
        self.provider.bind("<<ComboboxSelected>>", lambda _e: self._update_action_state())
        self.new_btn = self._button(provider_row, "新建", self.new_card_dialog, kind="subtle", height=26, padx=8, bg_role="card")
        self.new_btn.grid(row=0, column=2, padx=(6, 0))
        self.del_btn = self._button(provider_row, "删除", self.delete_card_dialog, kind="subtle", height=26, padx=8, bg_role="card")
        self.del_btn.grid(row=0, column=3, padx=(4, 0))

        self.prefix_var = tk.StringVar()
        ttk.Label(body, text="卡名前缀", style="Form.TLabel").grid(row=5, column=0, sticky="w", pady=(8, 0))
        prefix_row = self._frame(body, "card")
        prefix_row.grid(row=5, column=1, sticky="ew", pady=(8, 0))
        prefix_row.columnconfigure(0, weight=1, minsize=100)
        self.prefix = ttk.Entry(prefix_row, textvariable=self.prefix_var)
        self.prefix.grid(row=0, column=0, sticky="ew")
        self.prefix_hint = ttk.Label(prefix_row, text="仅「每个模型一张卡」生效", style="Hint.TLabel")
        self.prefix_hint.grid(row=0, column=1, sticky="w", padx=(SPACE["sm"], 0))

        ttk.Label(body, text="选项", style="Section.TLabel").grid(row=6, column=0, columnspan=2, sticky="w", pady=(12, 2))
        self.replace = tk.BooleanVar(value=True)
        self.disc = tk.BooleanVar(value=False)
        self.merge = tk.BooleanVar(value=False)
        self.roles = tk.BooleanVar(value=True)
        self.opt_replace, self.hint_replace = self._option_row(body, 7, "只显示我选的模型", self.replace, "仅 claude + 一张卡")
        self.opt_disc, self.hint_disc = self._option_row(body, 8, "同时开启网关模型发现", self.disc, "仅 claude + 一张卡")
        self.opt_merge, self.hint_merge = self._option_row(body, 9, "合并到已有模型列表", self.merge, "仅 codex / opencode + 一张卡")
        self.opt_roles, self.hint_roles = self._option_row(body, 10, "同时填 Sonnet / Opus / Haiku 槽位", self.roles, "仅「每个模型一张卡」")

        ttk.Label(body, text="参数", style="Section.TLabel").grid(row=11, column=0, columnspan=2, sticky="w", pady=(12, 2))
        self.ctx_var = tk.StringVar(value=str(DEFAULT_CONTEXT))
        self.ctx_var.trace_add("write", lambda *_: self._validate_params())
        self.ctx_entry = ttk.Entry(body, textvariable=self.ctx_var, width=12)
        ttk.Label(body, text="上下文", style="Form.TLabel").grid(row=12, column=0, sticky="w", pady=(6, 0))
        ctx_row = self._frame(body, "card")
        ctx_row.grid(row=12, column=1, sticky="ew", pady=(6, 0))
        self.ctx_entry.pack(in_=ctx_row, side="left")
        self.max_btn = self._button(ctx_row, "取接口最大值", self._fill_max_ctx, kind="subtle", height=26, padx=8, bg_role="card")
        self.max_btn.pack(side="left", padx=(SPACE["sm"], 0))
        self.ctx_err = ttk.Label(body, text="", style="Error.TLabel")
        self.ctx_err.grid(row=13, column=1, sticky="w")

        self.out_var = tk.StringVar(value=str(DEFAULT_OUTPUT))
        self.out_var.trace_add("write", lambda *_: self._validate_params())
        self.out_entry = ttk.Entry(body, textvariable=self.out_var, width=12)
        ttk.Label(body, text="最大输出", style="Form.TLabel").grid(row=14, column=0, sticky="w", pady=(8, 0))
        out_row = self._frame(body, "card")
        out_row.grid(row=14, column=1, sticky="ew", pady=(8, 0))
        self.out_entry.pack(in_=out_row, side="left")
        ttk.Label(out_row, text="token，支持 256K / 1M", style="Hint.TLabel").pack(side="left", padx=(SPACE["sm"], 0))
        self.out_err = ttk.Label(body, text="", style="Error.TLabel")
        self.out_err.grid(row=15, column=1, sticky="w")
        self._set_error(self.ctx_err, "")
        self._set_error(self.out_err, "")

        divider = self._frame(body, "card", height=1)
        divider.grid(row=16, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        self.reason = ttk.Label(body, text="", style="Hint.TLabel")
        self.reason.grid(row=17, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.apply_btn = self._button(body, "写入并备份", self.do_apply, kind="primary", height=34)
        self.apply_btn.grid(row=18, column=0, columnspan=2, sticky="ew", pady=(SPACE["sm"], 0))

        row19 = self._frame(body, "card")
        row19.grid(row=19, column=0, columnspan=2, sticky="ew", pady=(SPACE["sm"], 0))
        row19.columnconfigure(0, weight=1)
        row19.columnconfigure(1, weight=1)
        self.preview_btn = self._button(row19, "预览变更", self.do_preview, kind="secondary", height=30)
        self.preview_btn.grid(row=0, column=0, sticky="ew", padx=(0, SPACE["xs"]))
        self.undo_btn = self._button(row19, "回滚到备份", self.do_rollback, kind="danger", height=30)
        self.undo_btn.grid(row=0, column=1, sticky="ew", padx=(SPACE["xs"], 0))

        backup_row = self._frame(body, "card")
        backup_row.grid(row=20, column=0, columnspan=2, sticky="ew", pady=(SPACE["sm"], 0))
        self.backup_lbl = ttk.Label(backup_row, text="", style="Hint.TLabel")
        self.backup_lbl.pack(side="left")
        self.open_backup_btn = self._button(backup_row, "打开备份目录", self._open_backup_dir, kind="subtle", height=24, padx=6, bg_role="card")
        self.open_backup_btn.pack(side="right")

    def _option_row(self, parent, row: int, text: str, var: tk.BooleanVar, hint: str):
        holder = self._frame(parent, "card")
        holder.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        check = ttk.Checkbutton(holder, text=text, variable=var)
        check.pack(side="left")
        label = ttk.Label(holder, text=hint, style="Hint.TLabel")
        label.pack(side="right")
        return check, label

    def _build_models(self, parent) -> None:
        card = self._card(parent, expand=True)
        card.grid(row=0, column=1, sticky="nsew", padx=(SPACE["md"], 0))

        head = self._frame(card.body, "card")
        head.pack(fill="x", padx=PAGE_PAD, pady=(12, 0))
        ttk.Label(head, text="模型", style="CardTitle.TLabel").pack(side="left")

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_changed)
        self.search = ttk.Entry(head, textvariable=self.search_var, width=24)
        self.search_clear = self._button(head, "清除", self._clear_search, kind="subtle", height=26, padx=8, bg_role="card")
        self.search_clear.pack(side="right")
        self.search.pack(side="right", padx=(0, SPACE["sm"]))
        self._attach_placeholder(self.search, self.search_var, "搜索模型 ID 或名称")

        toolbar = self._frame(card.body, "card")
        toolbar.pack(fill="x", padx=PAGE_PAD, pady=(SPACE["sm"], 0))
        for text, kind in (("全选", "all"), ("全不选", "none"), ("反选", "inv"), ("仅 Claude / Anthropic", "gw")):
            self._button(
                toolbar, text, lambda k=kind: self.sel(k), kind="subtle", height=28, padx=10, bg_role="card",
            ).pack(side="left", padx=(0, SPACE["xs"]))

        info = self._frame(card.body, "card")
        info.pack(fill="x", padx=PAGE_PAD, pady=(SPACE["sm"], 0))
        self.count = ttk.Label(info, text="共 0 个模型", style="Chip.TLabel")
        self.count.pack(side="left")
        self.fetch_info = ttk.Label(info, text="单击勾选 · 空格切换 · Ctrl+C 复制已选 ID · Ctrl+Enter 写入", style="Hint.TLabel")
        self.fetch_info.pack(side="right")

        holder = self._frame(card.body, "card", highlightthickness=1, highlightbackground=self.pal["border"])
        self._watch(holder, highlightbackground="border")
        holder.pack(fill="both", expand=True, padx=PAGE_PAD, pady=(SPACE["sm"], 14))

        self.tree = ttk.Treeview(holder, columns=[c for c, _t in _HEADINGS], show="headings", selectmode="extended")
        for column, title in _HEADINGS:
            self.tree.heading(column, text=title)
            if column in _SORTABLE:
                self.tree.heading(column, command=lambda c=column: self._sort_by(c))
        self.tree.column("sel", width=40, anchor="center", stretch=False)
        self.tree.column("no", width=52, anchor="center", stretch=False)
        self.tree.column("id", width=360, minwidth=180)
        self.tree.column("name", width=200, minwidth=120)
        self.tree.column("by", width=120, minwidth=80)
        self.tree.column("ctx", width=90, anchor="e", stretch=False)
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<ButtonPress-1>", self._on_tree_press)
        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", self._on_tree_leave)
        self.tree.bind("<space>", self._on_space)
        self.tree.bind("<Control-a>", self._on_ctrl_a)
        self.tree.bind("<Control-c>", self._on_copy_ids)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        self.prog = ttk.Progressbar(holder, mode="indeterminate", style="TProgressbar")

        self.empty = self._frame(holder, "card")
        empty_label = ttk.Label(self.empty, text="还没有模型", style="CardTitle.TLabel")
        empty_label.pack()
        ttk.Label(self.empty, text="填写端点后拉取模型列表，再勾选要写入的模型", style="Hint.TLabel").pack(pady=(4, 10))
        self._button(self.empty, "拉取模型列表", self.do_fetch, kind="primary", height=30).pack()
        self.empty.place(relx=0.5, rely=0.5, anchor="center")

    def _build_log(self) -> None:
        card = self._card(self)
        card.grid(row=2, column=0, sticky="ew", padx=PAGE_PAD, pady=(SPACE["md"], PAGE_PAD))

        head = self._frame(card.body, "card")
        head.pack(fill="x", padx=PAGE_PAD, pady=(10, 6))
        ttk.Label(head, text="日志", style="CardTitle.TLabel").pack(side="left")
        self.log_toggle_btn = self._button(head, "收起", self._toggle_log, kind="subtle", height=26, padx=8, bg_role="card")
        self.log_toggle_btn.pack(side="right")
        self._button(head, "清空", self._clear_log, kind="subtle", height=26, padx=8, bg_role="card").pack(
            side="right", padx=(0, SPACE["xs"])
        )
        self._button(head, "复制全部", self._copy_log, kind="subtle", height=26, padx=8, bg_role="card").pack(
            side="right", padx=(0, SPACE["xs"])
        )
        self.autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(head, text="自动滚动", variable=self.autoscroll).pack(side="right", padx=(0, SPACE["md"]))

        self.log_body = self._frame(card.body, "card")
        self.log_body.pack(fill="x", padx=PAGE_PAD, pady=(0, 12))
        self.log_text = tk.Text(
            self.log_body, height=6, relief="flat", wrap="word", font=self.f_small,
            padx=10, pady=8, spacing1=2, spacing3=2, highlightthickness=1,
            highlightbackground=self.pal["border"], highlightcolor=self.pal["border"],
            bg=self.pal["card"], fg=self.pal["text2"], insertbackground=self.pal["accent"],
        )
        self._watch(self.log_text, highlightbackground="border", highlightcolor="border")
        scroll = ttk.Scrollbar(self.log_body, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="x", expand=True)
        scroll.pack(side="right", fill="y")
        self.log_text.configure(state="disabled")
        if bool(self._config.get("log_collapsed")):
            self._toggle_log()

    def _restore_geometry(self) -> None:
        geometry = str(self._config.get("geometry") or "")
        match = re.match(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$", geometry)
        if not match:
            width = min(1200, max(940, self.winfo_screenwidth() - 160))
            height = min(830, max(620, self.winfo_screenheight() - 140))
            self.geometry(f"{width}x{height}+{(self.winfo_screenwidth() - width) // 2}+{max(0, (self.winfo_screenheight() - height) // 3)}")
            return
        width, height, x, y = (int(match.group(i)) for i in range(1, 5))
        width = max(940, min(width, self.winfo_screenwidth()))
        height = max(620, min(height, self.winfo_screenheight()))
        x = max(-40, min(x, self.winfo_screenwidth() - 200))
        y = max(0, min(y, self.winfo_screenheight() - 120))
        self.geometry(f"{width}x{height}+{x}+{y}")

    # ---------- 主题 ----------

    def _on_theme_selected(self, _event=None) -> None:
        mode = THEME_LABELS[self.theme_box.current()][1]
        if mode != self._theme_mode:
            self._theme_mode = mode
            self._apply_theme()
            self._config["theme"] = mode

    def _draw_status_dot(self) -> None:
        self._set_status(self._cc_running)

    # ---------- 通用交互 ----------

    def _attach_placeholder(self, entry: ttk.Entry, var: tk.StringVar, text: str) -> None:
        label = tk.Label(entry, text=text, bg=self.pal["card"], fg=self.pal["text3"], font=self.f_small, cursor="xterm")
        self._watch(label, bg="card", fg="text3")

        def sync(*_args) -> None:
            if var.get() or self.focus_get() is entry:
                label.place_forget()
            else:
                label.place(x=9, rely=0.5, anchor="w")

        var.trace_add("write", sync)
        entry.bind("<FocusIn>", sync, add="+")
        entry.bind("<FocusOut>", sync, add="+")
        label.bind("<Button-1>", lambda _e: entry.focus_set())
        sync()

    def _set_error(self, label: ttk.Label, text: str) -> None:
        if text:
            label.configure(text=text)
            label.grid()
        else:
            label.configure(text="")
            label.grid_remove()

    def _toggle_key(self) -> None:
        showing = self.key.cget("show") == ""
        self.key.configure(show="•" if showing else "")
        self.key_btn.set_text("显示" if showing else "隐藏")

    def _on_wheel(self, event) -> None:
        step = int(-1 * (event.delta / 120)) or (-1 if event.delta > 0 else 1)
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget is self.tree:
                if self._scrollable(self.tree):
                    self.tree.yview_scroll(step, "units")
                return
            if widget is self.log_text:
                if self._scrollable(self.log_text):
                    self.log_text.yview_scroll(step, "units")
                return
            if widget is self.left.canvas:
                if self.left.can_scroll():
                    self.left.canvas.yview_scroll(step, "units")
                return
            widget = getattr(widget, "master", None)

    @staticmethod
    def _scrollable(widget) -> bool:
        first, last = widget.yview()
        return first > 0.0 or last < 1.0

    def _pump(self) -> None:
        try:
            while True:
                kind, payload, extra = self.q.get_nowait()
                if kind == "log":
                    self.logln(payload)
                elif kind == "err":
                    self.logln("错误：" + payload, "err")
                    messagebox.showerror("出错", payload, parent=self)
                    if extra:
                        extra()
                elif kind == "status":
                    self._set_status(bool(payload))
                elif kind == "done" and extra:
                    extra(payload)
                elif kind == "done":
                    self.logln(str(payload))
        except queue.Empty:
            pass
        self.after(120, self._pump)

    def _work(self, fn, on_done=None, on_error=None) -> None:
        def target() -> None:
            try:
                result = fn()
            except Exception as exc:
                self.q.put(("err", str(exc), on_error))
            else:
                self.q.put(("done", result, on_done))

        threading.Thread(target=target, daemon=True).start()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_action_state()

    def _refresh_status(self) -> None:
        def job() -> None:
            self.q.put(("status", core.cc_switch_running(), None))

        threading.Thread(target=job, daemon=True).start()
        self.after(8000, self._refresh_status)

    def _set_status(self, running: bool | None) -> None:
        self._cc_running = running
        if running is None:
            self.status.configure(text="● 检查中…", fg=self.pal["text3"])
        else:
            mode, app = self.mode.get(), self.app.get()
            hot_codex = mode == "list" and app == "codex"
            if running and hot_codex:
                self.status.configure(text="● CC Switch 正在运行 · Codex 可热更新", fg=self.pal["success"])
            elif running:
                self.status.configure(text="● CC Switch 正在运行 · 请先退出再写入", fg=self.pal["danger"])
            else:
                self.status.configure(text="● CC Switch 未运行 · 可以写入", fg=self.pal["success"])
        self._update_action_state()

    # ---------- 日志 ----------

    def logln(self, message: str, level: str = "info") -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{stamp}] ", ("ts",))
        self.log_text.insert("end", message + "\n", (level,))
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 2000:
            self.log_text.delete("1.0", f"{lines - 2000}.0")
        self.log_text.configure(state="disabled")
        if self.autoscroll.get():
            self.log_text.see("end")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _copy_log(self) -> None:
        text = self.log_text.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(text)
        self.logln("日志已复制到剪贴板", "ok")

    def _toggle_log(self) -> None:
        if self.log_body.winfo_ismapped():
            self.log_body.pack_forget()
            self.log_toggle_btn.set_text("展开")
            collapsed = True
        else:
            self.log_body.pack(fill="x", padx=PAGE_PAD, pady=(0, 12))
            self.log_toggle_btn.set_text("收起")
            collapsed = False
        self._config["log_collapsed"] = collapsed

    # ---------- 连接 ----------

    def do_fetch(self) -> None:
        base = self.base_var.get().strip()
        if not base:
            self._set_error(self.base_err, "请填写端点地址")
            self.base.configure(style="Error.TEntry")
            self.base.focus_set()
            return
        self._set_error(self.base_err, "")
        self.base.configure(style="TEntry")
        key = self.key_var.get()
        fmt = ["openai", "anthropic", "google"][self.fmt.current()]
        ua = self.ua_var.get().strip() or None
        murl = self.murl_var.get().strip() or None
        full = self.full_url.get()

        self._fetching = True
        self.fetch_btn.set_enabled(False)
        self.fetch_btn.set_text("拉取中…")
        self.fetch_info.configure(text="正在拉取…")
        self.prog.place(in_=self.tree.master, x=1, y=1, relwidth=1.0, height=3)
        self.prog.start(14)
        lines: list[str] = []

        def job() -> list[core.Model]:
            models, _logs = core.fetch_models(
                base, key, is_full_url=full, models_url=murl, user_agent=ua, api_format=fmt,
                log=lambda m: (lines.append(m), self.q.put(("log", core.redact(m, [key] if key else []), None))),
            )
            core.save_models(models)
            return models

        def done(models: list[core.Model]) -> None:
            self._fetch_finished()
            self.models = models
            self.picked.clear()
            self._sort = None
            self._anchor = None
            self.render()
            hit = next((line[4:] for line in reversed(lines) if line.startswith("GET ")), "")
            self.fetch_info.configure(
                text=f"命中 {_shorten(hit, 56)} · {len(models)} 个模型" if hit else f"{len(models)} 个模型"
            )
            self.logln(f"拉取完成：共 {len(models)} 个模型", "ok")
            known = [int(getattr(m, "context", 0) or 0) for m in models]
            known = [n for n in known if n > 0]
            if known:
                self.ctx_var.set(str(max(known)))
                self.logln(f"接口返回了 {len(known)} 个模型的上下文，已按最大值 {max(known)}（{_fmt_ctx(max(known))}）填入")
            else:
                self.logln("接口没返回上下文长度，可在「写入目标」里手动填（默认 1M / 128K）")
            self._update_action_state()

        def failed() -> None:
            self._fetch_finished()
            self.fetch_info.configure(text="拉取失败")

        self._work(job, done, failed)

    def _fetch_finished(self) -> None:
        self._fetching = False
        self.prog.stop()
        self.prog.place_forget()
        self.fetch_btn.set_enabled(True)
        self.fetch_btn.set_text("拉取模型列表")
        self._update_action_state()

    # ---------- 模型列表 ----------

    def render(self) -> None:
        if not hasattr(self, "tree"):
            return
        order = sort_indices(self.models, *self._sort) if self._sort else list(range(len(self.models)))
        self.visible = filter_indices(self.models, order, self.search_var.get())
        self.tree.delete(*self.tree.get_children())
        for index in self.visible:
            model = self.models[index]
            self.tree.insert(
                "", "end", iid=str(index), tags=self._row_tags(index),
                values=(
                    "☑" if index in self.picked else "☐",
                    index + 1,
                    model.id,
                    model.display_name,
                    model.owned_by,
                    _fmt_ctx(model.context),
                ),
            )
        self._refresh_headings()
        self._refresh_count()
        self._sync_empty()

    def _row_tags(self, index: int) -> tuple[str, ...]:
        tags = []
        if self._hover_row == str(index):
            tags.append("hover")
        if index in self.picked:
            tags.append("picked")
        return tuple(tags)

    def _refresh_row(self, index: int) -> None:
        iid = str(index)
        if not self.tree.exists(iid):
            return
        model = self.models[index]
        self.tree.item(
            iid, tags=self._row_tags(index),
            values=(
                "☑" if index in self.picked else "☐",
                index + 1,
                model.id,
                model.display_name,
                model.owned_by,
                _fmt_ctx(model.context),
            ),
        )

    def _refresh_headings(self) -> None:
        for column, title in _HEADINGS:
            if self._sort and self._sort[0] == column:
                title = title + (" ▼" if self._sort[1] else " ▲")
            self.tree.heading(column, text=title)

    def _refresh_count(self) -> None:
        total = len(self.models)
        shown = len(self.visible)
        known = sum(1 for m in self.models if getattr(m, "context", 0))
        text = f"已选 {len(self.picked)} · 显示 {shown} / {total} 个模型" if shown != total else f"已选 {len(self.picked)} · 共 {total} 个模型"
        if known:
            text += f" · 接口给出 {known} 个上下文"
        focus = self.tree.focus()
        if focus and self.tree.exists(focus):
            text += f" · 当前 {_shorten(self.models[int(focus)].id, 46)}"
        self.count.configure(text=text)

    def _sync_empty(self) -> None:
        if self.models:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.5, anchor="center")
            self.empty.lift()

    def _sort_by(self, column: str) -> None:
        if self._sort and self._sort[0] == column:
            self._sort = None if self._sort[1] else (column, True)
        else:
            self._sort = (column, False)
        self.render()

    def _on_search_changed(self, *_args) -> None:
        if self._search_after:
            self.after_cancel(self._search_after)
        self._search_after = self.after(120, self.render)

    def _clear_search(self) -> None:
        self.search_var.set("")
        self.search.focus_set()

    def _on_tree_press(self, event) -> None:
        row = self.tree.identify_row(event.y)
        now = time.monotonic()
        previous_time, previous_row = self._last_press
        self._suppress_click = bool(row) and row == previous_row and (now - previous_time) < 0.4
        self._last_press = (now, row)

    def _on_tree_click(self, event) -> None:
        if self._suppress_click:
            return
        row = self.tree.identify_row(event.y)
        if not row:
            return
        index = int(row)
        shift = bool(event.state & 0x0001)
        control = bool(event.state & 0x0004)
        if shift and self._anchor is not None:
            low, high = sorted((self._anchor, index))
            target = index not in self.picked
            for other in self.visible:
                if low <= other <= high:
                    if target:
                        self.picked.add(other)
                    else:
                        self.picked.discard(other)
            for other in range(low, high + 1):
                if other in self.visible:
                    self._refresh_row(other)
        else:
            if index in self.picked:
                self.picked.discard(index)
            else:
                self.picked.add(index)
            self._anchor = index
            self._refresh_row(index)
            if not control:
                self.tree.selection_set(row)
        self._refresh_count()
        self._update_action_state()

    def _on_tree_motion(self, event) -> None:
        row = self.tree.identify_row(event.y) or None
        if row == self._hover_row:
            return
        previous = self._hover_row
        self._hover_row = row
        if previous and previous.isdigit():
            self._refresh_row(int(previous))
        if row is not None:
            self._refresh_row(int(row))

    def _on_tree_leave(self, _event) -> None:
        previous = self._hover_row
        self._hover_row = None
        if previous and previous.isdigit():
            self._refresh_row(int(previous))

    def _on_tree_select(self, _event) -> None:
        self._refresh_count()

    def _on_space(self, _event=None) -> str:
        for row in self.tree.selection():
            index = int(row)
            if index in self.picked:
                self.picked.discard(index)
            else:
                self.picked.add(index)
            self._refresh_row(index)
        self._refresh_count()
        self._update_action_state()
        return "break"

    def _on_ctrl_a(self, _event=None) -> str:
        self.sel("all")
        return "break"

    def _on_copy_ids(self, _event=None) -> str:
        if self.picked:
            ids = [self.models[i].id for i in sorted(self.picked)]
        else:
            selection = sorted(int(row) for row in self.tree.selection())
            ids = [self.models[i].id for i in selection]
        if not ids:
            self.logln("没有可复制的模型 ID", "err")
            return "break"
        self.clipboard_clear()
        self.clipboard_append("\n".join(ids))
        self.logln(f"已复制 {len(ids)} 个模型 ID 到剪贴板", "ok")
        return "break"

    def sel(self, kind: str) -> None:
        visible = self.visible
        if kind == "all":
            self.picked.update(visible)
        elif kind == "none":
            self.picked.difference_update(visible)
        elif kind == "inv":
            for index in visible:
                if index in self.picked:
                    self.picked.discard(index)
                else:
                    self.picked.add(index)
        elif kind == "gw":
            for index in visible:
                model_id = self.models[index].id.lower()
                if "claude" in model_id or "anthropic" in model_id:
                    self.picked.add(index)
                else:
                    self.picked.discard(index)
        self.render()
        self._update_action_state()

    # ---------- 写入目标 ----------

    def _current_provider_id(self) -> str | None:
        index = self.provider.current()
        if 0 <= index < len(self.provider_ids):
            return self.provider_ids[index]
        return None

    def _provider_label(self) -> str:
        index = self.provider.current()
        if 0 <= index < len(self.provider_ids):
            return self.provider.get().split("（")[0]
        return "（未选择）"

    def sync_mode(self) -> None:
        mode, app = self.mode.get(), self.app.get()
        if mode == "fanout" and app == "opencode":
            self.app.set("claude")
            app = "claude"
            self.logln("OpenCode 卡自带模型列表，「每个模型一张卡」模式不支持，已切换为 claude", "err")
        list_mode = mode == "list"
        self._set_enabled(self.opt_replace, list_mode and app == "claude")
        self._set_enabled(self.opt_disc, list_mode and app == "claude")
        self._set_enabled(self.opt_merge, list_mode and app in ("opencode", "codex"))
        self._set_enabled(self.opt_roles, mode == "fanout")
        self._set_enabled(self.ctx_entry, list_mode and app in ("opencode", "codex"))
        self._set_enabled(self.out_entry, list_mode and app == "opencode")
        self._set_enabled(self.prefix, mode == "fanout")
        self._validate_params()
        self.load_providers()
        self._set_status(self._cc_running)

    def _set_enabled(self, widget: ttk.Widget, enabled: bool) -> None:
        widget.configure(state="normal" if enabled else "disabled")

    def load_providers(self) -> None:
        app = self.app.get()
        previous = self._current_provider_id()

        def job() -> list[dict]:
            try:
                return core.list_providers(app)
            except Exception as exc:
                self.q.put(("log", f"读取供应商卡失败：{exc}", None))
                return []

        def done(rows: list[dict]) -> None:
            self.provider_ids = [row["id"] for row in rows]
            self.provider.configure(values=[f"{row['name']}（{row['id']}）" for row in rows])
            if previous in self.provider_ids:
                self.provider.current(self.provider_ids.index(previous))
            elif self.provider_ids:
                self.provider.current(0)
            else:
                self.provider.set("")
            self._update_action_state()

        self._work(job, done)

    def _select_provider(self, provider_id: str) -> None:
        if provider_id in self.provider_ids:
            self.provider.current(self.provider_ids.index(provider_id))

    def _validate_params(self) -> None:
        mode, app = self.mode.get(), self.app.get()
        ctx_active = mode == "list" and app in ("opencode", "codex")
        out_active = mode == "list" and app == "opencode"

        self._ctx_ok, self._out_ok = True, True
        self.ctx_entry.configure(style="TEntry")
        self.out_entry.configure(style="TEntry")
        self._set_error(self.ctx_err, "")
        self._set_error(self.out_err, "")

        if ctx_active:
            try:
                parse_tokens(self.ctx_var.get(), field="上下文长度")
            except ValueError as exc:
                self._ctx_ok = False
                self.ctx_entry.configure(style="Error.TEntry")
                self._set_error(self.ctx_err, str(exc))
        if out_active:
            try:
                parse_tokens(self.out_var.get(), field="最大输出")
            except ValueError as exc:
                self._out_ok = False
                self.out_entry.configure(style="Error.TEntry")
                self._set_error(self.out_err, str(exc))
        self._update_action_state()

    def _fill_max_ctx(self) -> None:
        known = [int(getattr(m, "context", 0) or 0) for m in self.models]
        known = [n for n in known if n > 0]
        if not known:
            messagebox.showinfo("上下文", "接口没有返回任何上下文长度，已填入默认值，可手动修改。", parent=self)
            self.ctx_var.set(str(DEFAULT_CONTEXT))
            return
        top = max(known)
        self.ctx_var.set(str(top))
        self.logln(f"已取接口返回的最大上下文：{top}（{_fmt_ctx(top)}）")

    def _action_reason(self) -> str:
        if self._busy:
            return "正在处理，请稍候"
        if not self.picked:
            return "先勾选要写入的模型"
        mode, app = self.mode.get(), self.app.get()
        provider = self._current_provider_id()
        if mode == "fanout" and not provider:
            return "先选择模板卡，或点「新建」创建一张"
        if mode == "list" and app in ("claude", "opencode") and not provider:
            return "先选择目标供应商卡，或点「新建」创建一张"
        if self._cc_running and not (mode == "list" and app == "codex"):
            return "请先完全退出 CC Switch（含托盘图标）"
        if not self._ctx_ok or not self._out_ok:
            return "请修正「参数」里的输入"
        return ""

    def _update_action_state(self) -> None:
        if not hasattr(self, "apply_btn"):
            return
        reason = self._action_reason()
        self.reason.configure(text=reason)
        self.apply_btn.set_enabled(not reason)
        self.preview_btn.set_enabled(bool(self.picked) and not self._busy)
        self.undo_btn.set_enabled(bool(self.last_backups) and not self._busy)
        self.new_btn.set_enabled(not self._busy)
        self.del_btn.set_enabled(not self._busy)
        self.fetch_btn.set_enabled(not self._busy and not self._fetching)

    def chosen(self) -> list[core.Model]:
        return [self.models[i] for i in sorted(self.picked)]

    def payload(self) -> dict:
        return {
            "mode": self.mode.get(),
            "app": self.app.get(),
            "providerId": self._current_provider_id(),
            "models": [m.to_dict() for m in self.chosen()],
            "replaceBuiltIn": self.replace.get(),
            "gatewayDiscovery": self.disc.get(),
            "merge": self.merge.get(),
            "fillRoles": self.roles.get(),
            "namePrefix": self.prefix_var.get().strip(),
            "context": parse_tokens(self.ctx_var.get(), field="上下文长度"),
            "output": parse_tokens(self.out_var.get(), field="最大输出"),
        }

    # ---------- 预览与写入 ----------

    def do_preview(self) -> None:
        if not self.picked:
            messagebox.showwarning("未选择", "请先勾选模型", parent=self)
            return
        if not self._ctx_ok or not self._out_ok:
            messagebox.showwarning("参数有误", "请先修正「参数」里的输入", parent=self)
            return
        body = self.payload()
        self._work(lambda: _preview_summary(body), self._show_preview)

    def _show_preview(self, text: str) -> None:
        win, outer = self._dialog("变更预览", 720, 580)
        body = self._frame(outer, "card")
        body.pack(fill="both", expand=True)

        view = tk.Text(
            body, relief="flat", wrap="word", font=self.f_small, padx=10, pady=8,
            highlightthickness=1, highlightbackground=self.pal["border"],
            bg=self.pal["card"], fg=self.pal["text"], insertbackground=self.pal["accent"],
        )
        self._watch(view, highlightbackground="border", bg="card", fg="text")
        scroll = ttk.Scrollbar(body, orient="vertical", command=view.yview)
        view.configure(yscrollcommand=scroll.set)
        view.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        view.insert("end", text)
        view.configure(state="disabled")

        bar = self._frame(outer, "card")
        bar.pack(fill="x", pady=(SPACE["md"], 0))
        self._button(bar, "关闭", win.destroy, kind="secondary", height=30).pack(side="right")
        self._button(bar, "复制内容", lambda: self._copy_text(text), kind="subtle", height=30).pack(
            side="right", padx=(0, SPACE["sm"])
        )
        self._button(bar, "写入并备份", lambda: (win.destroy(), self.do_apply()), kind="primary", height=30).pack(
            side="right", padx=(0, SPACE["sm"])
        )

    def _copy_text(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self.logln("已复制到剪贴板", "ok")

    def _confirm_text(self, body: dict) -> str:
        mode_name = "一张卡 + 模型列表" if body["mode"] == "list" else "每个模型一张卡"
        lines = [f"应用：{body['app']}", f"模式：{mode_name}"]
        if body["mode"] == "list" and body["app"] == "codex" and not body["providerId"]:
            lines.append("目标：只更新 ~/.codex 模型目录（未选择供应商卡）")
        else:
            lines.append(f"目标卡：{self._provider_label()}")
        lines.append(f"模型：{len(body['models'])} 个")
        if body["mode"] == "list" and body["app"] in ("opencode", "codex"):
            lines.append(f"上下文：{_fmt_ctx(body['context'])}")
        if body["mode"] == "list" and body["app"] == "opencode":
            lines.append(f"最大输出：{_fmt_ctx(body['output'])}")
        lines.append("")
        lines.append("写入前会自动备份，可用「回滚到备份」还原。")
        return "\n".join(lines)

    def do_apply(self) -> None:
        reason = self._action_reason()
        if reason:
            messagebox.showwarning("还不能写入", reason, parent=self)
            return
        body = self.payload()
        if not messagebox.askyesno("确认写入", self._confirm_text(body), parent=self):
            return
        self._set_busy(True)
        self.apply_btn.set_text("写入中…")

        def done(result: dict) -> None:
            self._set_busy(False)
            self.apply_btn.set_text("写入并备份")
            self._after_apply(result)

        def failed() -> None:
            self._set_busy(False)
            self.apply_btn.set_text("写入并备份")

        self._work(lambda: _apply(body), done, failed)

    def _after_apply(self, result: dict) -> None:
        self.logln("写入成功：" + result.get("summary", ""), "ok")
        backups: list[tuple[str, str]] = []
        if result.get("dbBackup"):
            backups.append((str(result["dbBackup"]), "db"))
        if result.get("catalogBackup"):
            backups.append((str(result["catalogBackup"]), "catalog"))
        if not backups and result.get("backup"):
            target = "catalog" if result.get("mode") == "codex" else "db"
            backups.append((str(result["backup"]), target))
        if backups:
            self.last_backups = backups
            labels = [path.replace("\\", "/").rsplit("/", 1)[-1] for path, _t in backups]
            self.backup_lbl.configure(text="上次备份：" + "；".join(labels))
        self._update_action_state()
        self._refresh_status()

    def _open_backup_dir(self) -> None:
        if not self.last_backups:
            return
        folder = Path(self.last_backups[0][0]).parent
        os.startfile(str(folder))

    def do_rollback(self) -> None:
        if not self.last_backups:
            return
        if not messagebox.askyesno("回滚", "回滚到上一次写入前的备份？", parent=self):
            return
        backups = list(self.last_backups)

        def job() -> list[dict]:
            return [core.rollback(path, target) for path, target in backups]

        def done(result: list[dict]) -> None:
            self.logln("已回滚：" + "；".join(item["restored"] for item in result), "ok")
            self.last_backups = []
            self.backup_lbl.configure(text="")
            self._update_action_state()

        self._work(job, done)

    # ---------- 对话框 ----------

    def _dialog(self, title: str, width: int, height: int) -> tuple[tk.Toplevel, tk.Frame]:
        win = tk.Toplevel(self)
        win.title(title)
        win.configure(bg=self.pal["bg"])
        win.transient(self)
        win.resizable(False, False)
        outer = self._frame(win, "bg")
        outer.pack(fill="both", expand=True, padx=PAGE_PAD, pady=PAGE_PAD)
        self._center(win, width, height)
        win.grab_set()
        win.bind("<Escape>", lambda _e: win.destroy())
        return win, outer

    def _center(self, win: tk.Toplevel, width: int, height: int) -> None:
        win.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - width) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - height) // 2)
        x = max(0, min(x, self.winfo_screenwidth() - width - 8))
        y = max(0, min(y, self.winfo_screenheight() - height - 40))
        win.geometry(f"{width}x{height}+{x}+{y}")

    def new_card_dialog(self) -> None:
        win, outer = self._dialog("新建供应商卡", 520, 430)
        card = self._card(outer)
        card.pack(fill="both", expand=True)
        head = self._frame(card.body, "card")
        head.pack(fill="x", padx=PAGE_PAD, pady=(12, 2))
        ttk.Label(head, text="新建供应商卡", style="CardTitle.TLabel").pack(side="left")

        body = self._frame(card.body, "card")
        body.pack(fill="both", expand=True, padx=PAGE_PAD, pady=(6, 14))
        body.columnconfigure(1, weight=1)

        app_var = tk.StringVar(value=self.app.get() if self.app.get() != "opencode" else "claude")
        name_var = tk.StringVar()
        url_var = tk.StringVar(value=self.base_var.get().strip())
        key_var = tk.StringVar(value=self.key_var.get())
        model_var = tk.StringVar()

        ttk.Label(body, text="应用", style="Form.TLabel").grid(row=0, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(body, width=14, state="readonly", textvariable=app_var,
                     values=["claude", "codex", "opencode"]).grid(row=0, column=1, sticky="w", pady=(6, 0))
        ttk.Label(body, text="名称", style="Form.TLabel").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(body, textvariable=name_var).grid(row=1, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(body, text="端点", style="Form.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(body, textvariable=url_var).grid(row=2, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(body, text="Key", style="Form.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(body, textvariable=key_var, show="•").grid(row=3, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(body, text="默认模型", style="Form.TLabel").grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(body, textvariable=model_var).grid(row=4, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(body, text="留空则先建卡，再回到主界面用模型列表写入", style="Hint.TLabel").grid(
            row=5, column=1, sticky="w", pady=(6, 0)
        )
        error = ttk.Label(body, text="", style="Error.TLabel")
        error.grid(row=6, column=1, sticky="w", pady=(6, 0))
        self._set_error(error, "")

        bar = self._frame(body, "card")
        bar.grid(row=7, column=0, columnspan=2, sticky="e", pady=(16, 0))
        self._button(bar, "取消", win.destroy, kind="secondary", height=30).pack(side="right")
        create_btn = self._button(bar, "创建", None, kind="primary", height=30)
        create_btn.pack(side="right", padx=(0, SPACE["sm"]))

        def submit() -> None:
            name = name_var.get().strip()
            url = url_var.get().strip()
            if not name:
                self._set_error(error, "请填写卡片名称")
                return
            if not url:
                self._set_error(error, "请填写端点地址")
                return
            self._set_error(error, "")
            create_btn.set_enabled(False)

            def job() -> dict:
                result = core.create_provider(app_var.get(), name, url, key_var.get().strip(), model=model_var.get().strip())
                result["summary"] = f"已新建 {result['app']} 卡「{result['name']}」"
                return result

            def done(result: dict) -> None:
                self.logln("新建成功：" + result["summary"], "ok")
                if result.get("backup"):
                    self.last_backups = [(str(result["backup"]), "db")]
                    self.backup_lbl.configure(text="上次备份：" + str(result["backup"]).replace("\\", "/").rsplit("/", 1)[-1])
                self.app.set(result["app"])
                self.sync_mode()
                self.after(400, lambda: self._select_provider(result["id"]))
                win.destroy()
                self._update_action_state()

            def failed() -> None:
                create_btn.set_enabled(True)

            self._work(job, done, failed)

        create_btn.command = submit

    def delete_card_dialog(self) -> None:
        app = self.app.get()
        try:
            rows = core.list_providers(app)
        except Exception as exc:
            messagebox.showwarning("读取失败", f"读取供应商卡失败：{exc}", parent=self)
            return
        win, outer = self._dialog(f"删除 {app} 卡", 560, 480)
        card = self._card(outer, expand=True)
        card.pack(fill="both", expand=True)
        head = self._frame(card.body, "card")
        head.pack(fill="x", padx=PAGE_PAD, pady=(12, 2))
        ttk.Label(head, text=f"删除 {app} 卡", style="CardTitle.TLabel").pack(side="left")
        ttk.Label(head, text="可多选", style="Hint.TLabel").pack(side="left", padx=(10, 0))

        body = self._frame(card.body, "card")
        body.pack(fill="both", expand=True, padx=PAGE_PAD, pady=(6, 14))

        query = tk.StringVar()
        search = ttk.Entry(body, textvariable=query)
        search.pack(fill="x")
        self._attach_placeholder(search, query, "搜索名称或 ID")

        holder = self._frame(body, "card", highlightthickness=1, highlightbackground=self.pal["border"])
        self._watch(holder, highlightbackground="border")
        holder.pack(fill="both", expand=True, pady=(SPACE["sm"], 0))
        tree = ttk.Treeview(holder, columns=("name", "id", "current"), show="headings", selectmode="extended")
        tree.heading("name", text="名称")
        tree.heading("id", text="ID")
        tree.heading("current", text="状态")
        tree.column("name", width=180)
        tree.column("id", width=260)
        tree.column("current", width=80, anchor="center", stretch=False)
        scroll = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        force = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, text="强制删除（含正在使用的卡）", variable=force).pack(anchor="w", pady=(SPACE["sm"], 0))
        error = ttk.Label(body, text="", style="Error.TLabel")
        error.pack(anchor="w", pady=(SPACE["xs"], 0))
        self._set_error(error, "")

        bar = self._frame(body, "card")
        bar.pack(fill="x", pady=(SPACE["md"], 0))
        self._button(bar, "取消", win.destroy, kind="secondary", height=30).pack(side="right")
        delete_btn = self._button(bar, "删除选中的卡", None, kind="danger", height=30)
        delete_btn.pack(side="right", padx=(0, SPACE["sm"]))
        delete_btn.set_enabled(False)

        def refresh_tree(*_args) -> None:
            q = query.get().strip().lower()
            tree.delete(*tree.get_children())
            for index, row in enumerate(rows):
                if q and q not in row["name"].lower() and q not in str(row["id"]).lower():
                    continue
                tree.insert(
                    "", "end", iid=str(index),
                    values=(row["name"], row["id"], "当前使用" if int(row["is_current"] or 0) else ""),
                )
            update_state()

        def selected_rows() -> list[dict]:
            return [rows[int(iid)] for iid in tree.selection()]

        def update_state(*_args) -> None:
            picked = selected_rows()
            blocked = [r for r in picked if int(r["is_current"] or 0) and not force.get()]
            if blocked:
                self._set_error(error, "选中的卡正在使用，需要勾选「强制删除」")
            else:
                self._set_error(error, "")
            delete_btn.set_text(f"删除 {len(picked)} 张卡" if picked else "删除选中的卡")
            delete_btn.set_enabled(bool(picked) and not blocked)

        def submit() -> None:
            picked = selected_rows()
            if not picked:
                return
            ids = [str(r["id"]) for r in picked]
            names = [str(r["name"]) for r in picked]
            delete_btn.set_enabled(False)
            delete_btn.set_text("删除中…")

            def job() -> dict:
                result = core.delete_providers(app, ids, force=force.get())
                result["summary"] = f"已删除 {result['deleted']} 张卡：" + "、".join(result["names"])
                return result

            def done(result: dict) -> None:
                self.logln(result["summary"], "ok")
                if result.get("backup"):
                    self.last_backups = [(str(result["backup"]), "db")]
                    self.backup_lbl.configure(
                        text="上次备份：" + str(result["backup"]).replace("\\", "/").rsplit("/", 1)[-1]
                    )
                self.load_providers()
                win.destroy()

            def failed() -> None:
                update_state()

            self._work(job, done, failed)

        query.trace_add("write", refresh_tree)
        tree.bind("<<TreeviewSelect>>", update_state)
        force.trace_add("write", update_state)
        delete_btn.command = submit
        refresh_tree()

    def _on_close(self) -> None:
        self._config["theme"] = self._theme_mode
        self._config["geometry"] = self.geometry()
        save_ui_config(self._config_path, self._config)
        self.destroy()


# ---------------------------------------------------------------- 预览文本


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
                    input_modalities=list(item.get("input_modalities") or []),
                    reasoning_levels=list(item.get("reasoning_levels") or []),
                    default_reasoning_level=str(item.get("default_reasoning_level") or ""),
                )
            )
    return [m for m in out if m.id]


def _model_lines(models: list[core.Model], limit: int = 12) -> list[str]:
    lines = [f"  {n}. {m.id}" for n, m in enumerate(models[:limit], 1)]
    if len(models) > limit:
        lines.append(f"  … 其余 {len(models) - limit} 个")
    return lines


def _preview_summary(body: dict) -> str:
    models = _models_from(body)
    if not models:
        raise ValueError("没有选择任何模型")
    mode = body.get("mode", "list")
    app = body.get("app", "claude")
    context = int(body.get("context") or 0)
    known = sum(1 for m in models if getattr(m, "context", 0))

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
        names = [card["name"] for card in cards]
        lines = [
            f"目标：以「{template['name']}」为模板，在 {app} 下新建 {len(names)} 张卡",
            f"卡名前缀：{body.get('namePrefix') or '（无）'}",
            f"角色槽位：{'同时填写 Sonnet / Opus / Haiku' if body.get('fillRoles', True) else '不填写'}",
            "",
            f"将新建的卡（{len(names)} 张）：",
        ]
        lines.extend(f"  {n}. {name}" for n, name in enumerate(names[:12], 1))
        if len(names) > 12:
            lines.append(f"  … 其余 {len(names) - 12} 张")
        lines.extend(["", "写入前会自动备份数据库，可用「回滚到备份」还原。"])
        return "\n".join(lines)

    if mode == "list" and app == "opencode":
        provider = core.get_provider("opencode", body.get("providerId"))
        if not provider:
            raise ValueError("找不到 OpenCode 供应商卡")
        existing = json.loads(provider["settings_config"]).get("models") or {}
        built = core.build_opencode_models(
            models,
            existing=existing if isinstance(existing, dict) else None,
            merge=bool(body.get("merge")),
            context=context or DEFAULT_CONTEXT,
            output=int(body.get("output") or DEFAULT_OUTPUT),
        )
        action = "合并进" if body.get("merge") else "覆盖为"
        note = (
            f"接口返回值用于 {known} 个模型，其余使用手动值" if known else "接口未返回，全部使用手动值"
        )
        lines = [
            f"目标：OpenCode 卡「{provider['name']}」的模型列表",
            f"操作：{action} {len(built)} 个模型",
            f"上下文：{_fmt_ctx(context or DEFAULT_CONTEXT)}（{note}）",
            f"最大输出：{_fmt_ctx(int(body.get('output') or DEFAULT_OUTPUT))}",
            "",
            f"模型列表（{len(built)} 个，显示前 12 个）：",
        ]
        lines.extend(f"  {n}. {model_id}" for n, model_id in enumerate(list(built)[:12], 1))
        if len(built) > 12:
            lines.append(f"  … 其余 {len(built) - 12} 个")
        lines.extend(["", "写入前会自动备份数据库，可用「回滚到备份」还原。"])
        return "\n".join(lines)

    if mode == "list" and app == "codex":
        provider_id = body.get("providerId")
        provider = core.get_provider("codex", provider_id) if provider_id else None
        existing_card = None
        if provider:
            existing_card = json.loads(provider["settings_config"]).get("modelCatalog")
        existing_catalog = json.loads(core.CODEX_CATALOG.read_text(encoding="utf-8")) if core.CODEX_CATALOG.exists() else None
        template = None
        if isinstance(existing_catalog, dict) and existing_catalog.get("models"):
            template = existing_catalog["models"][0]
        catalog = core.build_codex_catalog(
            models, template, context=context, existing=existing_catalog, merge=bool(body.get("merge")),
        )
        card_catalog = (
            core.build_codex_model_catalog(models, existing=existing_card, merge=bool(body.get("merge")))
            if provider else None
        )
        base = existing_card if provider else existing_catalog
        key = "model" if provider else "slug"
        incoming = card_catalog if provider else core.build_codex_catalog(models, template, context=context)
        _merged, stats = core.merge_json_entries(base, incoming, key=key, merge=bool(body.get("merge")))
        action = "合并新增" if body.get("merge") else "覆盖写入"
        lines = [
            f"目标：{'Codex 卡「' + provider['name'] + '」和 ' if provider else ''}模型目录 {core.CODEX_CATALOG}",
            f"操作：{action} {stats['added']} 个模型，保留 {stats['preserved']} 个",
            f"上下文：{_fmt_ctx(context) or context}（接口给出 {known} 个）",
            f"卡内模型：{len(card_catalog['models']) if card_catalog else 0} 个 · 目录模型：{len(catalog['models'])} 个",
            "",
            f"模型列表（{len(models)} 个，显示前 12 个）：",
        ]
        lines.extend(_model_lines(models))
        lines.extend(["", "写入前会自动备份数据库与模型目录，可用「回滚到备份」还原。"])
        return "\n".join(lines)

    provider = core.get_provider("claude", body.get("providerId"))
    if not provider:
        raise ValueError("找不到 Claude 供应商卡")
    picker = core.build_model_picker(models, bool(body.get("replaceBuiltIn", True)))
    lines = [
        f"目标：Claude 卡「{provider['name']}」的 modelPicker",
        f"操作：写入 {len(picker['options'])} 行"
        + ("，并覆盖内置模型列表" if bool(body.get("replaceBuiltIn", True)) else "，保留内置模型列表"),
    ]
    if body.get("gatewayDiscovery"):
        lines.append("附加：开启 CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1")
    lines.extend(["", f"模型列表（{len(models)} 个，显示前 12 个）："])
    lines.extend(_model_lines(models))
    lines.extend(["", "写入前会自动备份数据库，可用「回滚到备份」还原。"])
    return "\n".join(lines)


def _apply(body: dict) -> dict:
    models = _models_from(body)
    if not models:
        raise ValueError("没有选择任何模型")
    mode = body.get("mode", "list")
    app = body.get("app", "claude")
    hot_codex = mode == "list" and app == "codex"
    if core.cc_switch_running() and not hot_codex:
        raise RuntimeError("CC Switch 正在运行，请先完全退出后再写入")

    provider_id = body.get("providerId")

    if mode == "fanout":
        result = core.apply_fanout(
            provider_id, models, app_type=app,
            fill_roles=bool(body.get("fillRoles", True)),
            name_prefix=str(body.get("namePrefix") or ""),
        )
        result["summary"] = f"已在 {result['app']} 下新建 {result['rows']} 张供应商卡"
        return result

    if app == "opencode":
        result = core.apply_opencode(
            provider_id, models, merge=bool(body.get("merge")),
            context=int(body.get("context") or DEFAULT_CONTEXT),
            output=int(body.get("output") or DEFAULT_OUTPUT),
        )
        result["summary"] = f"已把 {result['rows']} 个模型写入 OpenCode 卡「{result['provider']}」的模型列表"
        return result

    if app == "codex":
        result = core.apply_codex(
            models, provider_id,
            context=int(body.get("context") or 0),
            merge=bool(body.get("merge")),
        )
        action = "合并新增" if result["merged"] else "覆盖写入"
        target = f"Codex 卡「{result['provider']}」和模型目录" if result.get("provider") else "Codex 模型目录"
        result["summary"] = (
            f"已{action} {result['added']} 个模型到{target}，保留 {result['preserved']} 个；"
            f"共 {result['cardRows'] or result['catalogRows']} 个模型"
        )
        return result

    result = core.apply_claude(
        provider_id, models,
        replace_builtin=bool(body.get("replaceBuiltIn", True)),
        gateway_discovery=bool(body.get("gatewayDiscovery")),
    )
    result["summary"] = f"已把 {result['rows']} 个模型写入 Claude 卡「{result['provider']}」的 modelPicker"
    return result


def main() -> None:
    _enable_dpi_awareness()
    App().mainloop()


if __name__ == "__main__":
    main()
