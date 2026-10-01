import unittest

from nice_ui.app import main_shortcut_script


class MainShortcutsTest(unittest.TestCase):
    def test_main_shortcuts_target_numbered_tabs(self):
        script = main_shortcut_script()

        for number in range(1, 6):
            self.assertIn(f'"key": "{number}"', script)
            self.assertIn(f'"code": "Digit{number}"', script)
            self.assertIn(f".main-tab-shortcut-{number}", script)


if __name__ == "__main__":
    unittest.main()
