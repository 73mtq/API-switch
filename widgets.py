"""自绘部件：圆角按钮、卡片容器与可滚动纵向容器。"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from theme import CARD_RADIUS, CONTROL_RADIUS


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
        w = self.winfo_width() if self.winfo_width() > 1 else self._width
        h = self.winfo_height() if self.winfo_height() > 1 else self._height
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
        self._shape: int | None = None
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
        shape = rounded_rect(
            self.canvas, 1, 1, max(2, width - 1), max(2, height - 1), CARD_RADIUS,
            fill=self.pal["card"], outline=self.pal["border"],
        )
        self._shape = shape
        self.canvas.tag_lower(shape)

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
