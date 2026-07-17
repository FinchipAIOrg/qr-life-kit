#!/usr/bin/env python3
"""Build and verify static QR life cards from a JSON specification."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

try:
    import qrcode
    from PIL import Image, ImageDraw, ImageFont
    from qrcode.constants import (
        ERROR_CORRECT_H,
        ERROR_CORRECT_L,
        ERROR_CORRECT_M,
        ERROR_CORRECT_Q,
    )
    from qrcode.image.svg import SvgPathImage
except ImportError as exc:
    print(
        "Missing generation dependencies. Run: python3 -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc

try:
    import zxingcpp
except ImportError as exc:
    print(
        "Missing verification dependency. Run: python3 -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc


ERROR_LEVELS = {
    "L": ERROR_CORRECT_L,
    "M": ERROR_CORRECT_M,
    "Q": ERROR_CORRECT_Q,
    "H": ERROR_CORRECT_H,
}

MAX_BYTE_CAPACITY = {"L": 2953, "M": 2331, "Q": 1663, "H": 1273}
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
UNSAFE_MULTILINE_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

THEMES = {
    "paper": {
        "page": "#F3F0E8",
        "card": "#FFFDF8",
        "ink": "#171716",
        "muted": "#6D695F",
        "accent": "#171716",
        "line": "#DDD7CA",
        "accent_text": "#FFFDF8",
    },
    "midnight": {
        "page": "#09111F",
        "card": "#101B2D",
        "ink": "#F4F7FC",
        "muted": "#A9B7CC",
        "accent": "#2B70FF",
        "line": "#293A55",
        "accent_text": "#FFFFFF",
    },
    "sunset": {
        "page": "#F7E4D2",
        "card": "#FFF8EE",
        "ink": "#322019",
        "muted": "#826456",
        "accent": "#E25A37",
        "line": "#E8C7B1",
        "accent_text": "#FFFFFF",
    },
}


class SpecError(ValueError):
    """Raised when a build specification is invalid."""


@dataclass(frozen=True)
class Payload:
    kind: str
    text: str
    safe_display: str
    sensitive: bool


def require_string(data: dict[str, Any], key: str, *, allow_empty: bool = False) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise SpecError(f"data.{key} must be a string")
    value = value.strip()
    if not allow_empty and not value:
        raise SpecError(f"data.{key} must not be empty")
    if CONTROL_RE.search(value):
        raise SpecError(f"data.{key} contains control characters")
    return value


def optional_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise SpecError(f"data.{key} must be a string")
    value = value.strip()
    if CONTROL_RE.search(value):
        raise SpecError(f"data.{key} contains control characters")
    return value


def multiline_string(data: dict[str, Any], key: str, *, required: bool = False) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise SpecError(f"data.{key} must be a string")
    value = value.strip()
    if required and not value:
        raise SpecError(f"data.{key} must not be empty")
    if UNSAFE_MULTILINE_CONTROL_RE.search(value):
        raise SpecError(f"data.{key} contains unsupported control characters")
    return value


def normalize_url(value: str) -> str:
    value = value.strip()
    if not value:
        raise SpecError("data.url must not be empty")
    if CONTROL_RE.search(value):
        raise SpecError("data.url contains control characters")
    explicit_scheme = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value)
    if explicit_scheme and "://" not in value:
        raise SpecError("URL payloads permit only complete http and https URLs")
    if "://" not in value:
        value = "https://" + value
    parts = urlsplit(value)
    if parts.scheme.lower() not in {"http", "https"}:
        raise SpecError("URL payloads permit only http and https")
    if not parts.hostname:
        raise SpecError("URL must include a hostname")
    if parts.username or parts.password:
        raise SpecError("URL must not embed a username or password")
    try:
        host = parts.hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise SpecError("URL hostname is invalid") from exc
    try:
        port = parts.port
    except ValueError as exc:
        raise SpecError("URL port is invalid") from exc
    if port is not None and not 1 <= port <= 65535:
        raise SpecError("URL port must be between 1 and 65535")
    netloc = host
    if ":" in host and not host.startswith("["):
        netloc = f"[{host}]"
    if port:
        netloc += f":{port}"
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "", parts.query, parts.fragment))


def escape_wifi(value: str) -> str:
    result = value.replace("\\", "\\\\")
    for char in (";", ",", ":", '"'):
        result = result.replace(char, "\\" + char)
    return result


def escape_vcard(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def escape_ics(value: str) -> str:
    return escape_vcard(value)


def format_ics_time(value: str, field: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SpecError(f"data.{field} must be ISO 8601") from exc
    if parsed.tzinfo is None:
        return parsed.strftime("%Y%m%dT%H%M%S")
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_iso_datetime(value: str, field: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SpecError(f"data.{field} must be ISO 8601") from exc


def build_payload(spec: dict[str, Any]) -> Payload:
    kind = spec.get("type")
    data = spec.get("data")
    if not isinstance(kind, str):
        raise SpecError("type must be a string")
    kind = kind.lower().strip()
    if not isinstance(data, dict):
        raise SpecError("data must be an object")

    if kind == "url":
        value = normalize_url(require_string(data, "url"))
        return Payload(kind, value, value, False)

    if kind == "wifi":
        ssid = require_string(data, "ssid")
        security = str(data.get("security", "WPA")).strip()
        normalized_security = {"wpa": "WPA", "wep": "WEP", "nopass": "nopass"}.get(
            security.lower()
        )
        if not normalized_security:
            raise SpecError("data.security must be WPA, WEP, or nopass")
        password = optional_string(data, "password")
        if normalized_security != "nopass" and not password:
            raise SpecError("data.password is required for secured Wi-Fi")
        hidden = data.get("hidden", False)
        if not isinstance(hidden, bool):
            raise SpecError("data.hidden must be a boolean")
        text = (
            f"WIFI:T:{normalized_security};S:{escape_wifi(ssid)};"
            f"P:{escape_wifi(password)};H:{str(hidden).lower()};;"
        )
        return Payload(kind, text, f"Wi-Fi: {ssid}", True)

    if kind in {"vcard", "contact"}:
        name = require_string(data, "name")
        fields = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{escape_vcard(name)}"]
        optional_map = [
            ("organization", "ORG"),
            ("title", "TITLE"),
            ("phone", "TEL;TYPE=CELL"),
            ("email", "EMAIL"),
            ("url", "URL"),
        ]
        for key, label in optional_map:
            value = optional_string(data, key)
            if value:
                if key == "email" and not EMAIL_RE.match(value):
                    raise SpecError("data.email is not a valid email address")
                if key == "url":
                    value = normalize_url(value)
                fields.append(f"{label}:{escape_vcard(value)}")
        fields.append("END:VCARD")
        return Payload("vcard", "\r\n".join(fields), f"Contact: {name}", True)

    if kind == "email":
        recipient = require_string(data, "to")
        if not EMAIL_RE.match(recipient):
            raise SpecError("data.to is not a valid email address")
        query = {
            "subject": optional_string(data, "subject"),
            "body": multiline_string(data, "body"),
        }
        query = {key: value for key, value in query.items() if value}
        text = f"mailto:{quote(recipient, safe='@')}"
        if query:
            text += "?" + urlencode(query)
        return Payload(kind, text, f"Email: {recipient}", True)

    if kind == "sms":
        phone = require_string(data, "phone")
        if not re.fullmatch(r"[+0-9(). -]{3,32}", phone):
            raise SpecError("data.phone contains unsupported characters")
        message = multiline_string(data, "message")
        return Payload(kind, f"SMSTO:{phone}:{message}", f"SMS: {phone}", True)

    if kind == "phone":
        phone = require_string(data, "phone")
        if not re.fullmatch(r"[+0-9(). -]{3,32}", phone):
            raise SpecError("data.phone contains unsupported characters")
        return Payload(kind, f"tel:{phone}", f"Call: {phone}", True)

    if kind == "geo":
        latitude = data.get("latitude")
        longitude = data.get("longitude")
        if not isinstance(latitude, (int, float)) or not -90 <= latitude <= 90:
            raise SpecError("data.latitude must be a number from -90 to 90")
        if not isinstance(longitude, (int, float)) or not -180 <= longitude <= 180:
            raise SpecError("data.longitude must be a number from -180 to 180")
        label = optional_string(data, "label")
        text = f"geo:{latitude},{longitude}"
        if label:
            text += "?" + urlencode({"q": f"{latitude},{longitude}({label})"})
        return Payload(kind, text, label or f"{latitude}, {longitude}", False)

    if kind == "event":
        title = require_string(data, "title")
        start_raw = require_string(data, "start")
        end_raw = require_string(data, "end")
        start_dt = parse_iso_datetime(start_raw, "start")
        end_dt = parse_iso_datetime(end_raw, "end")
        if (start_dt.tzinfo is None) != (end_dt.tzinfo is None):
            raise SpecError("data.start and data.end must use the same timezone style")
        start = format_ics_time(start_raw, "start")
        end = format_ics_time(end_raw, "end")
        if end_dt <= start_dt:
            raise SpecError("data.end must be after data.start")
        location = optional_string(data, "location")
        description = multiline_string(data, "description")
        uid_seed = f"{title}|{start}|{end}|{location}".encode("utf-8")
        uid = hashlib.sha256(uid_seed).hexdigest()[:20] + "@qr-life-kit"
        fields = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//QR Life Kit//EN",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART:{start}",
            f"DTEND:{end}",
            f"SUMMARY:{escape_ics(title)}",
        ]
        if location:
            fields.append(f"LOCATION:{escape_ics(location)}")
        if description:
            fields.append(f"DESCRIPTION:{escape_ics(description)}")
        fields.extend(["END:VEVENT", "END:VCALENDAR"])
        return Payload(kind, "\r\n".join(fields), f"Event: {title}", True)

    if kind == "text":
        text = multiline_string(data, "text", required=True)
        return Payload(kind, text, text[:120], False)

    raise SpecError(
        "type must be one of: url, wifi, vcard, email, sms, phone, geo, event, text"
    )


def parse_options(spec: dict[str, Any], payload: Payload) -> tuple[dict[str, Any], dict[str, Any]]:
    qr_options = spec.get("qr", {})
    card_options = spec.get("card", {})
    if not isinstance(qr_options, dict) or not isinstance(card_options, dict):
        raise SpecError("qr and card must be objects")

    error = str(qr_options.get("error_correction", "H")).upper()
    if error not in ERROR_LEVELS:
        raise SpecError("qr.error_correction must be L, M, Q, or H")
    box_size = qr_options.get("box_size", 24)
    border = qr_options.get("border", 4)
    if not isinstance(box_size, int) or not 4 <= box_size <= 40:
        raise SpecError("qr.box_size must be an integer from 4 to 40")
    if not isinstance(border, int) or not 4 <= border <= 12:
        raise SpecError("qr.border must be an integer from 4 to 12")
    payload_bytes = len(payload.text.encode("utf-8"))
    if payload_bytes > MAX_BYTE_CAPACITY[error]:
        raise SpecError(
            f"payload is {payload_bytes} bytes; correction level {error} supports at most "
            f"{MAX_BYTE_CAPACITY[error]} bytes"
        )

    theme = str(card_options.get("theme", "paper")).lower()
    card_format = str(card_options.get("format", "portrait")).lower()
    if theme not in THEMES:
        raise SpecError("card.theme must be paper, midnight, or sunset")
    if card_format not in {"portrait", "square"}:
        raise SpecError("card.format must be portrait or square")

    defaults = {
        "url": ("Open link", "Scan with your camera"),
        "wifi": ("Join Wi-Fi", "Scan to connect"),
        "vcard": ("Save contact", "Scan to add this contact"),
        "email": ("Send email", "Scan to start a message"),
        "sms": ("Send message", "Scan to open SMS"),
        "phone": ("Call", "Scan to open the phone app"),
        "geo": ("Open location", "Scan to view the map"),
        "event": ("Save event", "Scan to open calendar details"),
        "text": ("Scan to read", "Point your camera at the code"),
    }
    default_title, default_subtitle = defaults[payload.kind]
    title = str(card_options.get("title", default_title)).strip()
    subtitle = str(card_options.get("subtitle", default_subtitle)).strip()
    footer = str(card_options.get("footer", "Static QR - no redirect or tracking")).strip()
    for key, value in {"title": title, "subtitle": subtitle, "footer": footer}.items():
        if not value or CONTROL_RE.search(value):
            raise SpecError(f"card.{key} must be non-empty and contain no control characters")
        if len(value) > 120:
            raise SpecError(f"card.{key} must be 120 characters or fewer")
    show_payload = card_options.get("show_payload", payload.kind in {"url", "geo"})
    if not isinstance(show_payload, bool):
        raise SpecError("card.show_payload must be a boolean")
    if payload.sensitive:
        show_payload = False

    return (
        {"error": error, "box_size": box_size, "border": border},
        {
            "theme": theme,
            "format": card_format,
            "title": title,
            "subtitle": subtitle,
            "footer": footer,
            "show_payload": show_payload,
        },
    )


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def choose_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = [
        "/System/Library/Fonts/SFNSRounded.ttf" if bold else "/System/Library/Fonts/SFNS.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for name in names:
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def draw_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: float,
    width: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int],
) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (box[2] - box[0])) / 2, y), text, font=font, fill=fill)


def fit_font(text: str, max_width: int, start_size: int, *, bold: bool) -> Any:
    for size in range(start_size, 23, -2):
        font = choose_font(size, bold=bold)
        box = font.getbbox(text)
        if box[2] - box[0] <= max_width:
            return font
    return choose_font(24, bold=bold)


def make_qr(payload: Payload, qr_options: dict[str, Any], stage: Path) -> Image.Image:
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_LEVELS[qr_options["error"]],
        box_size=qr_options["box_size"],
        border=qr_options["border"],
    )
    qr.add_data(payload.text)
    qr.make(fit=True)
    raw = qr.make_image(fill_color="#111111", back_color="#FFFFFF").convert("RGB")
    raw.save(stage / "qr.png", quality=100)
    qr.make_image(image_factory=SvgPathImage).save(stage / "qr.svg")
    return raw


def make_card_png(
    raw: Image.Image, payload: Payload, card_options: dict[str, Any], output: Path
) -> None:
    portrait = card_options["format"] == "portrait"
    width, height = (1400, 1800) if portrait else (1400, 1400)
    colors = THEMES[card_options["theme"]]
    page = Image.new("RGB", (width, height), hex_to_rgb(colors["page"]))
    draw = ImageDraw.Draw(page)

    margin = 84
    draw.rounded_rectangle(
        (margin, margin, width - margin, height - margin),
        radius=54,
        fill=hex_to_rgb(colors["card"]),
        outline=hex_to_rgb(colors["line"]),
        width=3,
    )
    banner_bottom = 340 if portrait else 310
    draw.rounded_rectangle(
        (128, 128, width - 128, banner_bottom),
        radius=36,
        fill=hex_to_rgb(colors["accent"]),
    )
    title_font = fit_font(card_options["title"], width - 330, 78, bold=True)
    subtitle_font = fit_font(card_options["subtitle"], width - 300, 36, bold=True)
    url_font = fit_font(payload.safe_display, width - 300, 43, bold=True)
    footer_font = fit_font(card_options["footer"], width - 300, 28, bold=False)
    action_font = choose_font(34, bold=False)

    draw_centered(
        draw,
        card_options["title"],
        177 if portrait else 160,
        width,
        title_font,
        hex_to_rgb(colors["accent_text"]),
    )
    draw_centered(
        draw,
        card_options["subtitle"],
        banner_bottom + 38,
        width,
        subtitle_font,
        hex_to_rgb(colors["muted"]),
    )

    qr_size = 900 if portrait else 720
    qr_resized = raw.resize((qr_size, qr_size), Image.Resampling.NEAREST)
    qx = (width - qr_size) // 2
    qy = 455 if portrait else 435
    frame = 28
    draw.rounded_rectangle(
        (qx - frame, qy - frame, qx + qr_size + frame, qy + qr_size + frame),
        radius=30,
        fill=(255, 255, 255),
        outline=hex_to_rgb(colors["line"]),
        width=2,
    )
    page.paste(qr_resized, (qx, qy))

    payload_y = qy + qr_size + 68
    if card_options["show_payload"]:
        draw_centered(
            draw,
            payload.safe_display,
            payload_y,
            width,
            url_font,
            hex_to_rgb(colors["ink"]),
        )
        footer_y = payload_y + 82
    else:
        footer_y = payload_y + 10
    draw_centered(
        draw,
        card_options["footer"],
        footer_y,
        width,
        footer_font,
        hex_to_rgb(colors["muted"]),
    )
    if portrait:
        line_y = height - 180
        draw.line((180, line_y, width - 180, line_y), fill=hex_to_rgb(colors["line"]), width=2)
        draw_centered(
            draw,
            "Point your camera at the code",
            line_y + 42,
            width,
            action_font,
            hex_to_rgb(colors["ink"]),
        )
    page.save(output, quality=96)


def make_card_html(
    svg_path: Path, payload: Payload, card_options: dict[str, Any], output: Path
) -> None:
    svg = svg_path.read_text(encoding="utf-8")
    svg = re.sub(r"^<\?xml[^>]*>\s*", "", svg)
    colors = THEMES[card_options["theme"]]
    display = ""
    if card_options["show_payload"]:
        display = f'<p class="payload">{html.escape(payload.safe_display)}</p>'
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(card_options['title'])}</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:36px;background:{colors['page']};font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:{colors['ink']}}}
.card{{width:min(94vw,720px);background:{colors['card']};border:2px solid {colors['line']};border-radius:34px;padding:28px;box-shadow:0 24px 70px #0002;text-align:center}}
.head{{background:{colors['accent']};color:{colors['accent_text']};border-radius:24px;padding:30px 18px}}h1{{font-size:clamp(34px,7vw,60px);line-height:1;margin:0}}.subtitle{{color:{colors['muted']};font-size:20px;font-weight:700;margin:26px 0 18px}}
.qr{{width:min(100%,520px);margin:auto;background:white;padding:18px;border:1px solid {colors['line']};border-radius:22px}}.qr svg{{display:block;width:100%;height:auto}}
.payload{{font-size:24px;font-weight:750;overflow-wrap:anywhere;margin:24px 0 0}}footer{{color:{colors['muted']};font-size:15px;margin:20px 0 4px}}
@media print{{body{{padding:0;background:white}}.card{{width:100%;box-shadow:none;border:none}}}}
</style>
</head>
<body><main class="card"><div class="head"><h1>{html.escape(card_options['title'])}</h1></div><p class="subtitle">{html.escape(card_options['subtitle'])}</p><div class="qr">{svg}</div>{display}<footer>{html.escape(card_options['footer'])}</footer></main></body>
</html>"""
    output.write_text(document, encoding="utf-8")


def decode_image(path: Path) -> list[str]:
    try:
        image = Image.open(path)
    except Exception as exc:
        raise SpecError(f"could not open image: {exc}") from exc
    results = [result.text for result in zxingcpp.read_barcodes(image)]
    if results:
        return results
    # Some decoder builds miss perfectly valid codes at particular integer
    # module scales. Retry nearest-neighbor scale variants without altering the
    # source artifact; this also mirrors cameras observing the code at distance.
    for scale in (0.5, 2 / 3, 1.5):
        resized = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.NEAREST,
        )
        results = [result.text for result in zxingcpp.read_barcodes(resized)]
        if results:
            return results
    return []


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def redact_spec(spec: dict[str, Any], payload: Payload) -> dict[str, Any]:
    redacted = json.loads(json.dumps(spec))
    data = redacted.get("data", {})
    sensitive_fields = {
        "wifi": {"ssid", "password"},
        "vcard": {"name", "phone", "email", "organization", "title", "url"},
        "contact": {"name", "phone", "email", "organization", "title", "url"},
        "email": {"to", "subject", "body"},
        "sms": {"phone", "message"},
        "phone": {"phone"},
        "event": {"title", "location", "description"},
    }.get(payload.kind, set())
    for field in sensitive_fields:
        if field in data and data[field]:
            data[field] = "[redacted]"
    return redacted


def build(spec_path: Path, output: Path, include_payload: bool) -> dict[str, Any]:
    if output.exists():
        raise SpecError("output directory already exists; choose a new path")
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SpecError(f"spec file not found: {spec_path}") from exc
    except json.JSONDecodeError as exc:
        raise SpecError(f"spec is not valid JSON: {exc}") from exc
    if not isinstance(spec, dict):
        raise SpecError("spec root must be an object")

    payload = build_payload(spec)
    qr_options, card_options = parse_options(spec, payload)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".qr-life-kit-", dir=output.parent) as temp_dir:
        stage = Path(temp_dir)
        raw = make_qr(payload, qr_options, stage)
        make_card_png(raw, payload, card_options, stage / "card.png")
        make_card_html(stage / "qr.svg", payload, card_options, stage / "card.html")

        raw_values = decode_image(stage / "qr.png")
        card_values = decode_image(stage / "card.png")
        raw_passed = payload.text in raw_values
        card_passed = payload.text in card_values
        verification = {
            "status": "passed" if raw_passed and card_passed else "failed",
            "payload_type": payload.kind,
            "payload_sha256": hashlib.sha256(payload.text.encode("utf-8")).hexdigest(),
            "payload_bytes": len(payload.text.encode("utf-8")),
            "sensitive": payload.sensitive,
            "raw_qr": {"passed": raw_passed, "decoded_count": len(raw_values)},
            "card_png": {"passed": card_passed, "decoded_count": len(card_values)},
            "network_checked": False,
        }
        (stage / "verification.json").write_text(
            json.dumps(verification, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (stage / "spec-redacted.json").write_text(
            json.dumps(redact_spec(spec, payload), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        if include_payload:
            (stage / "payload.txt").write_text(payload.text, encoding="utf-8")

        if verification["status"] != "passed":
            raise SpecError("round-trip QR verification failed; build was not published")

        artifact_names = [
            "qr.png",
            "qr.svg",
            "card.png",
            "card.html",
            "verification.json",
            "spec-redacted.json",
        ]
        if include_payload:
            artifact_names.append("payload.txt")
        manifest = {
            "format_version": 1,
            "payload_type": payload.kind,
            "payload_sha256": verification["payload_sha256"],
            "sensitive": payload.sensitive,
            "theme": card_options["theme"],
            "card_format": card_options["format"],
            "verification_status": verification["status"],
            "files": {
                name: {"sha256": sha256_file(stage / name), "bytes": (stage / name).stat().st_size}
                for name in artifact_names
            },
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(stage, output)
    return manifest


def inspect_image(path: Path) -> list[dict[str, Any]]:
    values = decode_image(path)
    return [
        {
            "index": index,
            "data": value,
            "bytes": len(value.encode("utf-8")),
            "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        }
        for index, value in enumerate(values, start=1)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and verify static QR life cards")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Build a verified QR deliverable pack")
    build_parser.add_argument("--spec", required=True, type=Path, help="JSON build specification")
    build_parser.add_argument("--output", required=True, type=Path, help="New output directory")
    build_parser.add_argument(
        "--include-payload",
        action="store_true",
        help="Write plaintext payload.txt (may expose sensitive data)",
    )

    inspect_parser = subparsers.add_parser("inspect", help="Decode QR values from an image")
    inspect_parser.add_argument("--image", required=True, type=Path)

    args = parser.parse_args()
    try:
        if args.command == "build":
            manifest = build(args.spec.resolve(), args.output.resolve(), args.include_payload)
            print(json.dumps({"output": str(args.output.resolve()), **manifest}, ensure_ascii=False))
            return 0
        results = inspect_image(args.image.resolve())
        print(json.dumps({"image": str(args.image.resolve()), "results": results}, indent=2, ensure_ascii=False))
        return 0 if results else 1
    except SpecError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
