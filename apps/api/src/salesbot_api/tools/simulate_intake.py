"""Simulate a registration-form submission (dev only).

Signs a request exactly like the real form must (docs/INTAKE_CONTRACT.md) and posts it to a
running API. Submissions are tagged source=simulation and excluded from metrics.

    uv run --package salesbot-api python -m salesbot_api.tools.simulate_intake \\
        --clinic-id <uuid> --name "Test Patient" --phone +9198XXXXXXXX --lang mr

Use test patients only (people who agreed to receive test messages). Never real patient data.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime

from salesbot_api.intake import (
    SIGNATURE_HEADER,
    SIMULATION_HEADER,
    TIMESTAMP_HEADER,
    IntakeRecord,
    sign,
)
from salesbot_api.settings import Settings


def build_payload(args: argparse.Namespace) -> dict:
    opted_in = args.whatsapp or args.call
    data = {
        "clinic_id": args.clinic_id,
        "external_patient_id": args.external_id or f"sim-{uuid.uuid4().hex[:10]}",
        "name": args.name,
        "phone": args.phone,
        "preferred_language": args.lang,
        "dob": args.dob,
        "age": args.age,
        "caregiver_name": args.caregiver_name,
        "caregiver_phone": args.caregiver_phone,
        "whatsapp_opt_in": args.whatsapp,
        "call_opt_in": args.call,
        "consent_at": datetime.now(UTC).isoformat() if opted_in else None,
        "consent_source": "dev_simulator" if opted_in else None,
    }
    payload = {k: v for k, v in data.items() if v is not None}
    IntakeRecord.model_validate(payload)  # fail here, not at the server, on bad input
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--clinic-id", required=True)
    parser.add_argument("--external-id", help="default: a new random id (a new patient)")
    parser.add_argument("--name", required=True)
    parser.add_argument("--phone", required=True, help="E.164, e.g. +9198XXXXXXXX")
    parser.add_argument("--lang", choices=["en", "hi", "mr"], default="en")
    parser.add_argument("--dob", help="YYYY-MM-DD")
    parser.add_argument("--age", type=int)
    parser.add_argument("--caregiver-name")
    parser.add_argument("--caregiver-phone")
    parser.add_argument("--no-whatsapp", dest="whatsapp", action="store_false")
    parser.add_argument("--call", action="store_true", help="also opt in to calls")
    parser.add_argument("--dry-run", action="store_true", help="print the signed request only")
    args = parser.parse_args(argv)

    settings = Settings()
    if settings.app_env == "production":
        print("refusing to run with APP_ENV=production", file=sys.stderr)
        return 2
    if settings.intake_hmac_secret is None:
        print("INTAKE_HMAC_SECRET is not set in .env", file=sys.stderr)
        return 2

    body = json.dumps(build_payload(args)).encode()
    ts = int(time.time())
    headers = {
        "Content-Type": "application/json",
        TIMESTAMP_HEADER: str(ts),
        SIGNATURE_HEADER: sign(settings.intake_hmac_secret.get_secret_value(), ts, body),
        SIMULATION_HEADER: "1",
    }
    url = f"{args.url.rstrip('/')}/api/v1/intake/patients"
    if args.dry_run:
        print(f"POST {url}")
        for k, v in headers.items():
            print(f"{k}: {v}")
        print(body.decode())
        return 0

    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:  # noqa: S310 (dev URL)
            print(resp.status, resp.read().decode())
            return 0
    except urllib.error.HTTPError as exc:
        print(exc.code, exc.read().decode(), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
