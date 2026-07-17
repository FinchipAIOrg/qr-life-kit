# Safety and compatibility

## Static behavior

QR Life Kit encodes the final payload directly. A URL code contains the URL itself; it does not depend on a short-link provider. The phone can decode it offline, but opening a public URL still requires network access.

## Sensitive payloads

- Wi-Fi codes disclose the SSID and password to anyone who can scan them.
- vCards, email drafts, SMS drafts, and events can contain personal data.
- Generated QR images are not encrypted. Redaction in reports does not change what is encoded in the QR.

Keep sensitive cards within the intended audience. Do not upload them to a public asset host without explicit user intent.

## Scan reliability

- Preserve at least a four-module white quiet zone.
- Keep the QR modules dark and the background white.
- Avoid gradients, transparency, logos, rounded modules, or decorative overlays inside the QR.
- Use SVG for print. Do not resample with smoothing; use nearest-neighbor scaling.
- Verify the final composed card, not only the raw QR.

## Payload compatibility

- URL: only HTTP(S), with no embedded username/password.
- Wi-Fi: use the common `WIFI:T:...;S:...;P:...;H:...;;` syntax and escape reserved characters.
- Contact: use vCard 3.0 for broad compatibility.
- Calendar: use an iCalendar VEVENT payload. Scanner behavior varies; state this limitation if the target device is unknown.
- SMS: use `SMSTO:number:message`, which is broadly recognized but may vary by scanner.

## No automatic navigation

Inspection and verification decode payloads but never open URLs, join Wi-Fi, create contacts, send messages, or add events.
