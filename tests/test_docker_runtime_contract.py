import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class DockerRuntimeContractTests(unittest.TestCase):
    def test_gunicorn_timeout_outlasts_fish_tts_upstream(self) -> None:
        dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
        tts_source = (REPO_ROOT / "jianying_utils" / "tts_tool.py").read_text(encoding="utf-8")

        gunicorn_match = re.search(r'"--timeout",\s*"(\d+)"', dockerfile)
        fish_method = tts_source.split("def synthesize_fish(", 1)[1].split("def list_voices(", 1)[0]
        upstream_match = re.search(r"urlopen\(request, timeout=(\d+)\)", fish_method)

        self.assertIsNotNone(gunicorn_match, "Dockerfile must declare Gunicorn --timeout")
        self.assertIsNotNone(upstream_match, "Fish TTS must declare its upstream timeout")

        gunicorn_timeout = int(gunicorn_match.group(1))
        upstream_timeout = int(upstream_match.group(1))
        self.assertEqual(gunicorn_timeout, 300)
        self.assertGreater(gunicorn_timeout, upstream_timeout)

    def test_pip_install_has_bounded_network_resilience(self) -> None:
        dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
        pip_install = re.search(r"^RUN pip install .+$", dockerfile, re.MULTILINE)

        self.assertIsNotNone(pip_install, "Dockerfile must install Python requirements")
        self.assertEqual(
            pip_install.group(0).rstrip("\r"),
            "RUN pip install --no-cache-dir --timeout 180 --retries 10 -r requirements.txt",
        )


if __name__ == "__main__":
    unittest.main()
