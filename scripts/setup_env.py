"""Creates a local .env from .env.example with freshly generated secrets."""

import base64
import os
import secrets
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
target = root / ".env"
if target.exists() and "--force" not in sys.argv:
    sys.exit(".env already exists (use --force to overwrite)")

admin_email = os.environ.get("ADMIN_EMAIL", "")
values = {
    "SECRET_KEY": secrets.token_urlsafe(48),
    "ENCRYPTION_KEYS": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    "PLATFORM_ADMIN_EMAILS": f'["{admin_email}"]' if admin_email else "[]",
}
lines = []
for line in (root / ".env.example").read_text().splitlines():
    key = line.split("=", 1)[0]
    lines.append(f"{key}={values[key]}" if key in values and not line.startswith("#") else line)
target.write_text("\n".join(lines) + "\n")
print(f"Wrote {target}")
