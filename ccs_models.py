"""CC Switch 模型批量导入工具：只读取 /v1/models 列表，不发送任何推理请求。"""

from __future__ import annotations

import argparse
import copy
import getpass
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

HOME = Path.home()
CC_DIR = HOME / ".cc-switch"
DB_PATH = CC_DIR / "cc-switch.db"
BACKUP_DIR = CC_DIR / "backups"
CODEX_DIR = HOME / ".codex"
CODEX_CATALOG = CODEX_DIR / "cc-switch-model-catalog.json"

if getattr(sys, "frozen", False):
    OUT_DIR = Path(sys.executable).resolve().parent / "out"
else:
    OUT_DIR = Path(__file__).resolve().parent / "out"

KNOWN_COMPAT_SUFFIXES = [
    "/api/claudecode",
    "/api/anthropic",
    "/apps/anthropic",
    "/api/coding",
    "/claudecode",
    "/anthropic",
    "/step_plan",
    "/coding",
    "/claude",
]

PROCESS_NAMES = ["CC Switch.exe", "cc-switch.exe", "CC-Switch.exe", "cc-switch"]


@dataclass
class Model:
    id: str
    display_name: str = ""
    description: str = ""
    owned_by: str = ""
    context: int = 0  # 接口返回的上下文长度（0 = 未知）
    output: int = 0  # 接口返回的最大输出（0 = 未知）
    input_modalities: list[str] = field(default_factory=list)
    reasoning_levels: list[str] = field(default_factory=list)
    default_reasoning_level: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


LogFn = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


def redact(text: str, secrets: list[str]) -> str:
    out = text
    for s in secrets:
        if s and len(s) >= 4:
            out = out.replace(s, "***")
    return out


def ends_with_version_segment(url: str) -> bool:
    last = url.rsplit("/", 1)[-1]
    if not last.startswith("v"):
        return False
    digits = last[1:]
    return bool(digits) and all(c.isdigit() and c.isascii() for c in digits)


def strip_compat_suffix(base_url: str) -> str | None:
    for suffix in KNOWN_COMPAT_SUFFIXES:
        if base_url.endswith(suffix):
            return base_url[: -len(suffix)]
    return None


def build_candidates(base_url: str, is_full_url: bool = False, override: str | None = None) -> list[str]:
    if override and override.strip():
        return [override.strip()]

    trimmed = (base_url or "").strip().rstrip("/")
    if not trimmed:
        raise ValueError("端点地址为空")

    candidates: list[str] = []

    if is_full_url:
        idx = trimmed.find("/v1/")
        if idx != -1:
            candidates.append(trimmed[:idx] + "/v1/models")
        else:
            idx = trimmed.rfind("/")
            root = trimmed[:idx] if idx != -1 else ""
            if root and "://" in root and len(root) > root.find("://") + 3:
                candidates.append(root + "/v1/models")
        if not candidates:
            raise ValueError("无法从完整 URL 推导模型列表地址")
        return _dedupe(candidates)

    if ends_with_version_segment(trimmed):
        candidates.append(trimmed + "/models")
        if not trimmed.endswith("/v1"):
            candidates.append(trimmed + "/v1/models")
    else:
        candidates.append(trimmed + "/v1/models")

    stripped = strip_compat_suffix(trimmed)
    if stripped:
        root = stripped.rstrip("/")
        if root and "://" in root:
            candidates.append(root + "/v1/models")
            candidates.append(root + "/models")

    return _dedupe(candidates)


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    for i in items:
        if i not in out:
            out.append(i)
    return out


CONTEXT_KEYS = (
    "context_window", "contextWindow", "context_length", "contextLength",
    "max_context_tokens", "maxContextTokens", "max_context_window", "maxContextWindow",
    "context_tokens", "contextTokens", "context_size", "max_input_tokens",
    "maxInputTokens", "input_token_limit", "inputTokenLimit", "context",
)
OUTPUT_KEYS = (
    "max_output_tokens", "maxOutputTokens", "output_token_limit", "outputTokenLimit",
    "max_tokens", "maxTokens", "output_tokens", "outputTokens", "output",
)


def _as_int(value: Any) -> int:
    raw = str(value).strip().lower().replace(",", "").replace("_", "").replace(" ", "")
    if not raw:
        return 0
    try:
        mult = 1
        if raw.endswith("k"):
            raw, mult = raw[:-1], 1_000
        elif raw.endswith("m"):
            raw, mult = raw[:-1], 1_000_000
        n = int(float(raw) * mult)
    except Exception:
        return 0
    return n if n > 0 else 0


def _pick_int(item: dict[str, Any], keys: tuple[str, ...]) -> int:
    """从平铺字段或 limits / capabilities 等嵌套结构里读一个正整数。"""
    nested = []
    for key in ("limits", "capabilities", "model_limits", "context"):
        val = item.get(key)
        if isinstance(val, dict):
            nested.append(val)
    for src in [item, *nested]:
        for k in keys:
            if k in src:
                n = _as_int(src[k])
                if n:
                    return n
    return 0


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, dict):
        return [str(k) for k, enabled in value.items() if enabled]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v]
    return []


def parse_models_response(payload: Any) -> list[Model]:
    if not isinstance(payload, dict):
        return []

    raw: list[Any] = []
    zhipu_style = False
    data = payload.get("data")
    if isinstance(data, list):
        raw = data
    elif isinstance(payload.get("models"), list):
        raw = payload["models"]
        zhipu_style = True

    models: list[Model] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        if zhipu_style:
            mid = str(item.get("slug") or item.get("id") or "")
        else:
            mid = str(item.get("id") or item.get("name") or item.get("slug") or "")
        mid = mid.strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        capabilities = item.get("capabilities")
        capabilities = capabilities if isinstance(capabilities, dict) else {}
        input_caps = capabilities.get("input")
        variants = item.get("variants")
        reasoning_levels = _string_list(item.get("reasoning_levels"))
        if not reasoning_levels and isinstance(variants, dict):
            reasoning_levels = list(variants)
        models.append(
            Model(
                id=mid,
                display_name=str(item.get("display_name") or item.get("displayName") or ""),
                description=str(item.get("description") or ""),
                owned_by=str(item.get("owned_by") or item.get("ownedBy") or ""),
                context=_pick_int(item, CONTEXT_KEYS),
                output=_pick_int(item, OUTPUT_KEYS),
                input_modalities=_string_list(item.get("input_modalities") or input_caps),
                reasoning_levels=reasoning_levels,
                default_reasoning_level=str(
                    item.get("default_reasoning_level") or item.get("defaultReasoningLevel") or ""
                ),
            )
        )
    models.sort(key=lambda m: m.id)
    return models


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        raise urllib.error.HTTPError(req.full_url, code, f"redirect to {newurl}", headers, fp)


def fetch_models(
    base_url: str,
    api_key: str,
    *,
    is_full_url: bool = False,
    models_url: str | None = None,
    user_agent: str | None = None,
    api_format: str | None = None,
    timeout: float = 15.0,
    log: LogFn = _noop,
) -> tuple[list[Model], list[str]]:
    candidates = build_candidates(base_url, is_full_url, models_url)
    secrets = [api_key] if api_key else []
    logs: list[str] = []
    last_error = ""

    opener = urllib.request.build_opener(_NoRedirect)

    for url in candidates:
        target = url
        if "?" not in target:
            target = f"{target}?limit=1000"
        headers = {"Accept": "application/json"}
        if api_key:
            if api_format == "anthropic":
                headers["x-api-key"] = api_key
            elif api_format == "google":
                headers["x-goog-api-key"] = api_key
            else:
                headers["Authorization"] = f"Bearer {api_key}"
        if user_agent:
            headers["User-Agent"] = user_agent

        logs.append(f"GET {redact(target, secrets)}")
        log(logs[-1])

        req = urllib.request.Request(target, headers=headers, method="GET")
        try:
            with opener.open(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status = exc.code
            if status in (301, 302, 303, 307, 308):
                msg = f"{status} 重定向（视为失败）"
            else:
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:200]
                except Exception:
                    detail = ""
                msg = f"HTTP {status} {redact(detail, secrets)}".strip()
            logs.append(f"  → {msg}")
            log(logs[-1])
            if status in (404, 405):
                last_error = msg
                continue
            raise RuntimeError(f"{target} 请求失败：{msg}")
        except Exception as exc:
            msg = f"请求失败：{exc}"
            logs.append(f"  → {msg}")
            log(logs[-1])
            raise RuntimeError(f"{target} {msg}")

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{target} 返回内容不是 JSON：{exc}\n前 200 字符：{body[:200]}")

        models = parse_models_response(payload)
        logs.append(f"  → 200，解析到 {len(models)} 个模型")
        log(logs[-1])
        return models, logs

    raise RuntimeError(f"所有候选地址都失败：{last_error or '未知错误'}")


def open_ro(db_path: Path = DB_PATH) -> sqlite3.Connection:
    uri = "file:" + str(db_path).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def open_rw(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def list_providers(app_type: str, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    conn = open_ro(db_path)
    try:
        rows = conn.execute(
            "SELECT id, name, is_current, app_type FROM providers WHERE app_type=? ORDER BY name",
            (app_type,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_provider(app_type: str, provider_id: str, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    conn = open_ro(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM providers WHERE app_type=? AND id=?", (app_type, provider_id)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_endpoints(app_type: str, provider_id: str, db_path: Path = DB_PATH) -> list[str]:
    conn = open_ro(db_path)
    try:
        rows = conn.execute(
            "SELECT url FROM provider_endpoints WHERE app_type=? AND provider_id=?",
            (app_type, provider_id),
        ).fetchall()
        return [r["url"] for r in rows]
    finally:
        conn.close()


def run_hidden(cmd: list[str], timeout: float = 10.0) -> str:
    kwargs: dict[str, Any] = {}
    if sys.platform.startswith("win"):
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = 0
        kwargs["startupinfo"] = info
        kwargs["creationflags"] = 0x08000000
    return (
        subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **kwargs,
        ).stdout
        or ""
    )


def cc_switch_running() -> bool:
    try:
        if sys.platform.startswith("win"):
            out = run_hidden(["tasklist"])
            low = out.lower()
            return any(name.lower() in low for name in PROCESS_NAMES)
        return bool(run_hidden(["pgrep", "-f", "cc-switch"]).strip())
    except Exception:
        return False


def backup_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = path.parent / f"{path.name}.bak-{stamp}"
    shutil.copy2(path, target)
    return target


def backup_db(db_path: Path = DB_PATH) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"cc-switch.db.bak-{stamp}"
    src = open_ro(db_path)
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def build_model_picker(
    models: list[Model], replace_builtin: bool = True
) -> dict[str, Any]:
    options = []
    for m in models:
        row: dict[str, str] = {"model": m.id}
        if m.display_name and m.display_name != m.id:
            row["label"] = m.display_name
        if m.description:
            row["description"] = m.description.splitlines()[0][:120]
        options.append(row)
    return {"options": options, "replaceBuiltInOptions": bool(replace_builtin)}


def _catalog_entries(catalog: Any) -> list[dict[str, Any]]:
    if isinstance(catalog, dict):
        catalog = catalog.get("models")
    if not isinstance(catalog, list):
        return []
    return [copy.deepcopy(item) for item in catalog if isinstance(item, dict)]


def merge_json_entries(
    existing: Any,
    incoming: Any,
    *,
    key: str,
    merge: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    existing_entries = _catalog_entries(existing)
    incoming_entries = _catalog_entries(incoming)
    existing_ids = {str(item.get(key) or "") for item in existing_entries}
    existing_ids.discard("")
    incoming_ids = {str(item.get(key) or "") for item in incoming_entries}
    incoming_ids.discard("")

    if not merge:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in incoming_entries:
            ident = str(item.get(key) or "")
            if not ident or ident in seen:
                continue
            out.append(copy.deepcopy(item))
            seen.add(ident)
        return out, {"added": len(seen), "preserved": 0}

    out = existing_entries
    seen = set(existing_ids)
    added = 0
    for item in incoming_entries:
        ident = str(item.get(key) or "")
        if not ident or ident in seen:
            continue
        out.append(copy.deepcopy(item))
        seen.add(ident)
        added += 1
    preserved = len(incoming_ids & existing_ids)
    return out, {"added": added, "preserved": preserved}


def build_codex_catalog(
    models: list[Model],
    template: dict[str, Any] | None = None,
    context: int = 0,
    *,
    existing: Any = None,
    merge: bool = False,
) -> dict[str, Any]:
    base = template or {
        "context_window": 200000,
        "max_context_window": 200000,
        "effective_context_window_percent": 95,
        "input_modalities": ["text"],
        "supported_in_api": True,
        "supports_parallel_tool_calls": False,
        "supported_reasoning_levels": [
            {"effort": "none", "description": "Disable Thinking"},
            {"effort": "high", "description": "Enabled Thinking"},
        ],
    }
    entries = []
    for m in models:
        entry = json.loads(json.dumps(base))
        entry["slug"] = m.id
        entry["display_name"] = m.display_name or m.id
        entry["description"] = m.display_name or m.id
        ctx = int(getattr(m, "context", 0)) or int(context or 0)
        if ctx:
            entry["context_window"] = ctx
            entry["max_context_window"] = ctx
        entries.append(entry)
    merged, _stats = merge_json_entries(existing, entries, key="slug", merge=merge)
    return {"models": merged}


def build_codex_model_catalog(
    models: list[Model],
    *,
    existing: Any = None,
    merge: bool = False,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for m in models:
        entry: dict[str, Any] = {
            "model": m.id,
            "displayName": m.display_name or m.id,
        }
        if m.context:
            entry["contextWindow"] = int(m.context)
        if m.input_modalities:
            entry["inputModalities"] = list(m.input_modalities)
        if m.reasoning_levels:
            entry["reasoningLevels"] = list(m.reasoning_levels)
        if m.default_reasoning_level:
            entry["defaultReasoningLevel"] = m.default_reasoning_level
        entries.append(entry)
    merged, _stats = merge_json_entries(existing, entries, key="model", merge=merge)
    return {"models": merged}


def _set_toml_top_level(config: str, key: str, value: str) -> str:
    line = f'{key} = "{value}"'
    lines = config.splitlines()
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("[") or re.match(rf"^{re.escape(key)}\s*=", s):
            if re.match(rf"^{re.escape(key)}\s*=", s):
                lines[i] = line
                return "\n".join(lines)
            lines.insert(i, line)
            return "\n".join(lines)
    lines.append(line)
    return "\n".join(lines)


def apply_claude(
    provider_id: str,
    models: list[Model],
    *,
    replace_builtin: bool = True,
    gateway_discovery: bool = False,
    db_path: Path = DB_PATH,
    do_backup: bool = True,
) -> dict[str, Any]:
    provider = get_provider("claude", provider_id, db_path)
    if not provider:
        raise ValueError(f"找不到 Claude 供应商卡：{provider_id}")

    config = json.loads(provider["settings_config"])
    picker = build_model_picker(models, replace_builtin)
    before = config.get("modelPicker")
    config["modelPicker"] = picker

    env = config.setdefault("env", {})
    if gateway_discovery:
        env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] = "1"

    backup = backup_db(db_path) if do_backup else None
    conn = open_rw(db_path)
    try:
        with conn:
            conn.execute(
                "UPDATE providers SET settings_config=? WHERE app_type=? AND id=?",
                (json.dumps(config, ensure_ascii=False), "claude", provider_id),
            )
    finally:
        conn.close()

    return {
        "ok": True,
        "mode": "claude",
        "provider": provider["name"],
        "providerId": provider_id,
        "backup": str(backup) if backup else None,
        "rows": len(picker["options"]),
        "replaced": before is not None,
        "gatewayDiscovery": gateway_discovery,
    }


def build_opencode_models(
    models: list[Model],
    *,
    context: int = 1000000,
    output: int = 131072,
    existing: dict[str, Any] | None = None,
    merge: bool = False,
) -> dict[str, Any]:
    out: dict[str, Any] = dict(existing or {}) if merge else {}
    for m in models:
        if merge and m.id in out:
            continue
        ctx = int(getattr(m, "context", 0)) or int(context)
        out_max = int(getattr(m, "output", 0)) or int(output)
        out[m.id] = {
            "name": m.display_name or m.id,
            "limit": {"context": ctx, "output": out_max},
        }
    return out


def apply_opencode(
    provider_id: str,
    models: list[Model],
    *,
    context: int = 1000000,
    output: int = 131072,
    merge: bool = False,
    db_path: Path = DB_PATH,
    do_backup: bool = True,
) -> dict[str, Any]:
    provider = get_provider("opencode", provider_id, db_path)
    if not provider:
        raise ValueError(f"找不到 OpenCode 供应商卡：{provider_id}")

    config = json.loads(provider["settings_config"])
    existing = config.get("models") if isinstance(config.get("models"), dict) else {}
    built = build_opencode_models(
        models, context=context, output=output, existing=existing, merge=merge
    )
    config["models"] = built

    backup = backup_db(db_path) if do_backup else None
    conn = open_rw(db_path)
    try:
        with conn:
            conn.execute(
                "UPDATE providers SET settings_config=? WHERE app_type=? AND id=?",
                (json.dumps(config, ensure_ascii=False), "opencode", provider_id),
            )
    finally:
        conn.close()

    return {
        "ok": True,
        "mode": "opencode",
        "provider": provider["name"],
        "providerId": provider_id,
        "backup": str(backup) if backup else None,
        "rows": len(built),
        "merged": merge,
    }


def build_codex_config(base_url: str, model: str = "") -> str:
    url = (base_url or "").rstrip("/")
    return (
        'model_provider = "custom"\n'
        f'model = "{model or "gpt-5.2"}"\n'
        "disable_response_storage = true\n\n"
        "[model_providers.custom]\n"
        'name = "custom"\n'
        f'base_url = "{url}"\n'
        'wire_api = "responses"\n'
        "requires_openai_auth = true\n"
    )


def create_provider(
    app_type: str,
    name: str,
    base_url: str,
    api_key: str,
    *,
    model: str = "",
    api_format: str = "openai",
    db_path: Path = DB_PATH,
    do_backup: bool = True,
) -> dict[str, Any]:
    if app_type not in ("claude", "codex", "opencode"):
        raise ValueError(f"暂不支持新建 {app_type} 卡（支持 claude / codex / opencode）")
    if not name.strip():
        raise ValueError("请填写卡片名称")
    if not base_url.strip():
        raise ValueError("请填写端点地址")

    now = int(time.time() * 1000)
    pid = f"{re.sub(r'[^0-9A-Za-z]+', '-', name).strip('-').lower()}-{now}"
    url = base_url.strip().rstrip("/")

    if app_type == "claude":
        env: dict[str, str] = {"ANTHROPIC_BASE_URL": url}
        if api_key:
            env["ANTHROPIC_AUTH_TOKEN"] = api_key
        if model:
            env["ANTHROPIC_MODEL"] = model
        settings: dict[str, Any] = {"env": env}
        if model:
            settings["model"] = model
        meta = {"endpointAutoSelect": True, "apiFormat": "anthropic"}
    elif app_type == "opencode":
        settings = {
            "npm": "@ai-sdk/openai-compatible",
            "name": name,
            "options": {"baseURL": url, "apiKey": api_key},
            "models": {},
        }
        meta = {}
    else:
        settings = {
            "auth": {"OPENAI_API_KEY": api_key},
            "config": build_codex_config(url, model),
        }
        meta = {}

    backup = backup_db(db_path) if do_backup else None
    conn = open_rw(db_path)
    try:
        with conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(sort_index), 0) AS m FROM providers WHERE app_type=?", (app_type,)
            ).fetchone()
            conn.execute(
                "INSERT INTO providers "
                "(id, app_type, name, settings_config, category, created_at, sort_index, meta, is_current, in_failover_queue) "
                "VALUES (?,?,?,?,?,?,?,?,0,0)",
                (
                    pid, app_type, name, json.dumps(settings, ensure_ascii=False),
                    "custom", now, int(row["m"] or 0) + 1, json.dumps(meta, ensure_ascii=False),
                ),
            )
            conn.execute(
                "INSERT INTO provider_endpoints (provider_id, app_type, url, added_at) VALUES (?,?,?,?)",
                (pid, app_type, url, now),
            )
    finally:
        conn.close()

    return {"ok": True, "app": app_type, "id": pid, "name": name, "backup": str(backup) if backup else None}


def delete_providers(
    app_type: str,
    provider_ids: list[str],
    *,
    force: bool = False,
    db_path: Path = DB_PATH,
    do_backup: bool = True,
) -> dict[str, Any]:
    if not provider_ids:
        raise ValueError("没有选择要删除的卡")
    if "default" in provider_ids:
        raise ValueError("不能删除 default 卡")

    conn = open_rw(db_path)
    try:
        rows = conn.execute(
            "SELECT id, name, is_current FROM providers WHERE app_type=?", (app_type,)
        ).fetchall()
    finally:
        conn.close()

    by_id = {r["id"]: r for r in rows}
    missing = [p for p in provider_ids if p not in by_id]
    if missing:
        raise ValueError(f"找不到卡片：{', '.join(missing)}")

    if not force:
        current = [p for p in provider_ids if int(by_id[p]["is_current"] or 0) == 1]
        if current:
            raise ValueError("选中的卡里有当前正在使用的卡，请先在 CC Switch 里切到别的卡")

    backup = backup_db(db_path) if do_backup else None
    conn = open_rw(db_path)
    try:
        with conn:
            for pid in provider_ids:
                conn.execute(
                    "DELETE FROM provider_endpoints WHERE app_type=? AND provider_id=?", (app_type, pid)
                )
                conn.execute(
                    "DELETE FROM provider_health WHERE app_type=? AND provider_id=?", (app_type, pid)
                )
                conn.execute(
                    "DELETE FROM providers WHERE app_type=? AND id=?", (app_type, pid)
                )
    finally:
        conn.close()

    return {
        "ok": True,
        "app": app_type,
        "deleted": len(provider_ids),
        "names": [by_id[p]["name"] for p in provider_ids],
        "backup": str(backup) if backup else None,
    }


def apply_codex(
    models: list[Model],
    provider_id: str | None = None,
    *,
    context: int = 0,
    merge: bool = False,
    catalog_path: Path = CODEX_CATALOG,
    db_path: Path = DB_PATH,
    do_backup: bool = True,
) -> dict[str, Any]:
    existing_catalog: dict[str, Any] = {}
    template: dict[str, Any] | None = None
    if catalog_path.exists():
        try:
            loaded = json.loads(catalog_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing_catalog = loaded
            if isinstance(existing_catalog.get("models"), list) and existing_catalog["models"]:
                template = existing_catalog["models"][0]
        except Exception:
            existing_catalog = {}

    provider: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    existing_card: Any = None
    if provider_id:
        provider = get_provider("codex", provider_id, db_path)
        if not provider:
            raise ValueError(f"找不到 Codex 供应商卡：{provider_id}")
        try:
            config = json.loads(provider["settings_config"] or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"Codex 供应商卡配置不是有效 JSON：{exc}") from exc
        existing_card = config.get("modelCatalog")

    catalog = build_codex_catalog(
        models,
        template,
        context=context,
        existing=existing_catalog,
        merge=merge,
    )
    card_catalog = build_codex_model_catalog(
        models,
        existing=existing_card,
        merge=merge,
    ) if provider_id else None

    selected_ids = {m.id for m in models if m.id}
    existing_card_ids = {
        str(item.get("model") or "")
        for item in _catalog_entries(existing_card)
    }
    existing_card_ids.discard("")
    existing_catalog_ids = {
        str(item.get("slug") or "")
        for item in _catalog_entries(existing_catalog)
    }
    existing_catalog_ids.discard("")
    base_ids = existing_card_ids if provider_id and existing_card_ids else existing_catalog_ids
    preserved = len(selected_ids & base_ids) if merge else 0
    added = len(selected_ids - base_ids) if merge else len(selected_ids)

    catalog_backup: Path | None = None
    if do_backup and catalog_path.exists():
        catalog_backup = backup_file(catalog_path)

    db_backup: Path | None = None
    if provider_id and config is not None:
        text = str(config.get("config") or "")
        config["config"] = _set_toml_top_level(text, "model_catalog_json", catalog_path.name)
        if card_catalog is not None:
            config["modelCatalog"] = card_catalog
        if do_backup:
            db_backup = backup_db(db_path)
        conn = open_rw(db_path)
        try:
            with conn:
                conn.execute(
                    "UPDATE providers SET settings_config=? WHERE app_type=? AND id=?",
                    (json.dumps(config, ensure_ascii=False), "codex", provider_id),
                )
        finally:
            conn.close()

    write_text_atomic(
        catalog_path,
        json.dumps(catalog, ensure_ascii=False, indent=2),
    )

    return {
        "ok": True,
        "mode": "codex",
        "providerId": provider_id,
        "provider": provider["name"] if provider else None,
        "catalog": str(catalog_path),
        "backup": str(db_backup) if db_backup else (str(catalog_backup) if catalog_backup else None),
        "dbBackup": str(db_backup) if db_backup else None,
        "catalogBackup": str(catalog_backup) if catalog_backup else None,
        "rows": len(catalog["models"]),
        "catalogRows": len(catalog["models"]),
        "cardRows": len(card_catalog["models"]) if card_catalog else 0,
        "added": added,
        "preserved": preserved,
        "merged": merge,
    }


def build_fanout_cards(
    template: dict[str, Any],
    models: list[Model],
    *,
    app_type: str,
    endpoints: list[str],
    fill_roles: bool = True,
    name_prefix: str = "",
) -> list[dict[str, Any]]:
    config = json.loads(template["settings_config"])
    now = int(time.time() * 1000)
    cards: list[dict[str, Any]] = []

    for idx, m in enumerate(models):
        cfg = json.loads(json.dumps(config))
        name = f"{name_prefix}{m.id}"
        if app_type == "claude":
            env = cfg.setdefault("env", {})
            env["ANTHROPIC_MODEL"] = m.id
            if fill_roles:
                env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = m.id
                env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = m.id
                env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = m.id
            cfg["model"] = m.id
        else:
            text = str(cfg.get("config") or "")
            cfg["config"] = _set_toml_top_level(text, "model", m.id)

        cards.append(
            {
                "id": f"{re.sub(r'[^0-9A-Za-z]+', '-', m.id).strip('-').lower()}-{now}-{idx}",
                "app_type": app_type,
                "name": name,
                "settings_config": json.dumps(cfg, ensure_ascii=False),
                "meta": template.get("meta") or "{}",
                "category": "custom",
                "created_at": now + idx,
                "is_current": 0,
                "endpoints": endpoints,
            }
        )
    return cards


def apply_fanout(
    provider_id: str,
    models: list[Model],
    *,
    app_type: str = "claude",
    fill_roles: bool = True,
    name_prefix: str = "",
    db_path: Path = DB_PATH,
    do_backup: bool = True,
) -> dict[str, Any]:
    if app_type == "opencode":
        raise ValueError("OpenCode 卡自带模型列表，请用「一张卡 + 模型列表」模式")
    template = get_provider(app_type, provider_id, db_path)
    if not template:
        raise ValueError(f"找不到模板卡：{provider_id}")

    endpoints = get_endpoints(app_type, provider_id, db_path)
    cards = build_fanout_cards(
        template, models, app_type=app_type, endpoints=endpoints, fill_roles=fill_roles, name_prefix=name_prefix
    )

    backup = backup_db(db_path) if do_backup else None
    conn = open_rw(db_path)
    try:
        with conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(sort_index), 0) AS m FROM providers WHERE app_type=?", (app_type,)
            ).fetchone()
            sort_base = int(row["m"] or 0)
            for i, card in enumerate(cards):
                conn.execute(
                    "INSERT INTO providers "
                    "(id, app_type, name, settings_config, category, created_at, sort_index, meta, is_current, in_failover_queue) "
                    "VALUES (?,?,?,?,?,?,?,?,0,0)",
                    (
                        card["id"],
                        card["app_type"],
                        card["name"],
                        card["settings_config"],
                        card["category"],
                        card["created_at"],
                        sort_base + i + 1,
                        card["meta"],
                    ),
                )
                for url in card["endpoints"]:
                    conn.execute(
                        "INSERT INTO provider_endpoints (provider_id, app_type, url, added_at) VALUES (?,?,?,?)",
                        (card["id"], card["app_type"], url, card["created_at"]),
                    )
    finally:
        conn.close()

    return {
        "ok": True,
        "mode": "fanout",
        "app": app_type,
        "template": template["name"],
        "backup": str(backup) if backup else None,
        "rows": len(cards),
        "cards": [{"id": c["id"], "name": c["name"]} for c in cards[:20]],
    }


def rollback(backup_path: str | None, target: str = "db") -> dict[str, Any]:
    if not backup_path:
        raise ValueError("没有可回滚的备份")
    src = Path(backup_path)
    if not src.exists():
        raise FileNotFoundError(f"备份不存在：{backup_path}")
    dst = DB_PATH if target == "db" else CODEX_CATALOG
    shutil.copy2(src, dst)
    return {"ok": True, "restored": str(dst), "from": str(src)}


def save_models(models: list[Model], out_dir: Path = OUT_DIR) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    js = out_dir / "models.json"
    txt = out_dir / "models.txt"
    js.write_text(
        json.dumps([m.to_dict() for m in models], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    txt.write_text("\n".join(m.id for m in models) + "\n", encoding="utf-8")
    return js, txt


def load_models(path: Path) -> list[Model]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Model(**{k: v for k, v in item.items() if k in Model.__dataclass_fields__}) for item in payload]


def parse_pick(spec: str, total: int) -> list[int]:
    picked: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            picked.extend(range(int(a), int(b) + 1))
        else:
            picked.append(int(part))
    return sorted({i for i in picked if 1 <= i <= total})


def resolve_api_key(cli_key: str | None) -> str:
    if cli_key:
        return cli_key
    env = os.environ.get("CCS_API_KEY", "")
    if env:
        return env
    return getpass.getpass("API Key（不回显，不保存）: ")


def cmd_fetch(args: argparse.Namespace) -> int:
    key = resolve_api_key(args.key)
    models, logs = fetch_models(
        args.base_url,
        key,
        is_full_url=args.full_url,
        models_url=args.models_url,
        user_agent=args.ua,
        api_format=args.api_format,
        log=lambda m: print(m),
    )
    js, txt = save_models(models)
    print(f"\n共 {len(models)} 个模型 → {js}")
    print(f"可直接编辑的选择清单 → {txt}")
    for i, m in enumerate(models, 1):
        print(f"{i:4d}  {m.id}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    models = load_models(Path(args.file))
    for i, m in enumerate(models, 1):
        print(f"{i:4d}  {m.id}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    models = load_models(Path(args.file))
    if args.pick:
        idxs = parse_pick(args.pick, len(models))
    elif args.pick_file:
        wanted = {
            ln.strip()
            for ln in Path(args.pick_file).read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        }
        idxs = [i for i, m in enumerate(models, 1) if m.id in wanted]
    else:
        idxs = list(range(1, len(models) + 1))
    chosen = [models[i - 1] for i in idxs]
    print(f"已选 {len(chosen)} 个模型")

    if args.dry_run:
        print(json.dumps(build_model_picker(chosen), ensure_ascii=False, indent=2))
        return 0

    if args.mode == "claude":
        res = apply_claude(args.provider, chosen, replace_builtin=not args.append, gateway_discovery=args.discovery)
    elif args.mode == "opencode":
        res = apply_opencode(args.provider, chosen, merge=args.merge)
    elif args.mode == "codex":
        res = apply_codex(chosen, args.provider, merge=args.merge)
    else:
        res = apply_fanout(args.provider, chosen, app_type=args.app, fill_roles=not args.no_fill_roles)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


def cmd_new_card(args: argparse.Namespace) -> int:
    res = create_provider(args.app, args.name, args.base_url, args.key, model=args.model)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


def cmd_del_card(args: argparse.Namespace) -> int:
    res = delete_providers(args.app, args.ids.split(","), force=args.force)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CC Switch 模型批量导入（只读 /v1/models）")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="拉取模型列表")
    f.add_argument("--base-url", required=True)
    f.add_argument("--key", default=None)
    f.add_argument("--models-url", default=None)
    f.add_argument("--ua", default=None)
    f.add_argument("--api-format", choices=["openai", "anthropic", "google"], default="openai")
    f.add_argument("--full-url", action="store_true")
    f.set_defaults(func=cmd_fetch)

    s = sub.add_parser("show", help="重新打印编号清单")
    s.add_argument("--file", default=str(OUT_DIR / "models.json"))
    s.set_defaults(func=cmd_show)

    a = sub.add_parser("apply", help="写入 CC Switch")
    a.add_argument("--file", default=str(OUT_DIR / "models.json"))
    a.add_argument("--mode", choices=["claude", "codex", "opencode", "fanout"], default="claude")
    a.add_argument("--app", choices=["claude", "codex", "opencode"], default="claude")
    a.add_argument("--provider", required=True, help="模板/目标供应商卡 id")
    a.add_argument("--pick", default=None)
    a.add_argument("--pick-file", default=None)
    a.add_argument("--append", action="store_true", help="保留内置模型行")
    a.add_argument("--merge", action="store_true", help="OpenCode / Codex：合并到已有模型列表")
    a.add_argument("--discovery", action="store_true", help="同时开启网关模型发现")
    a.add_argument("--no-fill-roles", action="store_true")
    a.add_argument("--dry-run", action="store_true")
    a.set_defaults(func=cmd_apply)

    n = sub.add_parser("new-card", help="新建供应商卡")
    n.add_argument("--app", choices=["claude", "codex", "opencode"], required=True)
    n.add_argument("--name", required=True)
    n.add_argument("--base-url", required=True)
    n.add_argument("--key", default="")
    n.add_argument("--model", default="")
    n.set_defaults(func=cmd_new_card)

    d = sub.add_parser("del-card", help="删除供应商卡（逗号分隔 id）")
    d.add_argument("--app", choices=["claude", "codex", "opencode"], required=True)
    d.add_argument("--ids", required=True)
    d.add_argument("--force", action="store_true")
    d.set_defaults(func=cmd_del_card)

    return p


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
