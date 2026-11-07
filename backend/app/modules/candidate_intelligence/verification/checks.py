from __future__ import annotations

import ipaddress
import asyncio
import re
import socket
from datetime import date
from urllib.parse import urljoin, urlparse

from app.modules.candidate_intelligence.types import VerificationResultData

EMAIL_RE = re.compile(r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$", re.I)
PHONE_RE = re.compile(r"^\+?[0-9][0-9 .()\-]{6,24}[0-9]$")


def email_check(value: str | None) -> VerificationResultData:
    if not value:
        return VerificationResultData("email_syntax", "not_verified", "Email absent", {"reason_code": "missing_value"})
    normalized = value.strip()
    valid = bool(EMAIL_RE.fullmatch(normalized))
    try:
        from email_validator import validate_email
        validate_email(normalized, check_deliverability=False)
    except ImportError:
        pass
    except Exception:
        valid = False
    if not valid:
        return VerificationResultData("email_syntax", "failed", "Email syntax is malformed", {"reason_code": "invalid_syntax"})
    local, domain = normalized.rsplit("@", 1)
    role_accounts = {"admin", "careers", "contact", "info", "jobs", "office", "recruiting", "support", "team", "webmaster"}
    disposable_domains = {"10minutemail.com", "guerrillamail.com", "mailinator.com", "tempmail.com", "yopmail.com"}
    signals = []
    if local.casefold() in role_accounts:
        signals.append("role_account")
    if domain.casefold() in disposable_domains:
        signals.append("disposable_domain")
    status = "needs_review" if signals else "passed"
    return VerificationResultData("email_syntax", status, "Syntax only; does not prove control of address",
                                  {"reason_code": signals[0] if signals else "syntax_valid", "signals": signals})


def phone_check(value: str | None, region: str | None = None) -> VerificationResultData:
    if not value:
        return VerificationResultData("phone_format", "not_verified", "Phone absent", {"reason_code": "missing_value"})
    normalized = value.strip()
    try:
        import phonenumbers
        if not normalized.startswith("+") and not region:
            return VerificationResultData("phone_format", "not_verified", "National phone number cannot be validated without a configured region", {"reason_code": "region_not_configured"})
        parsed = phonenumbers.parse(normalized, region)
        if not phonenumbers.is_possible_number(parsed):
            return VerificationResultData("phone_format", "failed", "Phone number is not valid for its numbering plan", {"reason_code": "invalid_number"})
        if not phonenumbers.is_valid_number(parsed):
            return VerificationResultData(
                "phone_format", "needs_review",
                "Phone number has a possible format but is not currently valid for its numbering plan",
                {"reason_code": "possible_not_valid"},
            )
        e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        return VerificationResultData("phone_format", "passed", "Format only; does not prove control of number", {"normalized_e164": e164})
    except ImportError:
        pass
    except Exception:
        return VerificationResultData("phone_format", "failed", "Phone number is malformed", {"reason_code": "invalid_number"})
    digits = re.sub(r"\D", "", normalized)
    if not PHONE_RE.fullmatch(normalized) or not 7 <= len(digits) <= 15:
        return VerificationResultData("phone_format", "needs_review", "Phone format could not be validated without numbering-plan metadata", {"reason_code": "validation_unavailable"})
    if not normalized.startswith("+"):
        return VerificationResultData("phone_format", "needs_review", "National phone number requires a configured region", {"reason_code": "region_required"})
    return VerificationResultData("phone_format", "needs_review", "Phone format is plausible; install phonenumbers for numbering-plan validation", {"reason_code": "validation_unavailable"})


def completeness_check(profile: dict | None, source_text: str | None, review_threshold: float = 0.75, fail_threshold: float = 0.25) -> VerificationResultData:
    if not source_text and not profile:
        return VerificationResultData("resume_completeness", "not_verified", "Resume data absent")
    profile = profile or {}
    present = sum(bool(profile.get(k)) for k in ("skills", "employment", "education", "projects"))
    required = ("skills", "employment", "education", "projects")
    missing = [key for key in required if not profile.get(key)]
    ratio = (len(required) - len(missing)) / len(required)
    if len((source_text or "").strip()) < 40:
        status, reason = "needs_review", "below_content_floor"
    elif ratio < fail_threshold:
        status, reason = "failed", "insufficient_sections"
    elif ratio < review_threshold or missing:
        status, reason = "needs_review", "expected_sections_missing"
    else:
        status, reason = "passed", "sections_complete"
    return VerificationResultData("resume_completeness", status,
                                  "Resume section coverage is a parsing signal, not a quality judgment",
                                  {"reason_code": reason, "sections_present": present, "completeness": ratio, "missing_sections": missing})


def _year_month(value: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-\d{2})?)?", value or "")
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2) or 1)
    try:
        date.fromisoformat(value if len(value) == 10 else f"{year:04d}-{month:02d}-01")
    except ValueError:
        return None
    return year, month


def timeline_check(entries: list[dict] | None, today: date) -> VerificationResultData:
    if not entries:
        return VerificationResultData("timeline_consistency", "not_verified", "No timeline data")
    spans = []
    anomalies = []
    for i, row in enumerate(entries):
        start = _year_month(row.get("start_date"))
        end = _year_month(row.get("end_date")) if row.get("end_date") else ((today.year, today.month) if row.get("is_current") else None)
        if row.get("start_date") and start is None or row.get("end_date") and end is None:
            anomalies.append({"index": i, "signal": "malformed_date"}); continue
        if row.get("is_current") and row.get("end_date") and end:
            if end < (today.year, today.month):
                anomalies.append({"index": i, "signal": "current_role_has_past_end"})
            end = (today.year, today.month)
        if not start:
            anomalies.append({"index": i, "signal": "missing_start_date"})
            continue
        if not row.get("end_date") and not row.get("is_current"):
            anomalies.append({"index": i, "signal": "missing_end_date"})
        if start > (today.year, today.month) or (row.get("end_date") and end and end > (today.year, today.month)):
            anomalies.append({"index": i, "signal": "future_date"})
        if end and end < start:
            anomalies.append({"index": i, "signal": "end_before_start"})
        if end and end >= start:
            spans.append((start, end, i))
    overlaps = []
    for n, (start, end, idx) in enumerate(spans):
        for other_start, other_end, other_idx in spans[n + 1:]:
            if start <= other_end and other_start <= end:
                overlaps.append((idx, other_idx))
    gaps = []
    ordered = sorted(spans)
    for left, right in zip(ordered, ordered[1:]):
        delta = (right[0][0] - left[1][0]) * 12 + right[0][1] - left[1][1]
        if delta > 1:
            gaps.append({"months": delta - 1, "signal": "timeline_gap_neutral"})
    if any(item["signal"] in {"end_before_start", "future_date"} for item in anomalies):
        status = "failed"
    elif anomalies or overlaps:
        status = "needs_review"
    else:
        status = "passed"
    return VerificationResultData("timeline_consistency", status, "Timeline consistency signals only", {"anomalies": anomalies, "overlaps": overlaps, "gaps": gaps})


def duplicate_signals(email: str | None, phone: str | None, resume_hash: str | None,
                      existing: list[dict], company_id: str) -> VerificationResultData:
    if not any((email, phone, resume_hash)):
        return VerificationResultData("duplicate_signal", "not_verified", "No comparison identifiers")
    matches = []
    for row in existing:
        if str(row.get("company_id")) != str(company_id):
            continue
        norm_email = lambda x: str(x).strip().casefold()
        norm_phone = lambda x: re.sub(r"\D", "", str(x))
        fields = []
        if email and row.get("email") and norm_email(row["email"]) == norm_email(email): fields.append("email")
        if phone and row.get("phone") and norm_phone(row["phone"]) == norm_phone(phone): fields.append("phone")
        if resume_hash and row.get("resume_hash") and str(row["resume_hash"]).casefold() == str(resume_hash).casefold(): fields.append("resume_hash")
        if fields:
            matches.append({"application_id": str(row.get("application_id")), "fields": fields})
    return VerificationResultData("duplicate_signal", "needs_review" if matches else "passed", "Duplicate indicators only; not a determination of identity", {"matches": matches})


def portfolio_url_check(value: str | None) -> VerificationResultData:
    if not value:
        return VerificationResultData("portfolio_url", "not_verified", "URL absent")
    try:
        parsed = urlparse(value.strip())
        _ = parsed.port
    except ValueError:
        return VerificationResultData("portfolio_url", "failed", "URL format invalid", {"reason_code": "invalid_authority"})
    if len(value) > 2048:
        return VerificationResultData("portfolio_url", "failed", "URL exceeds the supported length", {"reason_code": "url_too_long"})
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return VerificationResultData("portfolio_url", "failed", "URL format invalid")
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        if not ip.is_global:
            return VerificationResultData("portfolio_url", "failed", "Private or reserved address blocked")
    except ValueError:
        pass
    return VerificationResultData("portfolio_url", "passed", "URL format only; a reachable public profile does not prove skills or employment")


def github_url_check(value: str | None) -> VerificationResultData:
    if not value:
        return VerificationResultData("github_url", "not_verified", "GitHub URL absent", {"reason_code": "missing_value"})
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").casefold() not in {"github.com", "www.github.com"} or parsed.username or parsed.password:
        return VerificationResultData("github_url", "failed", "URL must use the public GitHub profile host", {"reason_code": "invalid_host_or_scheme"})
    parts = [part for part in parsed.path.split("/") if part]
    if (len(parts) != 1 or parts[0] in {"features", "topics", "settings", "login", "signup", "orgs", "marketplace"}
            or len(parts[0]) > 39 or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", parts[0])):
        return VerificationResultData("github_url", "failed", "URL must identify one GitHub user profile", {"reason_code": "invalid_profile_path"})
    return VerificationResultData("github_url", "passed", "GitHub profile URL format only; it does not prove skills or employment", {"username": parts[0]})


def overall_status(results: list[VerificationResultData]) -> str:
    """Worst-of check status, in the documented review precedence."""
    order = {"passed": 0, "not_verified": 1, "needs_review": 2, "failed": 3}
    return max((r.status for r in results), key=lambda status: order[status], default="not_verified")


async def url_reachability_check(value: str | None, timeout: float = 2.0, check_type: str = "portfolio_url") -> VerificationResultData:
    """Check public URL reachability while validating every redirect target."""
    base = github_url_check(value) if check_type == "github_url" else portfolio_url_check(value)
    if base.status != "passed":
        return base
    import httpx
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            current = value
            for hop in range(4):
                parsed = urlparse(current)
                infos = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM), timeout=timeout)
                addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
                if not addresses or any(not address.is_global for address in addresses):
                    return VerificationResultData(check_type, "failed", "URL resolves to a private or reserved address", {"reason_code": "blocked_address", "redirect_hop": hop})
                response = await client.head(current, headers={"User-Agent": "Job-Sentry-verification"})
                status_code, location = response.status_code, response.headers.get("location")
                if status_code in {405, 501}:
                    async with client.stream("GET", current, headers={"User-Agent": "Job-Sentry-verification", "Range": "bytes=0-0"}) as fallback:
                        status_code, location = fallback.status_code, fallback.headers.get("location")
                if status_code not in {301, 302, 303, 307, 308}:
                    if status_code >= 400:
                        return VerificationResultData(check_type, "needs_review", "Public URL returned an unsuccessful response", {"status_code": status_code})
                    return VerificationResultData(check_type, "passed", "URL is reachable; this does not prove identity, skills, or employment", {"redirects_followed": hop})
                if not location:
                    return VerificationResultData(check_type, "needs_review", "Redirect has no destination", {"reason_code": "invalid_redirect"})
                if hop == 3:
                    return VerificationResultData(check_type, "needs_review", "URL exceeded the redirect limit", {"reason_code": "redirect_limit"})
                current = urljoin(current, location)
                if parsed.scheme == "https" and urlparse(current).scheme != "https":
                    return VerificationResultData(check_type, "failed", "HTTPS redirects may not downgrade to HTTP", {"reason_code": "scheme_downgrade"})
                redirected = github_url_check(current) if check_type == "github_url" else portfolio_url_check(current)
                if redirected.status != "passed":
                    return VerificationResultData(check_type, "failed", "Redirect target URL is not allowed", {"reason_code": "invalid_redirect_target"})
    except (OSError, asyncio.TimeoutError, httpx.HTTPError):
        return VerificationResultData(check_type, "not_verified", "URL reachability could not be verified", {"reason_code": "network_unavailable"})
