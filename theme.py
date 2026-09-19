"""配色、对比度计算、系统主题检测与布局常量。"""

from __future__ import annotations

import sys

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

THEME_LABELS = (("跟随系统", "system"), ("浅色", "light"), ("深色", "dark"))

if sys.platform == "win32":
    import ctypes
    import winreg


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


def system_theme() -> str:
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
    return dict(LIGHT if system_theme() == "light" else DARK)


def enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
