import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import ccs_models as core


class CodexMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db_path = root / "cc-switch.db"
        self.catalog_path = root / "catalog.json"
        self.old_backup_dir = core.BACKUP_DIR
        core.BACKUP_DIR = root / "backups"

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "CREATE TABLE providers ("
            "id TEXT PRIMARY KEY, app_type TEXT, name TEXT, settings_config TEXT, "
            "category TEXT, created_at INTEGER, sort_index INTEGER, meta TEXT, "
            "is_current INTEGER, in_failover_queue INTEGER)"
        )
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
        conn.commit()
        conn.close()

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

    def tearDown(self) -> None:
        core.BACKUP_DIR = self.old_backup_dir
        self.tmp.cleanup()

    def apply(self, models: list[core.Model], *, merge: bool) -> dict:
        return core.apply_codex(
            models,
            "provider-1",
            context=999,
            merge=merge,
            catalog_path=self.catalog_path,
            db_path=self.db_path,
        )

    def provider_settings(self) -> dict:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT settings_config FROM providers WHERE id='provider-1'"
        ).fetchone()
        conn.close()
        return json.loads(row[0])

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


if __name__ == "__main__":
    unittest.main()
