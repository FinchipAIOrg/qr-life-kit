# Build spec

Use a UTF-8 JSON object with `type`, `data`, and optional `card` and `qr` objects.

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
  },
  "qr": {"error_correction": "H", "box_size": 24, "border": 4}
}
```

## Types and fields

| Type | Required fields | Optional fields |
|---|---|---|
| `url` | `url` | none |
| `wifi` | `ssid` | `password`, `security` (`WPA`, `WEP`, `nopass`), `hidden` |
| `vcard` | `name` | `phone`, `email`, `organization`, `title`, `url` |
| `email` | `to` | `subject`, `body` |
| `sms` | `phone` | `message` |
| `phone` | `phone` | none |
| `geo` | `latitude`, `longitude` | `label` |
| `event` | `title`, `start`, `end` | `location`, `description` |
| `text` | `text` | none |

Use ISO 8601 values for event times. Offset-aware times are converted to UTC; naive times remain floating local times.

## Card options

- `theme`: `paper`, `midnight`, or `sunset`.
- `format`: `portrait` or `square`.
- `title`, `subtitle`, `footer`: optional display copy.
- `show_payload`: show a safe display value below the QR. It is forced off for Wi-Fi and contact payloads.

## QR options

- `error_correction`: `L`, `M`, `Q`, or `H`; default `H`.
- `box_size`: integer from 4 through 40; default `24`.
- `border`: minimum `4`; default `4`.

The command rejects payloads larger than the byte capacity of the selected correction level.
