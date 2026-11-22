"""Production-ready SendPulse REST API integration for candidate email notifications.

Authenticates directly with `Authorization: Bearer <SENDPULSE_API_KEY>` (no OAuth):
  - `verify_auth()` / `verifyAuth()` -> `GET /user/info`
  - `send_email()` / `sendEmail()`   -> `POST /smtp/emails`

Reads configuration strictly from environment variables (or `.env` via pydantic-settings):
  - `SENDPULSE_API_KEY` (required to send; falls back to Audit Outbox when unset)
  - `SENDPULSE_API_FROM_EMAIL` (required; defaults to `devtest@sendpulseemail.com` for SMTP Test plan)
  - `SENDPULSE_API_FROM_NAME` (optional; defaults to `Job Sentry`)
  - `SENDPULSE_API_BASE_URL` (optional; defaults to `https://api.sendpulse.com`)
"""

from __future__ import annotations

import html as html_lib
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("job_sentry.notifications")

DEFAULT_SENDPULSE_BASE_URL = "https://api.sendpulse.com"
DEFAULT_TEST_FROM_EMAIL = "devtest@sendpulseemail.com"


class SendPulseError(RuntimeError):
    """Structured error raised for non-2xx SendPulse REST API responses."""

    def __init__(
            self,
            message: str,
            *,
            status_code: int | None = None,
            retryable: bool = False,
            raw_body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.raw_body = raw_body


class SendPulseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SENDPULSE_API_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    key: SecretStr | None = Field(default=None)
    from_email: str = Field(default=DEFAULT_TEST_FROM_EMAIL)
    from_name: str = Field(default="Job Sentry")
    base_url: str = Field(default=DEFAULT_SENDPULSE_BASE_URL)
    timeout_seconds: float = Field(default=12.0)


def _clean(val: str | None) -> str:
    return (val or "").strip().strip('"').strip("'").strip()


def load_sendpulse_config() -> dict[str, Any] | None:
    """Read SendPulse settings from env / `.env`. Returns None if SENDPULSE_API_KEY is unset."""
    cfg = SendPulseSettings()
    raw_key = cfg.key.get_secret_value() if cfg.key is not None else ""
    api_key = _clean(raw_key)
    if not api_key:
        return None
    from_email = _clean(cfg.from_email) or DEFAULT_TEST_FROM_EMAIL
    from_name = _clean(cfg.from_name)
    base_url = (_clean(cfg.base_url) or DEFAULT_SENDPULSE_BASE_URL).rstrip("/")
    return {
        "api_key": api_key,
        "from_email": from_email,
        "from_name": from_name,
        "base_url": base_url,
        "timeout": max(3.0, float(cfg.timeout_seconds)),
    }


def _extract_error_message(resp: httpx.Response) -> tuple[str, Any]:
    body: Any = None
    try:
        body = resp.json() if resp.content else None
    except ValueError:
        body = (resp.text or "").strip()[:240]

    if isinstance(body, dict):
        msg = (
                body.get("message")
                or body.get("error_description")
                or body.get("error")
                or str(body)[:200]
        )
        return str(msg).strip()[:220], body
    if isinstance(body, str) and body:
        return body[:220], body
    return f"HTTP {resp.status_code}", body


def _raise_for_sendpulse_error(resp: httpx.Response, *, context: str) -> None:
    detail, body = _extract_error_message(resp)
    code = resp.status_code
    if code in {401, 403}:
        raise SendPulseError(
            f"SendPulse authentication failed ({context}, HTTP {code}): {detail}. Check SENDPULSE_API_KEY.",
            status_code=code,
            retryable=False,
            raw_body=body,
        )
    if code == 422:
        raise SendPulseError(
            f"SendPulse rejected request ({context}, HTTP 422): {detail}. "
            "Ensure SENDPULSE_API_FROM_EMAIL is a verified sender (or devtest@sendpulseemail.com on the SMTP Test plan).",
            status_code=code,
            retryable=False,
            raw_body=body,
        )
    if code == 429:
        raise SendPulseError(
            f"SendPulse rate limit or plan quota reached ({context}, HTTP 429): {detail}. Please retry later.",
            status_code=code,
            retryable=True,
            raw_body=body,
        )
    raise SendPulseError(
        f"SendPulse API error ({context}, HTTP {code}): {detail}",
        status_code=code,
        retryable=code >= 500,
        raw_body=body,
    )


async def verify_auth(
        *,
        config: dict[str, Any] | None = None,
        client: httpx.AsyncClient | None = None,
        transport=None,
) -> dict[str, Any]:
    """Verify SendPulse API key via `GET /user/info`."""
    cfg = config if config is not None else load_sendpulse_config()
    if cfg is None:
        raise SendPulseError(
            "SENDPULSE_API_KEY is not configured in environment.",
            status_code=None,
            retryable=False,
        )

    owned = client is None
    session = client or httpx.AsyncClient(
        timeout=cfg["timeout"],
        transport=transport,
        trust_env=False,
    )
    try:
        resp = await session.get(
            f"{cfg['base_url']}/user/info",
            headers={
                "Authorization": f"Bearer {cfg['api_key']}",
                "Accept": "application/json",
            },
        )
        if not (200 <= resp.status_code < 300):
            _raise_for_sendpulse_error(resp, context="GET /user/info")
        return resp.json() if resp.content else {"ok": True}
    except SendPulseError:
        raise
    except (httpx.TimeoutException, httpx.HTTPError, OSError) as exc:
        raise SendPulseError(
            f"SendPulse network error during GET /user/info ({type(exc).__name__}): {str(exc)[:160]}",
            retryable=True,
        ) from exc
    finally:
        if owned:
            await session.aclose()


async def send_email(
        *,
        to_email: str,
        subject: str,
        html: str,
        text: str,
        to_name: str | None = None,
        from_email: str | None = None,
        from_name: str | None = None,
        config: dict[str, Any] | None = None,
        client: httpx.AsyncClient | None = None,
        transport=None,
) -> dict[str, Any]:
    """Send a transactional email via `POST /smtp/emails` using Bearer API key auth."""
    cfg = config if config is not None else load_sendpulse_config()
    if cfg is None:
        raise SendPulseError(
            "SENDPULSE_API_KEY is not configured in environment.",
            status_code=None,
            retryable=False,
        )

    resolved_from_email = _clean(from_email) or cfg["from_email"]
    if not resolved_from_email or "@" not in resolved_from_email:
        raise SendPulseError(
            "SENDPULSE_API_FROM_EMAIL is required and must be a valid verified email address.",
            status_code=422,
            retryable=False,
        )
    if not to_email or "@" not in to_email:
        raise SendPulseError(
            "Recipient email address is invalid.",
            status_code=422,
            retryable=False,
        )

    resolved_from_name = _clean(from_name) or cfg.get("from_name") or ""
    from_obj: dict[str, str] = {"email": resolved_from_email}
    if resolved_from_name:
        from_obj["name"] = resolved_from_name

    to_entry: dict[str, str] = {"email": to_email.strip()}
    if to_name and to_name.strip():
        to_entry["name"] = to_name.strip()[:120]

    payload = {
        "email": {
            "subject": subject,
            "html": html,
            "text": text,
            "from": from_obj,
            "to": [to_entry],
        }
    }

    owned = client is None
    session = client or httpx.AsyncClient(
        timeout=cfg["timeout"],
        transport=transport,
        trust_env=False,
    )
    try:
        resp = await session.post(
            f"{cfg['base_url']}/smtp/emails",
            headers={
                "Authorization": f"Bearer {cfg['api_key']}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
        )
        if not (200 <= resp.status_code < 300):
            _raise_for_sendpulse_error(resp, context="POST /smtp/emails")
        data = resp.json() if resp.content else {"result": True}
        if isinstance(data, dict) and data.get("result") is False:
            msg = str(data.get("message") or data.get("error") or "SendPulse rejected email")[:200]
            raise SendPulseError(
                f"SendPulse delivery rejected: {msg}",
                status_code=resp.status_code,
                retryable=False,
                raw_body=data,
            )
        return data
    except SendPulseError:
        raise
    except (httpx.TimeoutException, httpx.HTTPError, OSError) as exc:
        raise SendPulseError(
            f"SendPulse network error during POST /smtp/emails ({type(exc).__name__}): {str(exc)[:160]}",
            retryable=True,
        ) from exc
    finally:
        if owned:
            await session.aclose()


# CamelCase aliases matching the requested API names
verifyAuth = verify_auth
sendEmail = send_email


def build_candidate_email(
        *,
        candidate_name: str | None,
        job_title: str,
        outcome: str,
        score: float | None = None,
        feedback: str | None = None,
        include_score: bool = True,
) -> tuple[str, str, str]:
    greeting = f"Hi {candidate_name}," if candidate_name else "Hello,"
    normalized = outcome.strip().lower()
    is_positive = normalized in {"shortlisted", "accepted", "accept", "advance", "strong_advance"}
    if is_positive:
        subject = f"Update on your application for {job_title} — Moving Forward"
        intro = (
            f"Thank you for applying for the {job_title} role. "
            "We are pleased to share that your application has been shortlisted for the next stage."
        )
    else:
        subject = f"Update on your application for {job_title}"
        intro = (
            f"Thank you for your interest in the {job_title} role and for taking the time to apply. "
            "After reviewing your application against our role criteria, we will not be moving forward at this time."
        )

    lines = [greeting, "", intro]
    if include_score and score is not None:
        lines.extend(["", f"Role Match Score: {round(float(score))}%"])
    if feedback and feedback.strip():
        lines.extend(["", f"Feedback Summary: {feedback.strip()}"])
    lines.extend(["", "Best regards,", "Recruitment Team · Job Sentry"])
    plain_body = "\n".join(lines)

    score_html = (
        f"<p><strong>Role Match Score:</strong> {round(float(score))}%</p>"
        if include_score and score is not None
        else ""
    )
    feedback_html = (
        f"<p><strong>Feedback Summary:</strong> {html_lib.escape(feedback.strip())}</p>"
        if feedback and feedback.strip()
        else ""
    )
    badge_color = "#047857" if is_positive else "#475569"
    badge_text = "Shortlisted" if is_positive else "Application Update"
    html_body = (
        '<div style="font-family:system-ui,-apple-system,sans-serif;max-width:560px;color:#0f172a;line-height:1.5;">'
        f'<p style="display:inline-block;padding:4px 10px;border-radius:999px;background:{badge_color};color:#fff;font-size:12px;font-weight:600;">{badge_text}</p>'
        f"<p>{html_lib.escape(greeting)}</p>"
        f"<p>{html_lib.escape(intro)}</p>"
        f"{score_html}{feedback_html}"
        '<p style="margin-top:20px;color:#475569;">Best regards,<br/><strong>Recruitment Team · Job Sentry</strong></p>'
        "</div>"
    )
    return subject, plain_body, html_body


async def send_candidate_notification(
        *,
        recipient_email: str | None,
        candidate_name: str | None,
        job_title: str,
        outcome: str,
        score: float | None = None,
        feedback: str | None = None,
        include_score: bool = True,
        client: httpx.AsyncClient | None = None,
        transport=None,
) -> dict[str, Any]:
    """Send candidate status/feedback email via SendPulse, or log to Audit Outbox when unconfigured."""
    subject, plain_body, html_body = build_candidate_email(
        candidate_name=candidate_name,
        job_title=job_title,
        outcome=outcome,
        score=score,
        feedback=feedback,
        include_score=include_score,
    )
    timestamp = datetime.now(timezone.utc).isoformat()
    if not recipient_email or "@" not in recipient_email:
        return {
            "delivered": False,
            "channel": "skipped",
            "reason": "Candidate email address is not available",
            "subject": subject,
            "preview": plain_body,
            "sent_at": timestamp,
        }

    cfg = load_sendpulse_config()
    if cfg is None:
        logger.info(
            "Candidate notification logged to audit outbox (SENDPULSE_API_KEY not configured)",
            extra={"outcome": outcome, "job_title": job_title},
        )
        return {
            "delivered": False,
            "channel": "audit_outbox",
            "reason": (
                "SENDPULSE_API_KEY is not configured; notification prepared and recorded in Audit Outbox. "
                "Set SENDPULSE_API_KEY and SENDPULSE_API_FROM_EMAIL in backend/.env to enable live delivery."
            ),
            "recipient": recipient_email,
            "subject": subject,
            "preview": plain_body,
            "sent_at": timestamp,
        }

    try:
        res = await send_email(
            to_email=recipient_email,
            to_name=candidate_name,
            subject=subject,
            html=html_body,
            text=plain_body,
            config=cfg,
            client=client,
            transport=transport,
        )
        msg_id = res.get("id") if isinstance(res, dict) else None
        suffix = f" (id: {msg_id})" if msg_id else ""
        return {
            "delivered": True,
            "channel": "sendpulse",
            "reason": f"Email sent via SendPulse{suffix}",
            "recipient": recipient_email,
            "subject": subject,
            "preview": plain_body,
            "sent_at": timestamp,
        }
    except SendPulseError as exc:
        logger.warning(
            "SendPulse email delivery failed",
            extra={"status_code": exc.status_code, "retryable": exc.retryable},
        )
        return {
            "delivered": False,
            "channel": "sendpulse_failed",
            "reason": str(exc),
            "recipient": recipient_email,
            "subject": subject,
            "preview": plain_body,
            "sent_at": timestamp,
        }
