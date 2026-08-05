import unittest

from nice_ui.keyboard_shortcuts import KeyboardShortcut, default_key_code, shortcut_script


class KeyboardShortcutsTest(unittest.TestCase):
    def test_shortcut_script_contains_editable_guard_and_bindings(self):
        script = shortcut_script(
            "test",
            [
                KeyboardShortcut("1", ".tab-one"),
                KeyboardShortcut(
                    "s",
                    ".save-action",
                    ctrl=True,
                    ignore_editable=False,
                ),
                KeyboardShortcut("ArrowLeft", ".previous"),
            ],
        )

        self.assertIn("__behaviourHubShortcut_test", script)
        self.assertIn(".cm-editor", script)
        self.assertIn('"selector": ".tab-one"', script)
        self.assertIn('"code": "Digit1"', script)
        self.assertIn('"selector": ".save-action"', script)
        self.assertIn('"code": "KeyS"', script)
        self.assertIn('"code": "ArrowLeft"', script)
        self.assertIn('"ctrl": true', script)
        self.assertIn('"ignoreEditable": false', script)

    def test_default_key_codes_make_shortcuts_physical(self):
        self.assertEqual(default_key_code("c"), "KeyC")
        self.assertEqual(default_key_code("S"), "KeyS")
        self.assertEqual(default_key_code("1"), "Digit1")
        self.assertEqual(default_key_code("ArrowRight"), "ArrowRight")
        self.assertIsNone(default_key_code("Escape"))


if __name__ == "__main__":
    unittest.main()
