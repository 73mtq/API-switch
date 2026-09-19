"""token 数值解析、上下文格式化与模型列表的排序和过滤。"""

from __future__ import annotations

import re

import ccs_models as core

DEFAULT_CONTEXT = 1_000_000
DEFAULT_OUTPUT = 131_072

_TOKENS_RE = re.compile(r"^(\d+(?:\.\d+)?)([km]?)$")


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


def fmt_ctx(n: int) -> str:
    n = int(n or 0)
    if not n:
        return ""
    if n >= 1_000_000:
        return f"{n / 1_000_000:g}M"
    if n >= 1000:
        return f"{n / 1000:g}K"
    return str(n)


def shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = max(1, limit - 12)
    return text[:head] + "…" + text[-10:]


def model_sort_value(model: core.Model, column: str) -> str | int:
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
