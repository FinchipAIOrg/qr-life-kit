---
name: qr-life-kit
description: Create and verify static QR codes plus polished printable/shareable cards for URLs, Wi-Fi credentials, contacts, email, SMS, phone numbers, locations, calendar events, and plain text. Use when Codex needs to turn everyday information into PNG/SVG QR assets, produce an offline single-file card, validate that the final composed artwork still scans, or inspect an existing QR image without using a hosted QR service or API key.
---

# QR Life Kit

Create static QR deliverables that remain independent of redirect services. Treat successful round-trip decoding of the final card as a required gate, not an optional check.

## Workflow

1. Identify the payload type and collect only its required fields.
2. Create a JSON spec using [references/spec-schema.md](references/spec-schema.md).
3. Build into a new output directory:

```bash
python3 scripts/qr_life_kit.py build \
  --spec /absolute/path/to/spec.json \
  --output /absolute/path/to/output
```

4. Read `verification.json`. Deliver only when `status` is `passed` and both `raw_qr` and `card_png` passed exact payload matching.
5. Show the user `card.png` and provide `qr.svg` for lossless printing.

Install the two lightweight dependencies when missing:

```bash
python3 -m pip install -r requirements.txt
```

## Output contract

The build command creates:

- `qr.png` — high-contrast raster QR.
- `qr.svg` — lossless vector QR for print.
- `card.png` — composed share/print card.
- `card.html` — responsive, self-contained printable card.
- `verification.json` — round-trip decoding evidence.
- `manifest.json` — hashes and build metadata.
- `spec-redacted.json` — reproducibility metadata with secrets removed.

Do not add plaintext `payload.txt` unless the user explicitly requests it and understands that Wi-Fi/contact data may be sensitive. Use `--include-payload` only in that case.

## Safety rules

- Generate static codes by default. Do not silently introduce redirectors, analytics, tracking pixels, or hosted QR APIs.
- Permit only `http` and `https` for URL payloads. Reject credentials embedded in URLs and unsafe schemes such as `javascript:`, `file:`, and `data:`.
- Keep the QR itself dark on white with the standard four-module quiet zone. Express branding in the surrounding card.
- Never place a logo over the QR in this version.
- Do not claim that URL content works offline. Scanning can reveal the URL offline; opening it requires network access.
- Warn that anyone who sees a Wi-Fi QR can recover its password.
- Treat contact, Wi-Fi, email, SMS, and event payloads as potentially sensitive even when the build report is redacted.
- Never overwrite an existing output directory. Choose a new directory for each build.

Read [references/safety-and-compatibility.md](references/safety-and-compatibility.md) before changing payload formats, QR contrast, quiet-zone rules, or disclosure behavior.

## Inspect an existing QR

```bash
python3 scripts/qr_life_kit.py inspect --image /absolute/path/to/image.png
```

The command reports decoded values without opening URLs or performing network requests.

## Design guidance

- Default to `paper` for general sharing, `midnight` for events/technology, and `sunset` for hospitality or personal cards.
- Use a short action title such as `Open finchip.ai`, `Join Wi-Fi`, or `Save contact`.
- Keep the subtitle factual. Do not promise access that the payload cannot provide.
- Prefer SVG for print and PNG for chat/social sharing.
