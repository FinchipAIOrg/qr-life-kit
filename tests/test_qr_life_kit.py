from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "qr_life_kit.py"
SPEC = importlib.util.spec_from_file_location("qr_life_kit", MODULE_PATH)
assert SPEC and SPEC.loader
qr_life_kit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = qr_life_kit
SPEC.loader.exec_module(qr_life_kit)


class PayloadTests(unittest.TestCase):
    def test_url_normalizes_scheme(self):
        payload = qr_life_kit.build_payload({"type": "url", "data": {"url": "finchip.ai"}})
        self.assertEqual(payload.text, "https://finchip.ai")
        self.assertFalse(payload.sensitive)

    def test_url_rejects_unsafe_scheme(self):
        with self.assertRaises(qr_life_kit.SpecError):
            qr_life_kit.build_payload(
                {"type": "url", "data": {"url": "javascript:alert(1)"}}
            )

    def test_url_rejects_embedded_credentials(self):
        with self.assertRaises(qr_life_kit.SpecError):
            qr_life_kit.build_payload(
                {"type": "url", "data": {"url": "https://user:pass@example.com"}}
            )

    def test_wifi_escapes_reserved_characters(self):
        payload = qr_life_kit.build_payload(
            {
                "type": "wifi",
                "data": {"ssid": "Cafe;Guest", "password": "a:b,c", "security": "WPA"},
            }
        )
        self.assertEqual(payload.text, r"WIFI:T:WPA;S:Cafe\;Guest;P:a\:b\,c;H:false;;")
        self.assertTrue(payload.sensitive)

    def test_contact_builds_vcard(self):
        payload = qr_life_kit.build_payload(
            {
                "type": "vcard",
                "data": {
                    "name": "FinChip Team",
                    "phone": "+1 202 555 0147",
                    "email": "hello@example.com",
                    "url": "finchip.ai",
                },
            }
        )
        self.assertIn("BEGIN:VCARD\r\nVERSION:3.0", payload.text)
        self.assertIn("URL:https://finchip.ai", payload.text)
        self.assertTrue(payload.sensitive)

    def test_event_rejects_reverse_times(self):
        with self.assertRaises(qr_life_kit.SpecError):
            qr_life_kit.build_payload(
                {
                    "type": "event",
                    "data": {
                        "title": "Demo",
                        "start": "2026-07-17T12:00:00+08:00",
                        "end": "2026-07-17T11:00:00+08:00",
                    },
                }
            )

    def test_event_rejects_mixed_timezone_styles(self):
        with self.assertRaises(qr_life_kit.SpecError):
            qr_life_kit.build_payload(
                {
                    "type": "event",
                    "data": {
                        "title": "Demo",
                        "start": "2026-07-17T12:00:00",
                        "end": "2026-07-17T13:00:00+08:00",
                    },
                }
            )

    def test_every_supported_payload_type_builds(self):
        specs = [
            {"type": "email", "data": {"to": "hello@example.com", "subject": "Hi"}},
            {"type": "sms", "data": {"phone": "+12025550147", "message": "Hi"}},
            {"type": "phone", "data": {"phone": "+12025550147"}},
            {"type": "geo", "data": {"latitude": 31.2304, "longitude": 121.4737}},
            {
                "type": "event",
                "data": {
                    "title": "Demo",
                    "start": "2026-07-17T12:00:00+08:00",
                    "end": "2026-07-17T13:00:00+08:00",
                },
            },
            {"type": "text", "data": {"text": "Hello QR"}},
        ]
        for spec in specs:
            with self.subTest(kind=spec["type"]):
                payload = qr_life_kit.build_payload(spec)
                self.assertTrue(payload.text)

    def test_plain_text_allows_line_breaks(self):
        payload = qr_life_kit.build_payload(
            {"type": "text", "data": {"text": "First line\nSecond line"}}
        )
        self.assertEqual(payload.text, "First line\nSecond line")


class BuildTests(unittest.TestCase):
    def write_spec(self, root: Path, spec: dict) -> Path:
        path = root / "spec.json"
        path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        return path

    def test_url_build_round_trip_and_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec_path = self.write_spec(
                root,
                {
                    "type": "url",
                    "data": {"url": "https://finchip.ai/"},
                    "card": {
                        "title": "Open finchip.ai",
                        "subtitle": "Scan with your camera",
                        "theme": "paper",
                        "format": "portrait",
                        "show_payload": True,
                    },
                },
            )
            output = root / "result"
            manifest = qr_life_kit.build(spec_path, output, include_payload=False)
            self.assertEqual(manifest["verification_status"], "passed")
            for name in (
                "qr.png",
                "qr.svg",
                "card.png",
                "card.html",
                "verification.json",
                "manifest.json",
                "spec-redacted.json",
            ):
                self.assertTrue((output / name).is_file(), name)
            self.assertFalse((output / "payload.txt").exists())
            verification = json.loads((output / "verification.json").read_text())
            self.assertTrue(verification["raw_qr"]["passed"])
            self.assertTrue(verification["card_png"]["passed"])
            self.assertEqual(
                qr_life_kit.decode_image(output / "card.png"), ["https://finchip.ai/"]
            )

    def test_wifi_build_redacts_password_and_forces_payload_hidden(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec_path = self.write_spec(
                root,
                {
                    "type": "wifi",
                    "data": {
                        "ssid": "Studio Guest",
                        "password": "top-secret",
                        "security": "WPA",
                    },
                    "card": {"show_payload": True, "theme": "sunset"},
                },
            )
            output = root / "result"
            qr_life_kit.build(spec_path, output, include_payload=False)
            redacted = (output / "spec-redacted.json").read_text()
            card_html = (output / "card.html").read_text()
            self.assertNotIn("top-secret", redacted)
            self.assertNotIn("Studio Guest", redacted)
            self.assertNotIn("top-secret", card_html)
            self.assertNotIn("Studio Guest", card_html)
            self.assertFalse((output / "payload.txt").exists())

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec_path = self.write_spec(root, {"type": "text", "data": {"text": "hello"}})
            output = root / "result"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("keep")
            with self.assertRaises(qr_life_kit.SpecError):
                qr_life_kit.build(spec_path, output, include_payload=False)
            self.assertEqual(marker.read_text(), "keep")

    def test_payload_capacity_is_checked_before_rendering(self):
        payload = qr_life_kit.build_payload(
            {"type": "text", "data": {"text": "x" * 1300}}
        )
        with self.assertRaises(qr_life_kit.SpecError):
            qr_life_kit.parse_options({}, payload)


if __name__ == "__main__":
    unittest.main()
