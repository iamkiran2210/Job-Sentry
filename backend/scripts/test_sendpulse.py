#!/usr/bin/env python3
"""Small CLI script to verify SendPulse auth (GET /user/info) and send a test email (POST /smtp/emails).

Usage:
    # 1. Verify API key only
    python scripts/test_sendpulse.py --verify-only

    # 2. Verify auth and send a test email
    python scripts/test_sendpulse.py --to you@example.com --subject "Job Sentry Test" --text "Hello from SendPulse"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ensure `app` is importable when invoked as `python scripts/test_sendpulse.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.candidate_intelligence.notifications import (  # noqa: E402
    SendPulseError,
    sendEmail,
    verifyAuth,
)


async def _run(args: argparse.Namespace) -> int:
    try:
        user_info = await verifyAuth()
        print("Auth verified (GET /user/info):")
        print(json.dumps(user_info, indent=2))
    except SendPulseError as exc:
        print(f"Auth verification failed: {exc}", file=sys.stderr)
        return 1

    if args.verify_only:
        return 0

    if not args.to:
        print("Error: --to <email> is required unless --verify-only is passed.", file=sys.stderr)
        return 2

    html_body = args.html or f"<p>{args.text}</p>"
    try:
        result = await sendEmail(
            to_email=args.to,
            to_name=args.to_name,
            subject=args.subject,
            html=html_body,
            text=args.text,
        )
        print("\nEmail sent (POST /smtp/emails):")
        print(json.dumps(result, indent=2))
        return 0
    except SendPulseError as exc:
        print(f"Email send failed: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify SendPulse API auth and send a test email.")
    parser.add_argument("--verify-only", action="store_true", help="Only call GET /user/info")
    parser.add_argument("--to", help="Recipient email address")
    parser.add_argument("--to-name", default=None, help="Optional recipient display name")
    parser.add_argument("--subject", default="Job Sentry SendPulse Test", help="Email subject")
    parser.add_argument("--text", default="Hello from Job Sentry via SendPulse!", help="Plain-text body")
    parser.add_argument("--html", default=None, help="Optional HTML body (defaults to <p>text</p>)")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
