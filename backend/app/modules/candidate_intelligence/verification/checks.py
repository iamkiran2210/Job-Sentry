from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from datetime import date
from urllib.parse import urljoin, urlparse

from app.modules.candidate_intelligence.types import VerificationResultData

EMAIL_RE = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.I,
)
EMAIL_CANDIDATE_RE = re.compile(
    r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+",
    re.I,
)
PHONE_RE = re.compile(r"^\+?[0-9][0-9 .()\-]{6,24}[0-9]$")


def email_check(value: str | None, enabled: bool = True) -> VerificationResultData:
    return email_verification(value, enabled)


def email_verification(value: str | None, enabled: bool = True) -> VerificationResultData:
    if not enabled:
        return VerificationResultData(
            "email_syntax",
            "not_verified",
            "Email check is disabled",
            {"reason_code": "check_disabled"},
        )
    if not value:
        return VerificationResultData(
            "email_syntax", "not_verified", "Email absent", {"reason_code": "missing_value"}
        )
    found = EMAIL_CANDIDATE_RE.findall(value)
    if len(found) > 1:
        return VerificationResultData(
            "email_syntax",
            "needs_review",
            "Multiple email addresses were provided",
            {"reason_code": "multiple_emails"},
        )
    normalized = normalize_email(value)
    internal_spaces_removed = bool(re.search(r"\s", value.strip()))
    valid = bool(EMAIL_RE.fullmatch(normalized))
    try:
        from email_validator import validate_email

        validate_email(normalized, check_deliverability=False)
    except ImportError:
        pass
    except Exception:
        valid = False
    if not valid:
        return VerificationResultData(
            "email_syntax", "failed", "Email syntax is malformed", {"reason_code": "invalid_syntax"}
        )
    local, domain = normalized.rsplit("@", 1)
    role_accounts = {
        "admin",
        "careers",
        "contact",
        "info",
        "jobs",
        "office",
        "recruiting",
        "support",
        "team",
        "webmaster",
    }
    disposable_domains = {
        "10minutemail.com",
        "guerrillamail.com",
        "mailinator.com",
        "tempmail.com",
        "yopmail.com",
    }
    signals = []
    if local.casefold() in role_accounts:
        signals.append("role_account")
    if domain.casefold() in disposable_domains:
        signals.append("disposable_domain")
    if internal_spaces_removed:
        signals.append("internal_whitespace_removed")
    status = "needs_review" if signals else "passed"
    return VerificationResultData(
        "email_syntax",
        status,
        "Syntax only; does not prove control of address",
        {"reason_code": signals[0] if signals else "syntax_valid", "signals": signals},
    )


def normalize_email(value: str | None) -> str | None:
    """Normalize email whitespace without modifying the caller's raw string."""
    if value is None:
        return None
    return re.sub(r"\s+", "", value.strip()).casefold()


def phone_check(value: str | None, region: str | None = None) -> VerificationResultData:
    if not value:
        return VerificationResultData(
            "phone_format", "not_verified", "Phone absent", {"reason_code": "missing_value"}
        )
    normalized = value.strip()
    try:
        import phonenumbers

        if _phone_match_count(normalized, region) > 1:
            return VerificationResultData(
                "phone_format",
                "needs_review",
                "Multiple phone numbers were provided",
                {"reason_code": "multiple_numbers"},
            )
        if not re.search(r"\d", normalized):
            return VerificationResultData(
                "phone_format",
                "failed",
                "Phone number is malformed",
                {"reason_code": "invalid_number"},
            )
        if not normalized.startswith(("+", "00")) and not region:
            return VerificationResultData(
                "phone_format",
                "not_verified",
                "National phone number cannot be validated without a configured region",
                {"reason_code": "region_not_configured"},
            )
        parsed = phonenumbers.parse(
            "+" + normalized[2:] if normalized.startswith("00") else normalized, region
        )
        if not phonenumbers.is_possible_number(parsed):
            return VerificationResultData(
                "phone_format",
                "failed",
                "Phone number is not valid for its numbering plan",
                {"reason_code": "invalid_number"},
            )
        if not phonenumbers.is_valid_number(parsed):
            return VerificationResultData(
                "phone_format",
                "needs_review",
                "Phone number has a possible format but is not currently valid for its numbering plan",
                {"reason_code": "possible_not_valid"},
            )
        e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        details = {"normalized_e164": e164}
        if parsed.extension:
            details["extension"] = parsed.extension
        if normalized.startswith("00"):
            details["converted_international_prefix"] = True
        return VerificationResultData(
            "phone_format", "passed", "Format only; does not prove control of number", details
        )
    except ImportError:
        pass
    except Exception:
        return VerificationResultData(
            "phone_format", "failed", "Phone number is malformed", {"reason_code": "invalid_number"}
        )
    digits = re.sub(r"\D", "", normalized)
    if not PHONE_RE.fullmatch(normalized) or not 7 <= len(digits) <= 15:
        return VerificationResultData(
            "phone_format",
            "needs_review",
            "Phone format could not be validated without numbering-plan metadata",
            {"reason_code": "validation_unavailable"},
        )
    if not normalized.startswith("+"):
        return VerificationResultData(
            "phone_format",
            "needs_review",
            "National phone number requires a configured region",
            {"reason_code": "region_required"},
        )
    return VerificationResultData(
        "phone_format",
        "needs_review",
        "Phone format is plausible; install phonenumbers for numbering-plan validation",
        {"reason_code": "validation_unavailable"},
    )


def _phone_match_count(value: str, region: str | None) -> int:
    try:
        import phonenumbers

        return sum(1 for _ in phonenumbers.PhoneNumberMatcher(value, region))
    except (ImportError, Exception):
        return 0


def normalize_phone(value: str | None, region: str | None = None) -> str | None:
    """Return canonical E.164 when numbering-plan metadata can parse the value."""
    if not value:
        return None
    try:
        import phonenumbers

        normalized = value.strip()
        if normalized.startswith("00"):
            normalized = "+" + normalized[2:]
        elif not normalized.startswith("+") and not region:
            return None
        parsed = phonenumbers.parse(normalized, region)
        if not phonenumbers.is_possible_number(parsed) or not phonenumbers.is_valid_number(parsed):
            return None
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        return None


def completeness_check(
        profile: dict | None,
        source_text: str | None,
        review_threshold: float = 0.80,
        fail_threshold: float = 0.50,
) -> VerificationResultData:
    if not profile:
        return VerificationResultData("resume_completeness", "not_verified", "Resume data absent")
    present = sum(
        bool(profile.get(k))
        for k in ("skills", "employment", "education", "projects", "certifications")
    )
    required = ("skills", "employment", "education", "projects", "certifications")
    missing = [key for key in required if not profile.get(key)]
    parsed_ratio = profile.get("completeness")
    ratio = (
        max(0.0, min(1.0, float(parsed_ratio)))
        if isinstance(parsed_ratio, (int, float))
        else (len(required) - len(missing)) / len(required)
    )
    if ratio < fail_threshold:
        status, reason = "failed", "insufficient_sections"
    elif ratio < review_threshold:
        status, reason = "needs_review", "expected_sections_missing"
    else:
        status, reason = "passed", "sections_complete"
    return VerificationResultData(
        "resume_completeness",
        status,
        "Resume section coverage is a parsing signal, not a quality judgment",
        {
            "reason_code": reason,
            "sections_present": present,
            "completeness": ratio,
            "missing_sections": missing,
        },
    )


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


def timeline_check(
    entries: list[dict] | None,
    today: date,
    overlap_tolerance_months: int = 1,
    gap_threshold_months: int = 12,
) -> VerificationResultData:
    if not entries:
        return VerificationResultData("timeline_consistency", "not_verified", "No timeline data")
    spans = []
    anomalies = []
    for i, row in enumerate(entries):
        start = _year_month(row.get("start_date"))
        end = (
            _year_month(row.get("end_date"))
            if row.get("end_date")
            else ((today.year, today.month) if row.get("is_current") else None)
        )
        if (row.get("start_date") and start is None) or (row.get("end_date") and end is None):
            anomalies.append({"index": i, "signal": "malformed_date"})
            continue
        if row.get("is_current") and row.get("end_date") and end:
            if end < (today.year, today.month):
                anomalies.append({"index": i, "signal": "current_role_has_past_end"})
            end = (today.year, today.month)
        if not start:
            anomalies.append({"index": i, "signal": "missing_start_date"})
            continue
        if not row.get("end_date") and not row.get("is_current"):
            anomalies.append({"index": i, "signal": "missing_end_date"})
        if start > (today.year, today.month) or (
                row.get("end_date") and end and end > (today.year, today.month)
        ):
            anomalies.append({"index": i, "signal": "future_date"})
        if end and end < start:
            anomalies.append({"index": i, "signal": "end_before_start"})
        if end and end >= start:
            spans.append((start, end, i))
    overlaps = []
    for n, (start, end, idx) in enumerate(spans):
        for other_start, other_end, other_idx in spans[n + 1:]:
            overlap_start, overlap_end = max(start, other_start), min(end, other_end)
            if overlap_start <= overlap_end:
                months = (
                        (overlap_end[0] - overlap_start[0]) * 12 + overlap_end[1] - overlap_start[1] + 1
                )
                if months > overlap_tolerance_months:
                    overlaps.append({"entries": [idx, other_idx], "months": months})
    gaps = []
    ordered = sorted(spans)
    for left, right in zip(ordered, ordered[1:]):
        delta = (right[0][0] - left[1][0]) * 12 + right[0][1] - left[1][1]
        missing_months = delta - 1
        if missing_months > gap_threshold_months:
            gaps.append(
                {
                    "months": missing_months,
                    "signal": "timeline_gap_neutral",
                    "message": "Dates show a gap; this is temporal information only.",
                }
            )
    if any(
            item["signal"] in {"end_before_start", "future_date", "malformed_date"}
            for item in anomalies
    ):
        status = "failed"
    elif anomalies or overlaps or gaps:
        status = "needs_review"
    elif len(spans) < 2:
        status = "not_verified"
    else:
        status = "passed"
    signal = (
        "Timeline dates are temporal signals only; gaps do not indicate performance."
        if gaps
        else "Timeline consistency signals only; they do not prove performance or employment."
    )
    return VerificationResultData(
        "timeline_consistency",
        status,
        signal,
        {"anomalies": anomalies, "overlaps": overlaps, "gaps": gaps},
    )


def duplicate_signals(
        email: str | None,
        phone: str | None,
        resume_hash: str | None,
        existing: list[dict],
        company_id: str,
        *,
        scope: str = "company",
        job_id: str | None = None,
        phone_region: str | None = None,
) -> VerificationResultData:
    if not any((email, phone, resume_hash)):
        return VerificationResultData(
            "duplicate_signal", "not_verified", "No comparison identifiers"
        )
    if scope not in {"job", "company"}:
        raise ValueError("duplicate scope must be 'job' or 'company'")
    candidates = [
        row
        for row in existing
        if str(row.get("company_id")) == str(company_id)
           and (scope != "job" or str(row.get("job_id")) == str(job_id))
    ]
    if not candidates:
        return VerificationResultData(
            "duplicate_signal",
            "not_verified",
            "No comparable applications in the configured scope",
            {"reason_code": "no_comparisons", "scope": scope},
        )
    matches = []
    normalized_email = normalize_email(email)
    normalized_phone = normalize_phone(phone, phone_region)
    for row in candidates:
        fields = []
        if normalized_email and normalize_email(row.get("email")) == normalized_email:
            fields.append("email")
        row_phone = normalize_phone(row.get("phone"), phone_region)
        if normalized_phone and row_phone == normalized_phone:
            fields.append("phone")
        if (
                resume_hash
                and row.get("resume_hash")
                and str(row["resume_hash"]).casefold() == str(resume_hash).casefold()
        ):
            fields.append("resume_hash")
        if fields:
            matches.append({"application_id": str(row.get("application_id")), "fields": fields})
    return VerificationResultData(
        "duplicate_signal",
        "needs_review" if matches else "passed",
        "Duplicate indicators only; they do not determine identity.",
        {"matches": matches, "scope": scope},
    )


def portfolio_url_check(value: str | None) -> VerificationResultData:
    if not value:
        return VerificationResultData("portfolio_url", "not_verified", "URL absent")
    try:
        parsed = urlparse(value.strip())
        _ = parsed.port
    except ValueError:
        return VerificationResultData(
            "portfolio_url", "failed", "URL format invalid", {"reason_code": "invalid_authority"}
        )
    if len(value) > 2048:
        return VerificationResultData(
            "portfolio_url",
            "failed",
            "URL exceeds the supported length",
            {"reason_code": "url_too_long"},
        )
    if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
    ):
        return VerificationResultData(
            "portfolio_url", "failed", "URL format invalid", {"reason_code": "invalid_url"}
        )
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        if not ip.is_global:
            return VerificationResultData(
                "portfolio_url",
                "failed",
                "Private or reserved address blocked",
                {"reason_code": "ssrf_blocked"},
            )
    except ValueError:
        pass
    return VerificationResultData(
        "portfolio_url",
        "passed",
        "URL format only; a reachable public profile does not prove skills or employment",
    )


def github_url_check(value: str | None) -> VerificationResultData:
    if not value:
        return VerificationResultData(
            "github_url", "not_verified", "GitHub URL absent", {"reason_code": "missing_value"}
        )
    parsed = urlparse(value.strip())
    if (
            parsed.scheme not in {"http", "https"}
            or (parsed.hostname or "").casefold() not in {"github.com", "www.github.com"}
            or parsed.username
            or parsed.password
    ):
        return VerificationResultData(
            "github_url",
            "failed",
            "URL must use the public GitHub profile host",
            {"reason_code": "invalid_host_or_scheme"},
        )
    parts = [part for part in parsed.path.split("/") if part]
    reserved = {"features", "topics", "settings", "login", "signup", "orgs", "marketplace"}
    if (
            len(parts) not in {1, 2}
            or not parts
            or parts[0].casefold() in reserved
            or len(parts[0]) > 39
            or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", parts[0])
    ):
        return VerificationResultData(
            "github_url",
            "needs_review",
            "GitHub path is not a user profile or repository path",
            {"reason_code": "wrong_path_shape"},
        )
    if len(parts) == 2 and not re.fullmatch(r"[A-Za-z0-9_.-]+", parts[1]):
        return VerificationResultData(
            "github_url",
            "needs_review",
            "GitHub repository path is malformed",
            {"reason_code": "wrong_path_shape"},
        )
    return VerificationResultData(
        "github_url",
        "passed",
        "GitHub profile or repository path format only; it does not prove skills or employment",
        {"username": parts[0]},
    )


def overall_status(results: list[VerificationResultData]) -> str:
    """Worst-of check status, in the documented review precedence."""
    order = {"passed": 0, "not_verified": 1, "needs_review": 2, "failed": 3}
    return max(
        (r.status for r in results), key=lambda status: order[status], default="not_verified"
    )


async def url_reachability_check(
    value: str | None,
    timeout: float = 2.0,
    check_type: str = "portfolio_url",
    *,
    enabled: bool = True,
    transport=None,
    resolver=None,
) -> VerificationResultData:
    """Check a public URL without forwarding credentials or trusting redirects."""
    import inspect
    import httpx

    base = github_url_check(value) if check_type == "github_url" else portfolio_url_check(value)
    if base.status != "passed":
        return base
    if not enabled:
        return VerificationResultData(
            check_type,
            "not_verified",
            "URL reachability check is disabled",
            {"reason_code": "reachability_disabled"},
        )

    original_host = (urlparse(value.strip()).hostname or "").casefold()
    current = value.strip()
    seen = set()
    try:
        async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=False, transport=transport, trust_env=False
        ) as client:
            for hop in range(4):
                parsed = urlparse(current)
                current_key = current.split("#", 1)[0]
                if current_key in seen:
                    return VerificationResultData(
                        check_type,
                        "needs_review",
                        "URL redirect loop detected",
                        {"reason_code": "url_redirect_loop", "redirect_hop": hop},
                    )
                seen.add(current_key)

                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                if resolver is None:
                    infos = await asyncio.wait_for(
                        asyncio.get_running_loop().getaddrinfo(
                            parsed.hostname, port, type=socket.SOCK_STREAM
                        ),
                        timeout=timeout,
                    )
                    addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
                else:
                    resolved = resolver(parsed.hostname, port)
                    if inspect.isawaitable(resolved):
                        resolved = await asyncio.wait_for(resolved, timeout=timeout)
                    addresses = {ipaddress.ip_address(address) for address in resolved}
                if not addresses or any(not address.is_global for address in addresses):
                    return VerificationResultData(
                        check_type,
                        "failed",
                        "URL resolves to a private or reserved address",
                        {"reason_code": "ssrf_blocked", "redirect_hop": hop},
                    )

                headers = {"User-Agent": "Job-Sentry-verification"}
                request = client.build_request("HEAD", current, headers=headers)
                request.headers.pop("cookie", None)
                request.headers.pop("authorization", None)
                response = await client.send(request, follow_redirects=False)
                client.cookies.clear()
                status_code, location = response.status_code, response.headers.get("location")
                if status_code in {405, 501}:
                    fallback = client.build_request(
                        "GET", current, headers={**headers, "Range": "bytes=0-0"}
                    )
                    fallback.headers.pop("cookie", None)
                    fallback.headers.pop("authorization", None)
                    response = await client.send(fallback, follow_redirects=False)
                    client.cookies.clear()
                    status_code, location = response.status_code, response.headers.get("location")

                if status_code not in {301, 302, 303, 307, 308}:
                    if status_code == 404:
                        return VerificationResultData(
                            check_type,
                            "needs_review",
                            "Public URL was not found; reachability does not prove skills or employment",
                            {"reason_code": "url_not_found", "status_code": status_code},
                        )
                    if status_code == 403:
                        return VerificationResultData(
                            check_type,
                            "needs_review",
                            "Public URL access was forbidden; reachability does not prove skills or employment",
                            {"reason_code": "url_forbidden", "status_code": status_code},
                        )
                    if status_code >= 500:
                        return VerificationResultData(
                            check_type,
                            "needs_review",
                            "Public URL server returned an error; reachability does not prove skills or employment",
                            {"reason_code": "url_server_error", "status_code": status_code},
                        )
                    if status_code >= 400:
                        return VerificationResultData(
                            check_type,
                            "needs_review",
                            "Public URL returned an unsuccessful response; reachability does not prove skills or employment",
                            {"reason_code": "url_http_error", "status_code": status_code},
                        )
                    return VerificationResultData(
                        check_type,
                        "passed",
                        "URL is reachable; reachability proves nothing about skills or employment",
                        {"redirects_followed": hop},
                    )

                if not location:
                    return VerificationResultData(
                        check_type,
                        "needs_review",
                        "Redirect has no destination",
                        {"reason_code": "invalid_redirect"},
                    )
                if hop == 3:
                    return VerificationResultData(
                        check_type,
                        "needs_review",
                        "URL exceeded the redirect limit",
                        {"reason_code": "url_redirect_limit"},
                    )
                redirected_url = urljoin(current, location)
                redirected = urlparse(redirected_url)
                if (
                        redirected.scheme not in {"http", "https"}
                        or not redirected.hostname
                        or redirected.username
                        or redirected.password
                ):
                    return VerificationResultData(
                        check_type,
                        "failed",
                        "Redirect target URL is malformed",
                        {"reason_code": "invalid_url", "redirect_hop": hop + 1},
                    )
                if (redirected.hostname or "").casefold() != original_host:
                    return VerificationResultData(
                        check_type,
                        "needs_review",
                        "Redirect changes the URL host; the destination was not checked",
                        {"reason_code": "url_redirect_different_host", "redirect_hop": hop + 1},
                    )
                if parsed.scheme == "https" and redirected.scheme != "https":
                    return VerificationResultData(
                        check_type,
                        "needs_review",
                        "Redirect downgrades from HTTPS",
                        {"reason_code": "url_redirect_downgrade", "redirect_hop": hop + 1},
                    )
                redirected_check = (
                    github_url_check(redirected_url)
                    if check_type == "github_url"
                    else portfolio_url_check(redirected_url)
                )
                if redirected_check.status != "passed":
                    reason = redirected_check.details.get("reason_code")
                    if reason == "ssrf_blocked":
                        return VerificationResultData(
                            check_type,
                            "failed",
                            "Redirect target is an SSRF-blocked address",
                            {"reason_code": "ssrf_blocked", "redirect_hop": hop + 1},
                        )
                    return VerificationResultData(
                        check_type,
                        "needs_review",
                        "Redirect target could not be validated",
                        {"reason_code": "invalid_redirect_target", "redirect_hop": hop + 1},
                    )
                current = redirected_url
    except asyncio.TimeoutError:
        return VerificationResultData(
            check_type, "not_verified", "URL reachability timed out", {"reason_code": "timeout"}
        )
    except socket.gaierror:
        return VerificationResultData(
            check_type, "not_verified", "URL DNS lookup failed", {"reason_code": "dns_failure"}
        )
    except httpx.TimeoutException:
        return VerificationResultData(
            check_type, "not_verified", "URL reachability timed out", {"reason_code": "timeout"}
        )
    except (OSError, httpx.HTTPError):
        return VerificationResultData(
            check_type,
            "not_verified",
            "URL reachability could not be verified",
            {"reason_code": "network_unavailable"},
        )


_DISPOSABLE_EMAIL_DOMAINS = frozenset(
    {
        "10minutemail.com",
        "10minutemail.net",
        "dispostable.com",
        "fakeinbox.com",
        "getnada.com",
        "guerrillamail.com",
        "guerrillamailblock.com",
        "maildrop.cc",
        "mailinator.com",
        "sharklasers.com",
        "temp-mail.org",
        "tempmail.com",
        "tempmailo.com",
        "throwawaymail.com",
        "trashmail.com",
        "yopmail.com",
    }
)

_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?", re.I),
    re.compile(r"(?:rank|score|rate)\s+this\s+candidate\s+(?:first|100|highest|top)", re.I),
    re.compile(r"(?:system\s+prompt|developer\s+message|you\s+are\s+now\s+an?\s+ai)", re.I),
    re.compile(r"(?:override|bypass)\s+(?:scoring|evaluation|verification|filter)", re.I),
)

_AI_TEMPLATE_PLACEHOLDERS = (
    re.compile(r"\bas\s+an\s+ai\s+language\s+model\b", re.I),
    re.compile(r"\blorem\s+ipsum\b", re.I),
    re.compile(r"\[(?:insert|your|company\s+name|job\s+title|date|degree|university)[^\]]{0,40}\]", re.I),
    re.compile(r"\b(?:your\s+name\s+here|insert\s+summary\s+here)\b", re.I),
)

_AI_CLICHE_PHRASES = (
    "results-driven professional",
    "proven track record of success",
    "dynamic and motivated",
    "passionate about leveraging cutting-edge",
    "synergistic solutions",
    "spearheaded cross-functional initiatives",
    "detail-oriented team player",
    "fast-paced environment",
)


def _dns_domain_check_sync(domain: str, timeout: float) -> tuple[str, list[str]]:
    """Return ('mx'|'a'|'nxdomain'|'unavailable', records)."""
    try:
        import dns.resolver

        res = dns.resolver.Resolver()
        res.lifetime = max(0.5, float(timeout))
        res.timeout = max(0.5, float(timeout))
        try:
            mx = res.resolve(domain, "MX")
            hosts = [str(r.exchange).rstrip(".") for r in mx][:5]
            if hosts:
                return "mx", hosts
        except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            pass
        except dns.resolver.NXDOMAIN:
            return "nxdomain", []
        try:
            a_rec = res.resolve(domain, "A")
            addrs = [str(r) for r in a_rec][:5]
            if addrs:
                return "a", addrs
        except dns.resolver.NXDOMAIN:
            return "nxdomain", []
        except Exception:
            return "unavailable", []
        return "unavailable", []
    except ImportError:
        try:
            infos = socket.getaddrinfo(domain, None)
            if infos:
                return "a", [str(infos[0][4][0])]
        except socket.gaierror:
            return "nxdomain", []
        except OSError:
            return "unavailable", []
    except Exception:
        return "unavailable", []


async def email_domain_check(
        value: str | None,
        *,
        enabled: bool = True,
        timeout: float = 2.0,
        dns_lookup=None,
) -> VerificationResultData:
    """Verify email domain MX/A DNS records and detect disposable throwaway email providers."""
    if not enabled:
        return VerificationResultData(
            "email_domain",
            "not_verified",
            "Email domain verification is disabled",
            {"reason_code": "check_disabled"},
        )
    if not value:
        return VerificationResultData(
            "email_domain",
            "not_verified",
            "Email absent",
            {"reason_code": "missing_value"},
        )
    normalized = normalize_email(value) or ""
    if not EMAIL_RE.fullmatch(normalized):
        return VerificationResultData(
            "email_domain",
            "failed",
            "Email address is malformed; cannot verify domain",
            {"reason_code": "invalid_syntax"},
        )
    domain = normalized.rsplit("@", 1)[1].casefold()
    if domain in _DISPOSABLE_EMAIL_DOMAINS:
        return VerificationResultData(
            "email_domain",
            "failed",
            "Email uses a known disposable/temporary domain",
            {"reason_code": "disposable_domain", "domain": domain},
        )
    if domain in {"example.com", "example.org", "example.net", "example.test", "test.local",
                  "localhost"} or domain.endswith((".test", ".invalid", ".local")):
        return VerificationResultData(
            "email_domain",
            "not_verified",
            "Reserved or non-routable test domain",
            {"reason_code": "reserved_domain", "domain": domain},
        )

    try:
        if dns_lookup is not None:
            outcome, records = dns_lookup(domain)
        else:
            outcome, records = await asyncio.wait_for(
                asyncio.to_thread(_dns_domain_check_sync, domain, timeout),
                timeout=max(0.5, timeout + 0.5),
            )
    except (asyncio.TimeoutError, TimeoutError):
        return VerificationResultData(
            "email_domain",
            "not_verified",
            "Email domain DNS check timed out",
            {"reason_code": "dns_timeout", "domain": domain},
        )
    except Exception:
        return VerificationResultData(
            "email_domain",
            "not_verified",
            "Email domain DNS check unavailable",
            {"reason_code": "dns_unavailable", "domain": domain},
        )

    if outcome == "mx":
        return VerificationResultData(
            "email_domain",
            "passed",
            "Email domain has valid MX mail records",
            {"reason_code": "mx_verified", "domain": domain, "mx_records": records[:3]},
        )
    if outcome == "a":
        return VerificationResultData(
            "email_domain",
            "passed",
            "Email domain resolves in DNS (A record present; no explicit MX)",
            {"reason_code": "a_record_verified", "domain": domain},
        )
    if outcome == "nxdomain":
        return VerificationResultData(
            "email_domain",
            "failed",
            "Email domain does not exist in DNS (NXDOMAIN)",
            {"reason_code": "domain_not_found", "domain": domain},
        )
    return VerificationResultData(
        "email_domain",
        "not_verified",
        "Email domain DNS lookup was inconclusive",
        {"reason_code": "dns_unavailable", "domain": domain},
    )


def content_authenticity_check(
        source_text: str | None,
        profile: dict | None = None,
        *,
        enabled: bool = True,
) -> VerificationResultData:
    """Detect suspicious resume fraud signals (prompt injection, unfilled AI templates, boilerplate stuffing)."""
    if not enabled:
        return VerificationResultData(
            "content_authenticity",
            "not_verified",
            "Content authenticity check is disabled",
            {"reason_code": "check_disabled"},
        )
    text = (source_text or "").strip()
    if not text:
        return VerificationResultData(
            "content_authenticity",
            "not_verified",
            "No resume source text available for authenticity inspection",
            {"reason_code": "missing_source_text"},
        )

    flags: list[str] = []
    risk_points = 0

    # 1. Prompt-injection attempt (high-severity manipulation/fraud signal)
    injection_hits = [p.pattern for p in _PROMPT_INJECTION_PATTERNS if p.search(text)]
    if injection_hits:
        flags.append("prompt_injection_detected")
        risk_points += 65

    # 2. Unfilled AI / template placeholders
    placeholder_hits = [p.search(text).group(0)[:60] for p in _AI_TEMPLATE_PLACEHOLDERS if p.search(text)]
    if placeholder_hits:
        flags.append("unfilled_template_or_ai_placeholder")
        risk_points += 40

    # 3. Heavy AI cliché density (advisory authenticity signal, never standalone proof)
    lowered = text.casefold()
    cliche_hits = [c for c in _AI_CLICHE_PHRASES if c in lowered]
    if len(cliche_hits) >= 4:
        flags.append("high_generic_ai_boilerplate_density")
        risk_points += 25

    # 4. Keyword stuffing / extreme duplicate line ratio
    lines = [re.sub(r"\s+", " ", ln).strip().casefold() for ln in text.splitlines() if len(ln.strip()) >= 25]
    if len(lines) >= 8:
        unique_ratio = len(set(lines)) / len(lines)
        if unique_ratio < 0.65:
            flags.append("excessive_duplicate_content")
            risk_points += 25

    # 5. Implausible skill stuffing without supporting employment/project narrative
    skills_count = len((profile or {}).get("skills") or [])
    words_count = len(re.findall(r"[A-Za-z0-9]+", text))
    if skills_count >= 50 and words_count < 220:
        flags.append("possible_keyword_stuffing")
        risk_points += 25

    risk_score = min(100, risk_points)
    if injection_hits or risk_score >= 60:
        status = "failed"
        signal = "High-risk suspicious content detected (possible prompt injection or manipulated template)"
    elif flags:
        status = "needs_review"
        signal = f"Content authenticity review suggested ({', '.join(f.replace('_', ' ') for f in flags)})"
    else:
        status = "passed"
        signal = "No prompt-injection, template placeholder, or stuffing anomalies detected"

    return VerificationResultData(
        "content_authenticity",
        status,
        signal,
        {
            "reason_code": flags[0] if flags else "authentic_signals_clean",
            "risk_score": risk_score,
            "flags": flags,
            "cliche_count": len(cliche_hits),
        },
    )


def compute_fraud_risk_summary(results: list[VerificationResultData]) -> dict:
    """Aggregate verification results into a transparent 0-100 fraud & authenticity risk summary."""
    weights = {
        "content_authenticity": (45, 20),
        "email_domain": (30, 12),
        "email_syntax": (20, 8),
        "duplicate_signal": (25, 15),
        "timeline_consistency": (25, 12),
        "linkedin_profile": (30, 14),
        "github_profile": (20, 10),
        "portfolio_ai": (20, 10),
        "project_links": (20, 10),
        "resume_completeness": (15, 6),
    }
    score = 0
    flags: list[str] = []
    for r in results:
        fail_w, review_w = weights.get(r.check_type, (15, 6))
        if r.status == "failed":
            score += fail_w
            flags.append(f"{r.check_type.replace('_', ' ')}: {r.signal[:100]}")
        elif r.status == "needs_review":
            score += review_w
            if r.check_type in {
                "content_authenticity",
                "duplicate_signal",
                "timeline_consistency",
                "linkedin_profile",
                "email_domain",
            }:
                flags.append(f"{r.check_type.replace('_', ' ')}: {r.signal[:100]}")
    score = min(100, score)
    level = "high" if score >= 50 else "medium" if score >= 20 else "low"
    return {"score": score, "level": level, "flags": flags[:8]}
