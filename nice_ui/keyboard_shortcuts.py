from __future__ import annotations

from dataclasses import dataclass
import json


EDITABLE_SELECTOR = ",".join([
    "input",
    "textarea",
    "select",
    '[contenteditable="true"]',
    ".cm-content",
    ".cm-editor",
    ".q-field__native",
])


@dataclass(frozen=True, slots=True)
class KeyboardShortcut:
    key: str
    selector: str
    code: str | None = None
    ctrl: bool = False
    meta: bool = False
    shift: bool = False
    alt: bool = False
    ignore_editable: bool = True


def shortcut_script(namespace: str, shortcuts: list[KeyboardShortcut]) -> str:
    bindings = [
        {
            "key": shortcut.key,
            "code": shortcut.code or default_key_code(shortcut.key),
            "selector": shortcut.selector,
            "ctrl": shortcut.ctrl,
            "meta": shortcut.meta,
            "shift": shortcut.shift,
            "alt": shortcut.alt,
            "ignoreEditable": shortcut.ignore_editable,
        }
        for shortcut in shortcuts
    ]

    return f"""
    <script>
    (() => {{
      const installedFlag = {json.dumps(f"__behaviourHubShortcut_{namespace}")};
      if (window[installedFlag]) {{
        return;
      }}
      window[installedFlag] = true;

      const editableSelector = {json.dumps(EDITABLE_SELECTOR)};
      const bindings = {json.dumps(bindings)};

      const activeElementIsEditable = () => {{
        const active = document.activeElement;
        return Boolean(active && active.closest && active.closest(editableSelector));
      }};

      const modifierMatches = (event, binding) => (
        Boolean(event.ctrlKey) === binding.ctrl &&
        Boolean(event.metaKey) === binding.meta &&
        Boolean(event.shiftKey) === binding.shift &&
        Boolean(event.altKey) === binding.alt
      );

      document.addEventListener('keydown', (event) => {{
        if (event.defaultPrevented || event.repeat) {{
          return;
        }}

        const key = event.key.toLowerCase();
        for (const binding of bindings) {{
          const codeMatches = binding.code && event.code === binding.code;
          const keyMatches = !binding.code && binding.key && key === binding.key.toLowerCase();
          if (!codeMatches && !keyMatches) {{
            continue;
          }}
          if (!modifierMatches(event, binding)) {{
            continue;
          }}
          if (binding.ignoreEditable && activeElementIsEditable()) {{
            return;
          }}

          const target = document.querySelector(binding.selector);
          if (!target) {{
            return;
          }}

          event.preventDefault();
          target.click();
          return;
        }}
      }}, true);
    }})();
    </script>
    """


def default_key_code(key: str) -> str | None:
    if len(key) == 1 and key.isascii() and key.isalpha():
        return f"Key{key.upper()}"
    if len(key) == 1 and key.isdigit():
        return f"Digit{key}"
    if key.startswith("Arrow"):
        return key
    return None
