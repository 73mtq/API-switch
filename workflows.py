"""预览摘要与写入编排：把界面收集的 payload 交给 core 执行。"""

from __future__ import annotations

import json

import ccs_models as core
from formatting import DEFAULT_CONTEXT, DEFAULT_OUTPUT, fmt_ctx


def models_from(body: dict) -> list[core.Model]:
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


def model_lines(models: list[core.Model], limit: int = 12) -> list[str]:
    lines = [f"  {n}. {m.id}" for n, m in enumerate(models[:limit], 1)]
    if len(models) > limit:
        lines.append(f"  … 其余 {len(models) - limit} 个")
    return lines


def _required_provider_id(body: dict, message: str) -> str:
    raw = body.get("providerId")
    if not isinstance(raw, str) or not raw:
        raise ValueError(message)
    return raw


def _optional_provider_id(body: dict) -> str | None:
    raw = body.get("providerId")
    if isinstance(raw, str) and raw:
        return raw
    return None


def preview_summary(body: dict) -> str:
    models = models_from(body)
    if not models:
        raise ValueError("没有选择任何模型")
    mode = body.get("mode", "list")
    app = body.get("app", "claude")
    context = int(body.get("context") or 0)
    known = sum(1 for m in models if getattr(m, "context", 0))

    if mode == "fanout":
        provider_id = _required_provider_id(body, "找不到模板卡")
        template = core.get_provider(app, provider_id)
        if not template:
            raise ValueError("找不到模板卡")
        cards = core.build_fanout_cards(
            template, models, app_type=app,
            endpoints=core.get_endpoints(app, provider_id),
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
        provider_id = _required_provider_id(body, "找不到 OpenCode 供应商卡")
        provider = core.get_provider("opencode", provider_id)
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
            f"上下文：{fmt_ctx(context or DEFAULT_CONTEXT)}（{note}）",
            f"最大输出：{fmt_ctx(int(body.get('output') or DEFAULT_OUTPUT))}",
            "",
            f"模型列表（{len(built)} 个，显示前 12 个）：",
        ]
        lines.extend(f"  {n}. {model_id}" for n, model_id in enumerate(list(built)[:12], 1))
        if len(built) > 12:
            lines.append(f"  … 其余 {len(built) - 12} 个")
        lines.extend(["", "写入前会自动备份数据库，可用「回滚到备份」还原。"])
        return "\n".join(lines)

    if mode == "list" and app == "codex":
        codex_provider_id = _optional_provider_id(body)
        provider = core.get_provider("codex", codex_provider_id) if codex_provider_id else None
        existing_card = None
        if provider:
            existing_card = json.loads(provider["settings_config"]).get("modelCatalog")
        existing_catalog = (
            json.loads(core.CODEX_CATALOG.read_text(encoding="utf-8"))
            if core.CODEX_CATALOG.exists() else None
        )
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
        card_rows = len(card_catalog["models"]) if card_catalog else 0
        lines = [
            f"目标：{'Codex 卡「' + provider['name'] + '」和 ' if provider else ''}模型目录 {core.CODEX_CATALOG}",
            f"操作：{action} {stats['added']} 个模型，保留 {stats['preserved']} 个",
            f"上下文：{fmt_ctx(context) or context}（接口给出 {known} 个）",
            f"卡内模型：{card_rows} 个 · 目录模型：{len(catalog['models'])} 个",
            "",
            f"模型列表（{len(models)} 个，显示前 12 个）：",
        ]
        lines.extend(model_lines(models))
        lines.extend(["", "写入前会自动备份数据库与模型目录，可用「回滚到备份」还原。"])
        return "\n".join(lines)

    provider_id = _required_provider_id(body, "找不到 Claude 供应商卡")
    provider = core.get_provider("claude", provider_id)
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
    lines.extend(model_lines(models))
    lines.extend(["", "写入前会自动备份数据库，可用「回滚到备份」还原。"])
    return "\n".join(lines)


def apply_payload(body: dict) -> dict:
    models = models_from(body)
    if not models:
        raise ValueError("没有选择任何模型")
    mode = body.get("mode", "list")
    app = body.get("app", "claude")
    hot_codex = mode == "list" and app == "codex"
    if core.cc_switch_running() and not hot_codex:
        raise RuntimeError("CC Switch 正在运行，请先完全退出后再写入")

    provider_id = _optional_provider_id(body)

    if mode == "fanout":
        if not provider_id:
            raise ValueError("请先选择模板卡")
        result = core.apply_fanout(
            provider_id, models, app_type=app,
            fill_roles=bool(body.get("fillRoles", True)),
            name_prefix=str(body.get("namePrefix") or ""),
        )
        result["summary"] = f"已在 {result['app']} 下新建 {result['rows']} 张供应商卡"
        return result

    if app == "opencode":
        if not provider_id:
            raise ValueError("请先选择目标供应商卡")
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

    if not provider_id:
        raise ValueError("请先选择目标供应商卡")
    result = core.apply_claude(
        provider_id, models,
        replace_builtin=bool(body.get("replaceBuiltIn", True)),
        gateway_discovery=bool(body.get("gatewayDiscovery")),
    )
    result["summary"] = f"已把 {result['rows']} 个模型写入 Claude 卡「{result['provider']}」的 modelPicker"
    return result
