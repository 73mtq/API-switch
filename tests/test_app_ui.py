import tempfile
import tkinter
import unittest
from pathlib import Path

import app as ui
import ccs_models as core


class TokenParsingTests(unittest.TestCase):
    def test_valid_forms(self) -> None:
        cases = {
            "1000000": 1_000_000,
            "256K": 256_000,
            "256k": 256_000,
            "1M": 1_000_000,
            "0.5m": 500_000,
            "1,000,000": 1_000_000,
            " 128K ": 128_000,
            "131_072": 131_072,
        }
        for raw, expected in cases.items():
            self.assertEqual(ui.parse_tokens(raw, field="上下文长度"), expected, raw)

    def test_invalid_forms(self) -> None:
        for raw in ("", "   ", "abc", "12x", "0", "-3", "1.2.3", "K"):
            with self.assertRaises(ValueError, msg=raw):
                ui.parse_tokens(raw, field="上下文长度")

    def test_format_context(self) -> None:
        self.assertEqual(ui._fmt_ctx(0), "")
        self.assertEqual(ui._fmt_ctx(999), "999")
        self.assertEqual(ui._fmt_ctx(200_000), "200K")
        self.assertEqual(ui._fmt_ctx(1_000_000), "1M")
        self.assertEqual(ui._fmt_ctx(1_500_000), "1.5M")


class FilterSortTests(unittest.TestCase):
    def setUp(self) -> None:
        self.models = [
            core.Model(id="claude-sonnet-4-5", display_name="Sonnet 4.5", owned_by="anthropic", context=200_000),
            core.Model(id="gpt-5.2-codex", display_name="Codex", owned_by="openai", context=0),
            core.Model(id="gemini-3-pro", display_name="Gemini Pro", owned_by="google", context=1_000_000),
        ]
        self.order = list(range(len(self.models)))

    def test_filter_matches_id_and_name(self) -> None:
        self.assertEqual(ui.filter_indices(self.models, self.order, "gpt"), [1])
        self.assertEqual(ui.filter_indices(self.models, self.order, "SONNET"), [0])
        self.assertEqual(ui.filter_indices(self.models, self.order, "gemini pro"), [2])
        self.assertEqual(ui.filter_indices(self.models, self.order, "nothing"), [])
        self.assertEqual(ui.filter_indices(self.models, self.order, "  "), self.order)

    def test_sort_ascending_and_descending(self) -> None:
        self.assertEqual(ui.sort_indices(self.models, "id", False), [0, 2, 1])
        self.assertEqual(ui.sort_indices(self.models, "id", True), [1, 2, 0])
        self.assertEqual(ui.sort_indices(self.models, "name", False), [1, 2, 0])
        self.assertEqual(ui.sort_indices(self.models, "by", False), [0, 2, 1])
        self.assertEqual(ui.sort_indices(self.models, "ctx", False), [1, 0, 2])
        self.assertEqual(ui.sort_indices(self.models, "ctx", True), [2, 0, 1])

    def test_sort_keeps_fetch_order_for_equal_keys(self) -> None:
        models = [core.Model(id="same"), core.Model(id="same"), core.Model(id="other")]
        self.assertEqual(ui.sort_indices(models, "id", False), [2, 0, 1])


class ContrastTests(unittest.TestCase):
    TEXT_PAIRS = (
        ("text", "card"),
        ("text", "bg"),
        ("text2", "card"),
        ("text3", "card"),
        ("accent_text", "accent"),
        ("success", "card"),
        ("danger", "card"),
    )
    CONTROL_PAIRS = (
        ("accent", "card"),
        ("accent", "bg"),
        ("control_border", "card"),
        ("accent", "select"),
    )

    def test_text_pairs_meet_aa(self) -> None:
        for label, palette in (("light", ui.LIGHT), ("dark", ui.DARK)):
            for fg, bg in self.TEXT_PAIRS:
                ratio = ui.contrast_ratio(palette[fg], palette[bg])
                self.assertGreaterEqual(ratio, 4.5, f"{label} {fg} on {bg} = {ratio:.2f}")

    def test_control_pairs_meet_non_text_threshold(self) -> None:
        for label, palette in (("light", ui.LIGHT), ("dark", ui.DARK)):
            for fg, bg in self.CONTROL_PAIRS:
                ratio = ui.contrast_ratio(palette[fg], palette[bg])
                self.assertGreaterEqual(ratio, 3.0, f"{label} {fg} on {bg} = {ratio:.2f}")


class ConfigTests(unittest.TestCase):
    def test_defaults_and_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ui.json"
            self.assertEqual(ui.load_ui_config(path), {"theme": "system", "geometry": "", "log_collapsed": False})
            ui.save_ui_config(path, {"theme": "dark", "geometry": "1200x800+10+20", "log_collapsed": True})
            loaded = ui.load_ui_config(path)
            self.assertEqual(loaded["theme"], "dark")
            self.assertEqual(loaded["geometry"], "1200x800+10+20")
            self.assertTrue(loaded["log_collapsed"])


class PaletteTests(unittest.TestCase):
    def test_palette_for_explicit_modes(self) -> None:
        self.assertEqual(ui.palette_for("light"), ui.LIGHT)
        self.assertEqual(ui.palette_for("dark"), ui.DARK)
        self.assertNotEqual(ui.palette_for("light")["card"], ui.palette_for("dark")["card"])


class AppSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        try:
            self.app = ui.App(config_path=Path(self._tmp.name) / "ui.json")
        except tkinter.TclError as exc:
            self.skipTest(f"没有可用的显示：{exc}")
        self.app.withdraw()

    def tearDown(self) -> None:
        self.app.destroy()
        self._tmp.cleanup()

    def test_render_and_selection(self) -> None:
        app = self.app
        app.models = [
            core.Model(id="claude-sonnet-4-5", display_name="Sonnet 4.5", owned_by="anthropic", context=200_000),
            core.Model(id="gpt-5.2-codex", display_name="Codex", owned_by="openai", context=0),
            core.Model(id="gemini-3-pro", display_name="Gemini Pro", owned_by="google", context=1_000_000),
        ]
        app.render()
        self.assertEqual(app.visible, [0, 1, 2])
        self.assertEqual(len(app.tree.get_children()), 3)

        app.sel("gw")
        self.assertEqual(app.picked, {0})
        app.sel("all")
        self.assertEqual(app.picked, {0, 1, 2})
        app.sel("inv")
        self.assertEqual(app.picked, set())

        app.search_var.set("gpt")
        app.render()
        self.assertEqual(app.visible, [1])
        app.sel("all")
        self.assertEqual(app.picked, {1})
        app.sel("none")
        self.assertEqual(app.picked, set())

        app.search_var.set("")
        app.render()
        app._sort_by("id")
        self.assertEqual(app.visible, [0, 2, 1])
        app._sort_by("id")
        self.assertEqual(app.visible, [1, 2, 0])
        app._sort_by("id")
        self.assertEqual(app.visible, [0, 1, 2])

    def test_payload_and_action_state(self) -> None:
        app = self.app
        app.models = [
            core.Model(id="claude-sonnet-4-5", display_name="Sonnet", owned_by="anthropic", context=200_000),
            core.Model(id="gpt-5.2-codex", display_name="Codex", owned_by="openai"),
        ]
        app.render()
        app.picked = {0, 1}
        app.provider_ids = ["provider-1"]
        app.provider.configure(values=["测试卡（provider-1）"])
        app.provider.current(0)
        app._cc_running = False
        app._update_action_state()
        self.assertEqual(app.reason.cget("text"), "")
        self.assertTrue(app.apply_btn._enabled)

        body = app.payload()
        self.assertEqual(body["mode"], "list")
        self.assertEqual(body["app"], "claude")
        self.assertEqual(body["providerId"], "provider-1")
        self.assertEqual(len(body["models"]), 2)
        self.assertEqual(body["context"], 1_000_000)
        self.assertEqual([m.id for m in ui._models_from(body)], ["claude-sonnet-4-5", "gpt-5.2-codex"])

    def test_validation_and_reason(self) -> None:
        app = self.app
        app.models = [core.Model(id="claude-sonnet-4-5")]
        app.picked = {0}
        app.app.set("opencode")
        app.sync_mode()
        app.provider_ids = ["provider-1"]
        app.provider.configure(values=["测试卡（provider-1）"])
        app.provider.current(0)
        app._cc_running = False
        app.ctx_var.set("abc")
        app._validate_params()
        self.assertFalse(app._ctx_ok)
        self.assertIn("上下文长度", app.ctx_err.cget("text"))
        self.assertIn("参数", app.reason.cget("text"))
        app.ctx_var.set("256K")
        app._validate_params()
        self.assertTrue(app._ctx_ok)
        self.assertEqual(app.ctx_err.cget("text"), "")

    def test_preview_summary_requires_models(self) -> None:
        body = {"mode": "list", "app": "claude", "models": [], "providerId": None}
        with self.assertRaises(ValueError):
            ui._preview_summary(body)

    def test_theme_switch(self) -> None:
        app = self.app
        app.theme_box.current(1)
        app._on_theme_selected()
        self.assertEqual(app.pal["card"], ui.LIGHT["card"])
        app.theme_box.current(2)
        app._on_theme_selected()
        self.assertEqual(app.pal["card"], ui.DARK["card"])
        app.theme_box.current(0)
        app._on_theme_selected()


if __name__ == "__main__":
    unittest.main()
