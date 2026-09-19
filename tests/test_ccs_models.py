import json
import sqlite3
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import ccs_models as core


def make_db(path: Path, *, codex: bool = True) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE providers ("
        "id TEXT PRIMARY KEY, app_type TEXT, name TEXT, settings_config TEXT, "
        "category TEXT, created_at INTEGER, sort_index INTEGER, meta TEXT, "
        "is_current INTEGER, in_failover_queue INTEGER)"
    )
    conn.execute(
        "CREATE TABLE provider_endpoints ("
        "provider_id TEXT, app_type TEXT, url TEXT, added_at INTEGER)"
    )
    conn.execute(
        "CREATE TABLE provider_health ("
        "provider_id TEXT, app_type TEXT, healthy INTEGER)"
    )
    if codex:
        settings = {
            "auth": {"OPENAI_API_KEY": "secret"},
            "config": (
                'model_provider = "custom"\n'
                'model = "keep-default"\n\n'
                '[model_providers.custom]\n'
                'name = "opencode_go"\n'
                'base_url = "http://127.0.0.1:15721/v1"\n'
                'wire_api = "responses"\n'
            ),
            "modelCatalog": {
                "models": [
                    {
                        "model": "model-a",
                        "displayName": "Model A Old",
                        "contextWindow": 111,
                        "customField": "keep-card",
                    }
                ]
            },
        }
        conn.execute(
            "INSERT INTO providers VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "provider-1",
                "codex",
                "OpenCode Go",
                json.dumps(settings, ensure_ascii=False),
                "custom",
                1,
                1,
                "{}",
                1,
                0,
            ),
        )
        conn.execute(
            "INSERT INTO provider_endpoints VALUES (?,?,?,?)",
            ("provider-1", "codex", "http://127.0.0.1:15721/v1", 1),
        )
    conn.commit()
    conn.close()


class TempDbCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        self.db_path = root / "cc-switch.db"
        self.catalog_path = root / "catalog.json"
        self.old_backup_dir = core.BACKUP_DIR
        self.old_db_path = core.DB_PATH
        self.old_catalog = core.CODEX_CATALOG
        core.BACKUP_DIR = root / "backups"
        make_db(self.db_path)

    def tearDown(self) -> None:
        core.BACKUP_DIR = self.old_backup_dir
        core.DB_PATH = self.old_db_path
        core.CODEX_CATALOG = self.old_catalog
        self.tmp.cleanup()

    def provider_settings(self, provider_id: str = "provider-1") -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT settings_config FROM providers WHERE id=?", (provider_id,)
        ).fetchone()
        conn.close()
        return json.loads(row[0])

    def provider_rows(self, app_type: str) -> list[sqlite3.Row]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, sort_index FROM providers WHERE app_type=? ORDER BY sort_index",
            (app_type,),
        ).fetchall()
        conn.close()
        return rows


class CodexMergeTests(TempDbCase):
    def setUp(self) -> None:
        super().setUp()
        self.catalog_path.write_text(
            json.dumps(
                {
                    "models": [
                        {
                            "slug": "model-a",
                            "display_name": "Model A Old",
                            "context_window": 111,
                            "max_context_window": 111,
                            "customField": "keep-catalog",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def apply(self, models: list[core.Model], *, merge: bool) -> dict:
        return core.apply_codex(
            models,
            "provider-1",
            context=999,
            merge=merge,
            catalog_path=self.catalog_path,
            db_path=self.db_path,
        )

    def catalog_models(self) -> list[dict]:
        return json.loads(self.catalog_path.read_text(encoding="utf-8"))["models"]

    def test_merge_preserves_existing_entries_and_is_idempotent(self) -> None:
        models = [
            core.Model(
                id="model-b",
                display_name="Model B",
                context=42,
                input_modalities=["text", "image"],
                reasoning_levels=["low", "high"],
                default_reasoning_level="high",
            ),
            core.Model(id="model-a", display_name="Model A New", context=222),
        ]

        result = self.apply(models, merge=True)

        self.assertEqual(1, result["added"])
        self.assertEqual(1, result["preserved"])
        self.assertEqual(2, result["cardRows"])
        self.assertEqual(2, result["catalogRows"])
        self.assertTrue(Path(result["dbBackup"]).exists())
        self.assertTrue(Path(result["catalogBackup"]).exists())

        settings = self.provider_settings()
        self.assertEqual("secret", settings["auth"]["OPENAI_API_KEY"])
        self.assertIn('model = "keep-default"', settings["config"])
        self.assertIn('model_catalog_json = "catalog.json"', settings["config"])
        card_models = settings["modelCatalog"]["models"]
        self.assertEqual(["model-a", "model-b"], [item["model"] for item in card_models])
        self.assertEqual("Model A Old", card_models[0]["displayName"])
        self.assertEqual(111, card_models[0]["contextWindow"])
        self.assertEqual("keep-card", card_models[0]["customField"])
        self.assertEqual(42, card_models[1]["contextWindow"])
        self.assertEqual(["text", "image"], card_models[1]["inputModalities"])

        catalog_models = self.catalog_models()
        self.assertEqual(["model-a", "model-b"], [item["slug"] for item in catalog_models])
        self.assertEqual("Model A Old", catalog_models[0]["display_name"])
        self.assertEqual(111, catalog_models[0]["context_window"])
        self.assertEqual("keep-catalog", catalog_models[0]["customField"])
        self.assertEqual(42, catalog_models[1]["context_window"])

        second = self.apply(models, merge=True)
        self.assertEqual(0, second["added"])
        self.assertEqual(2, second["preserved"])
        self.assertEqual(2, len(self.catalog_models()))
        self.assertEqual(
            2,
            len(self.provider_settings()["modelCatalog"]["models"]),
        )

    def test_replace_removes_old_entries(self) -> None:
        result = self.apply(
            [core.Model(id="model-c", display_name="Model C", context=77)],
            merge=False,
        )

        self.assertEqual(1, result["added"])
        self.assertEqual(0, result["preserved"])
        self.assertEqual(["model-c"], [
            item["model"] for item in self.provider_settings()["modelCatalog"]["models"]
        ])
        self.assertEqual(["model-c"], [item["slug"] for item in self.catalog_models()])


class ModelParsingTests(unittest.TestCase):
    def test_parse_rich_model_metadata(self) -> None:
        models = core.parse_models_response(
            {
                "data": [
                    {
                        "id": "model-x",
                        "name": "Model X",
                        "limit": {"context": 128000, "output": 8192},
                        "capabilities": {"input": {"text": True, "image": True}},
                        "variants": {"low": {}, "high": {}},
                    }
                ]
            }
        )

        self.assertEqual(1, len(models))
        self.assertEqual(["text", "image"], models[0].input_modalities)
        self.assertEqual(["low", "high"], models[0].reasoning_levels)
        self.assertEqual(0, models[0].context)
        self.assertEqual(0, models[0].output)

    def test_parse_preserves_interface_order(self) -> None:
        models = core.parse_models_response(
            {"data": [{"id": "z-model"}, {"id": "a-model"}, {"id": "m-model"}]}
        )
        self.assertEqual(["z-model", "a-model", "m-model"], [m.id for m in models])

    def test_parse_zhipu_style_and_dedupe(self) -> None:
        models = core.parse_models_response(
            {"models": [{"slug": "glm-4"}, {"slug": "glm-4"}, {"slug": "glm-4-air"}]}
        )
        self.assertEqual(["glm-4", "glm-4-air"], [m.id for m in models])


class CandidateTests(unittest.TestCase):
    def test_plain_base_url(self) -> None:
        self.assertEqual(
            ["https://x.com/v1/models"], core.build_candidates("https://x.com")
        )

    def test_version_segment(self) -> None:
        self.assertEqual(
            ["https://x.com/v1/models"], core.build_candidates("https://x.com/v1")
        )
        self.assertEqual(
            ["https://x.com/v3/models", "https://x.com/v3/v1/models"],
            core.build_candidates("https://x.com/v3"),
        )

    def test_models_suffix_is_not_duplicated(self) -> None:
        self.assertEqual(
            ["https://x.com/v1/models"], core.build_candidates("https://x.com/v1/models")
        )

    def test_compat_suffix_adds_root_candidates(self) -> None:
        candidates = core.build_candidates("https://x.com/api/anthropic")
        self.assertEqual(
            [
                "https://x.com/api/anthropic/v1/models",
                "https://x.com/v1/models",
                "https://x.com/models",
            ],
            candidates,
        )

    def test_full_url_mode(self) -> None:
        self.assertEqual(
            ["https://x.com/v1/models"],
            core.build_candidates("https://x.com/v1/chat/completions", is_full_url=True),
        )

    def test_override_wins(self) -> None:
        self.assertEqual(
            ["https://y.com/list"],
            core.build_candidates("https://x.com", override="https://y.com/list"),
        )

    def test_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            core.build_candidates("   ")


class FetchServerCase(unittest.TestCase):
    def setUp(self) -> None:
        self.requests: list[tuple[str, dict[str, str]]] = []

    def start_server(self, routes: dict[str, tuple[int, bytes, dict[str, str]]]) -> str:
        requests = self.requests

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                requests.append((self.path, dict(self.headers)))
                status, body, headers = routes.get(self.path, (404, b"{}", {}))
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}"

    @staticmethod
    def payload(*ids: str) -> bytes:
        return json.dumps({"data": [{"id": i} for i in ids]}).encode("utf-8")


class FetchModelsTests(FetchServerCase):
    def test_success_parses_and_requests_limit(self) -> None:
        base = self.start_server({"/v1/models?limit=1000": (200, self.payload("z", "a"), {})})
        models, logs = core.fetch_models(f"{base}/v1", "sk-secret")
        self.assertEqual(["z", "a"], [m.id for m in models])
        self.assertTrue(any("200" in line for line in logs))
        self.assertEqual("/v1/models?limit=1000", self.requests[0][0])

    def test_404_falls_through_to_next_candidate(self) -> None:
        base = self.start_server({"/v1/models?limit=1000": (200, self.payload("a"), {})})
        models, _logs = core.fetch_models(f"{base}/api/anthropic", "k")
        self.assertEqual(["a"], [m.id for m in models])
        self.assertEqual(
            ["/api/anthropic/v1/models?limit=1000", "/v1/models?limit=1000"],
            [path for path, _headers in self.requests],
        )

    def test_401_raises_immediately(self) -> None:
        base = self.start_server({"/v1/models?limit=1000": (401, b'{"error":"bad key"}', {})})
        with self.assertRaises(RuntimeError) as ctx:
            core.fetch_models(f"{base}/v1", "sk-secret")
        self.assertIn("HTTP 401", str(ctx.exception))
        self.assertEqual(1, len(self.requests))

    def test_redirect_is_treated_as_failure(self) -> None:
        base = self.start_server(
            {"/v1/models?limit=1000": (302, b"", {"Location": "https://elsewhere/models"})}
        )
        with self.assertRaises(RuntimeError) as ctx:
            core.fetch_models(f"{base}/v1", "k")
        self.assertIn("重定向", str(ctx.exception))

    def test_non_json_raises(self) -> None:
        base = self.start_server({"/v1/models?limit=1000": (200, b"<html>nope</html>", {})})
        with self.assertRaises(RuntimeError) as ctx:
            core.fetch_models(f"{base}/v1", "k")
        self.assertIn("不是 JSON", str(ctx.exception))

    def test_auth_headers_and_user_agent(self) -> None:
        cases = (
            ("openai", "Authorization", "Bearer sk-abc"),
            ("anthropic", "x-api-key", "sk-abc"),
            ("google", "x-goog-api-key", "sk-abc"),
        )
        for api_format, header, expected in cases:
            with self.subTest(api_format=api_format):
                self.requests.clear()
                base = self.start_server({"/v1/models?limit=1000": (200, self.payload("a"), {})})
                core.fetch_models(f"{base}/v1", "sk-abc", api_format=api_format, user_agent="MyUA/1.0")
                headers = {name.lower(): value for name, value in self.requests[0][1].items()}
                self.assertEqual(expected, headers.get(header.lower()))
                self.assertEqual("MyUA/1.0", headers.get("user-agent"))

    def test_api_key_is_redacted_in_logs(self) -> None:
        base = self.start_server({"/v1/models?limit=1000": (401, b'{"key":"sk-secret"}', {})})
        seen: list[str] = []
        with self.assertRaises(RuntimeError):
            core.fetch_models(f"{base}/v1", "sk-secret", log=seen.append)
        self.assertTrue(seen)
        self.assertNotIn("sk-secret", "\n".join(seen))

    def test_override_skips_derivation(self) -> None:
        base = self.start_server({"/custom/models?limit=1000": (200, self.payload("a"), {})})
        core.fetch_models(f"{base}/v1", "k", models_url=f"{base}/custom/models")
        self.assertEqual(["/custom/models?limit=1000"], [path for path, _h in self.requests])


class ApplyTests(TempDbCase):
    def test_apply_claude_writes_picker_and_backup(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO providers VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("claude-1", "claude", "Claude 卡", json.dumps({"env": {}}), "custom", 1, 1, "{}", 1, 0),
        )
        conn.commit()
        conn.close()

        result = core.apply_claude(
            "claude-1",
            [core.Model(id="claude-sonnet-4-5", display_name="Sonnet 4.5", description="line1\nline2")],
            gateway_discovery=True,
            db_path=self.db_path,
        )
        self.assertEqual(1, result["rows"])
        self.assertTrue(Path(result["backup"]).exists())
        settings = self.provider_settings("claude-1")
        self.assertEqual("claude-sonnet-4-5", settings["modelPicker"]["options"][0]["model"])
        self.assertEqual("Sonnet 4.5", settings["modelPicker"]["options"][0]["label"])
        self.assertEqual("line1", settings["modelPicker"]["options"][0]["description"])
        self.assertTrue(settings["modelPicker"]["replaceBuiltInOptions"])
        self.assertEqual("1", settings["env"]["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"])

    def test_apply_opencode_replace_and_merge(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO providers VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "oc-1",
                "opencode",
                "OpenCode 卡",
                json.dumps({"models": {"old-model": {"name": "Old", "limit": {"context": 1, "output": 1}}}}),
                "custom",
                1,
                1,
                "{}",
                1,
                0,
            ),
        )
        conn.commit()
        conn.close()

        core.apply_opencode(
            "oc-1", [core.Model(id="new-model", display_name="New")],
            context=200_000, output=8_192, db_path=self.db_path,
        )
        settings = self.provider_settings("oc-1")
        self.assertEqual(["new-model"], list(settings["models"]))
        self.assertEqual({"context": 200_000, "output": 8_192}, settings["models"]["new-model"]["limit"])

        core.apply_opencode(
            "oc-1", [core.Model(id="another", context=1_000_000)], merge=True, db_path=self.db_path,
        )
        settings = self.provider_settings("oc-1")
        self.assertEqual(["new-model", "another"], list(settings["models"]))
        self.assertEqual(1_000_000, settings["models"]["another"]["limit"]["context"])

    def test_apply_fanout_creates_cards_with_endpoints(self) -> None:
        result = core.apply_fanout(
            "provider-1", [core.Model(id="model-x"), core.Model(id="model-y")],
            app_type="codex", name_prefix="中转-", db_path=self.db_path,
        )
        self.assertEqual(2, result["rows"])
        rows = self.provider_rows("codex")
        self.assertEqual(3, len(rows))
        self.assertEqual(["中转-model-x", "中转-model-y"], [r["name"] for r in rows[1:]])
        conn = sqlite3.connect(self.db_path)
        endpoints = conn.execute(
            "SELECT provider_id, url FROM provider_endpoints WHERE provider_id=?",
            (result["cards"][0]["id"],),
        ).fetchall()
        conn.close()
        self.assertEqual([("http://127.0.0.1:15721/v1",)], [(e[1],) for e in endpoints])

    def test_apply_fanout_rejects_opencode(self) -> None:
        with self.assertRaises(ValueError):
            core.apply_fanout("provider-1", [core.Model(id="m")], app_type="opencode", db_path=self.db_path)

    def test_create_provider_and_delete(self) -> None:
        created = core.create_provider(
            "claude", "我的中转", "https://api.example.com/v1/", "sk-1", db_path=self.db_path,
        )
        self.assertTrue(Path(created["backup"]).exists())
        settings = self.provider_settings(created["id"])
        self.assertEqual("https://api.example.com/v1", settings["env"]["ANTHROPIC_BASE_URL"])
        self.assertEqual("sk-1", settings["env"]["ANTHROPIC_AUTH_TOKEN"])

        deleted = core.delete_providers("claude", [created["id"]], force=True, db_path=self.db_path)
        self.assertEqual(1, deleted["deleted"])
        conn = sqlite3.connect(self.db_path)
        left = conn.execute("SELECT COUNT(*) FROM providers WHERE id=?", (created["id"],)).fetchone()[0]
        conn.close()
        self.assertEqual(0, left)

    def test_delete_refuses_current_card_without_force(self) -> None:
        with self.assertRaises(ValueError):
            core.delete_providers("codex", ["provider-1"], db_path=self.db_path)
        core.delete_providers("codex", ["provider-1"], force=True, db_path=self.db_path)

    def test_delete_refuses_default_card(self) -> None:
        with self.assertRaises(ValueError):
            core.delete_providers("claude", ["default"], force=True, db_path=self.db_path)

    def test_rollback_restores_and_keeps_safety_backup(self) -> None:
        core.DB_PATH = self.db_path
        core.CODEX_CATALOG = self.catalog_path
        self.catalog_path.write_text(json.dumps({"models": [{"slug": "old"}]}), encoding="utf-8")
        backup = core.backup_file(self.catalog_path)
        self.catalog_path.write_text(json.dumps({"models": [{"slug": "new"}]}), encoding="utf-8")

        result = core.rollback(str(backup), "catalog")
        self.assertTrue(Path(result["backup"]).exists())
        restored = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        self.assertEqual("old", restored["models"][0]["slug"])
        safety = json.loads(Path(result["backup"]).read_text(encoding="utf-8"))
        self.assertEqual("new", safety["models"][0]["slug"])

    def test_rollback_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            core.rollback(str(self.root / "nope.bak"), "catalog")

    def test_backup_names_are_unique_within_same_second(self) -> None:
        target = self.root / "data.json"
        target.write_text("{}", encoding="utf-8")
        first = core.backup_file(target)
        second = core.backup_file(target)
        self.assertNotEqual(first, second)
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())

        core.DB_PATH = self.db_path
        db_first = core.backup_db(self.db_path)
        db_second = core.backup_db(self.db_path)
        self.assertNotEqual(db_first, db_second)


class SmallHelperTests(unittest.TestCase):
    def test_merge_json_entries_replace_dedupes(self) -> None:
        out, stats = core.merge_json_entries(
            {"models": [{"model": "old"}]},
            [{"model": "b"}, {"model": "b"}, {"model": "a"}],
            key="model",
        )
        self.assertEqual(["b", "a"], [item["model"] for item in out])
        self.assertEqual({"added": 2, "preserved": 0}, stats)

    def test_merge_json_entries_skips_blank_keys(self) -> None:
        out, stats = core.merge_json_entries(None, [{"model": ""}, {"model": "a"}], key="model")
        self.assertEqual(["a"], [item["model"] for item in out])
        self.assertEqual(1, stats["added"])

    def test_parse_pick_ranges_and_bounds(self) -> None:
        self.assertEqual([1, 3, 4, 5], core.parse_pick("1,3-5,9", 5))
        self.assertEqual([], core.parse_pick("", 3))

    def test_redact_ignores_short_secrets(self) -> None:
        self.assertEqual("sk-secret", core.redact("sk-secret", ["sk", ""]))
        self.assertEqual("***", core.redact("sk-secret", ["sk-secret"]))

    def test_save_and_load_models_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            models = [
                core.Model(id="a", display_name="A", context=1, output=2, input_modalities=["text"]),
                core.Model(id="b"),
            ]
            js, txt = core.save_models(models, Path(tmp))
            self.assertTrue(js.exists())
            self.assertEqual("a\nb\n", txt.read_text(encoding="utf-8"))
            loaded = core.load_models(js)
            self.assertEqual([m.to_dict() for m in models], [m.to_dict() for m in loaded])

    def test_build_model_picker_skips_label_when_same(self) -> None:
        picker = core.build_model_picker([core.Model(id="a", display_name="a")])
        self.assertEqual([{"model": "a"}], picker["options"])

    def test_strip_compat_suffix(self) -> None:
        self.assertEqual("https://x.com", core.strip_compat_suffix("https://x.com/api/anthropic"))
        self.assertIsNone(core.strip_compat_suffix("https://x.com/v1"))


if __name__ == "__main__":
    unittest.main()
