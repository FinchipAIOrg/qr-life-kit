# QR Life Kit

Turn everyday information into verified, polished QR deliverables—without an API key, hosted redirect, or tracking service.

QR Life Kit is an Agent Skill and local CLI for creating static QR codes plus shareable or printable cards. Every build round-trips both the raw QR image and the final composed card before it is considered ready to deliver.

## What makes it different

- **Useful payloads, not just URLs:** URL, Wi-Fi, vCard, email, SMS, phone, location, calendar event, and plain text.
- **Delivery-ready output:** PNG and SVG QR files, a styled card in PNG and standalone HTML, a manifest, and verification evidence.
- **Final-artwork verification:** the code is decoded from `card.png`, not only from the raw QR image.
- **Privacy-conscious defaults:** no remote QR API, no redirects, no analytics, and sensitive fields are removed from reproducibility metadata.
- **Safe static URLs:** only HTTP(S) links are accepted; credential-bearing URLs and unsafe schemes are rejected.

## Supported payloads

| Type | Typical use | Required data |
|---|---|---|
| `url` | Open a web page | `url` |
| `wifi` | Join a wireless network | `ssid` |
| `vcard` | Save a contact | `name` |
| `email` | Draft an email | `to` |
| `sms` | Draft a text message | `phone` |
| `phone` | Start a phone call | `phone` |
| `geo` | Open a map coordinate | `latitude`, `longitude` |
| `event` | Add a calendar event | `title`, `start`, `end` |
| `text` | Reveal plain text | `text` |

See [references/spec-schema.md](references/spec-schema.md) for every field and card option.

## Requirements

- Python 3.10+
- Packages listed in `requirements.txt`

No API key or hosted service is required.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## Quick start

Create a UTF-8 JSON spec:

```json
{
  "type": "url",
  "data": {"url": "https://finchip.ai/"},
  "card": {
    "title": "Open finchip.ai",
    "subtitle": "Scan with your camera",
    "footer": "Static QR - no redirect or tracking",
    "theme": "paper",
    "format": "portrait",
    "show_payload": true
  }
}
```

Build into a new output directory:

```bash
.venv/bin/python scripts/qr_life_kit.py build \
  --spec /absolute/path/to/spec.json \
  --output /absolute/path/to/output
```

The build succeeds only when exact payload matching passes for both the raw QR and the final card.

## Output bundle

| File | Purpose |
|---|---|
| `qr.png` | High-contrast raster QR for screens |
| `qr.svg` | Lossless vector QR for print |
| `card.png` | Styled share/print card |
| `card.html` | Responsive standalone printable card |
| `verification.json` | Raw-QR and final-card decoding evidence |
| `manifest.json` | File hashes and build metadata |
| `spec-redacted.json` | Reproducibility data with secrets removed |

Plaintext payload output is disabled by default. Add `--include-payload` only when the recipient understands that Wi-Fi, contact, message, and event data may be sensitive.

## Inspect an existing QR

Decode without opening links or making network requests:

```bash
.venv/bin/python scripts/qr_life_kit.py inspect \
  --image /absolute/path/to/qr-or-card.png
```

## Agent Skill usage

Copy or install this repository as a Codex-compatible skill, then ask the agent for a concrete deliverable, for example:

> Create a printable paper-theme QR card for https://finchip.ai/. Use the title “Open finchip.ai”, verify the final card, and give me PNG and SVG versions.

The skill entry point is [SKILL.md](SKILL.md). It instructs the agent to collect the right fields, build into a fresh directory, check `verification.json`, and deliver only verified assets.

## Safety and compatibility

- A static QR stores its payload directly in the image. The image can be scanned offline, but opening an encoded website still requires network access.
- Anyone who can see a Wi-Fi QR can recover its credentials.
- QR payloads are not encrypted. Handle contact, email, SMS, Wi-Fi, and event cards as sensitive data.
- Calendar, contact, SMS, and Wi-Fi behavior can vary by scanner and operating system.
- Keep the QR dark on white with a four-module quiet zone. Branding belongs around the code, not over it.
- Existing output directories are never overwritten.

Read [references/safety-and-compatibility.md](references/safety-and-compatibility.md) before modifying payload formats or QR rendering rules.

## Validation

Run the test suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The suite covers all nine payload families, exact decoding from raw and composed artwork, URL safety checks, redaction, and overwrite protection.

## License and attribution

Released under [MIT-0](LICENSE). See [NOTICE](NOTICE) for upstream inspiration and attribution details.
