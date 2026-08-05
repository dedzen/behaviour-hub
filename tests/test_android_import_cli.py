from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from timeline.cli import app


class _FakeResponse:
    def __init__(self, data: bytes = b""):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self.data


class AndroidImportCliTest(unittest.TestCase):
    def test_android_download_reads_unlock_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "unlock-events.jsonl"
            with patch(
                "timeline.commands.import_e.urllib.request.urlopen",
                return_value=_FakeResponse(b'{"event_type":"KEYGUARD_HIDDEN"}\n'),
            ) as urlopen:
                result = CliRunner().invoke(
                    app,
                    [
                        "import",
                        "android-download",
                        "192.168.3.55:8080",
                        "--output",
                        str(output),
                    ],
                )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(output.read_bytes(), b'{"event_type":"KEYGUARD_HIDDEN"}\n')
            urlopen.assert_called_once_with(
                "http://192.168.3.55:8080/unlock-events.jsonl",
                timeout=10.0,
            )

    def test_android_clear_deletes_unlock_endpoint(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["timeout"] = timeout
            return _FakeResponse()

        with patch(
            "timeline.commands.import_e.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            result = CliRunner().invoke(
                app,
                [
                    "import",
                    "android-clear",
                    "192.168.3.55:8080",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(captured, {
            "url": "http://192.168.3.55:8080/unlock-events.jsonl",
            "method": "DELETE",
            "timeout": 10.0,
        })


if __name__ == "__main__":
    unittest.main()
