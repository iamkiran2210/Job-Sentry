from __future__ import annotations

import logging
import socket
from datetime import date
from uuid import uuid4

import httpx
import pytest

from app.ai_features.models.application import Application
from app.models.job import EmploymentType, Job, WorkMode
from app.modules.candidate_intelligence.config import CandidateIntelligenceSettings
from app.modules.candidate_intelligence.types import VerificationResultData
from app.modules.candidate_intelligence.verification.checks import (
    completeness_check,
    duplicate_signals,
    email_check,
    github_url_check,
    normalize_email,
    normalize_phone,
    overall_status,
    phone_check,
    portfolio_url_check,
    timeline_check,
    url_reachability_check,
)


@pytest.mark.parametrize(
    ("value", "status"),
    [
        ("  person@example.com  ", "passed"),
        ("per son@example.com", "needs_review"),
        ("one@example.com; two@example.com", "needs_review"),
        ("recruiting@example.com", "needs_review"),
        ("person@mailinator.com", "needs_review"),
        ("not-an-email", "failed"),
        (None, "not_verified"),
    ],
    ids=["edge-trim", "internal-space", "multiple", "role-domain", "disposable-domain", "invalid", "absent"],
)
def test_email_verification_matrix(value, status):
    assert email_check(value).status == status


def test_email_check_disabled_is_not_verified():
    result = email_check("person@example.com", enabled=False)
    assert result.status == "not_verified"
    assert result.details["reason_code"] == "check_disabled"


@pytest.mark.parametrize(
    ("value", "region", "status", "normalized", "reason"),
    [
        ("+1 415 555 2671", None, "passed", "+14155552671", None),
        ("9876543210", "IN", "passed", "+919876543210", None),
        ("0091 98765 43210", None, "passed", "+919876543210", None),
        ("+1 415 555 2671 x123", None, "passed", "+14155552671", None),
        ("+1 415 555 2671 / +1 212 555 0199", None, "needs_review", None, "multiple_numbers"),
        ("+1 (555) 123-4567", None, "needs_review", None, "possible_not_valid"),
        ("+1 23", None, "failed", None, None),
        ("letters only", None, "failed", None, None),
        (None, None, "not_verified", None, None),
        ("9876543210", None, "not_verified", None, "region_not_configured"),
    ],
    ids=["plus-prefix", "local-IN", "international-00", "extension", "multiple", "possible-not-valid", "impossible", "unparseable", "absent", "no-region"],
)
def test_phone_verification_matrix(value, region, status, normalized, reason):
    result = phone_check(value, region)
    assert result.status == status
    if normalized:
        assert result.details["normalized_e164"] == normalized
    if value and "x123" in value:
        assert result.details["extension"] == "123"
    if reason:
        assert result.details["reason_code"] == reason


@pytest.mark.parametrize(
    ("ratio", "status"),
    [(0.8, "passed"), (0.65, "needs_review"), (0.5, "needs_review"), (0.49, "failed")],
    ids=["exact-pass-threshold", "between-thresholds", "exact-floor", "below-floor"],
)
def test_completeness_threshold_matrix(ratio, status):
    result = completeness_check({"completeness": ratio}, "parsed resume text")
    assert result.status == status
    assert result.details["completeness"] == ratio


def test_completeness_thresholds_are_read_from_settings():
    settings = CandidateIntelligenceSettings(completeness_review_threshold=0.9, completeness_fail_threshold=0.4)
    result = completeness_check({"completeness": 0.8}, "parsed resume", settings.completeness_review_threshold, settings.completeness_fail_threshold)
    assert result.status == "needs_review"


def test_completeness_without_parsed_resume_is_not_verified():
    assert completeness_check(None, None).status == "not_verified"


@pytest.mark.parametrize(
    ("entries", "expected", "details_key"),
    [
        ([{"start_date": "2020-01", "end_date": "2020-12"}, {"start_date": "2021-01", "end_date": "2021-12"}], "passed", None),
        ([{"start_date": "2020-01", "end_date": "2021-12"}, {"start_date": "2021-01", "end_date": "2022-01"}], "needs_review", "overlaps"),
        ([{"start_date": "2000-01", "end_date": "2000-03"}, {"start_date": "2002-01", "end_date": "2002-03"}], "needs_review", "gaps"),
        ([{"start_date": "2021-01", "end_date": "2020-01"}, {"start_date": "2022-01", "end_date": "2022-12"}], "failed", "anomalies"),
        ([{"start_date": "2026-01", "end_date": "2026-12"}, {"start_date": "2022-01", "end_date": "2022-12"}], "failed", "anomalies"),
        ([{"start_date": "2021-13", "end_date": "2022-01"}, {"start_date": "2022-01", "end_date": "2022-12"}], "failed", "anomalies"),
        ([{"start_date": "2020-01", "end_date": "2020-12"}], "not_verified", None),
    ],
    ids=["no-issues", "overlap", "gap", "end-before-start", "future", "malformed", "fewer-than-two"],
)
def test_timeline_matrix(entries, expected, details_key):
    result = timeline_check(entries, date(2025, 1, 1), overlap_tolerance_months=1, gap_threshold_months=6)
    assert result.status == expected
    if details_key:
        assert result.details[details_key]
    if expected == "needs_review" and details_key == "gaps":
        assert "temporal" in result.signal.casefold()
        assert "performance" in result.signal.casefold()


def test_duplicate_signal_matrix_and_never_fails():
    company, job, other_job = "company-a", "job-a", "job-b"
    same_job = {"company_id": company, "job_id": job, "application_id": "app-1", "email": "x@example.com", "phone": "+919876543210", "resume_hash": "abc"}
    other_job_row = {**same_job, "job_id": other_job, "application_id": "app-2"}
    assert duplicate_signals("new@example.com", None, None, [same_job], company, job_id=job).status == "passed"
    assert duplicate_signals("X@EXAMPLE.COM", None, None, [same_job], company, job_id=job).status == "needs_review"
    assert duplicate_signals(None, "9876543210", None, [same_job], company, job_id=job, phone_region="IN").status == "needs_review"
    assert duplicate_signals(None, None, "ABC", [same_job], company, job_id=job).status == "needs_review"
    assert duplicate_signals("x@example.com", None, None, [other_job_row], company, scope="job", job_id=job).status == "not_verified"
    assert duplicate_signals("x@example.com", None, None, [other_job_row], company, scope="company", job_id=job).status == "needs_review"
    assert duplicate_signals(None, None, None, [same_job], company, job_id=job).status == "not_verified"
    for email in (None, "missing@example.com", "x@example.com"):
        assert duplicate_signals(email, None, None, [same_job], company, job_id=job).status != "failed"


def _public_resolver(host, port):
    return ["93.184.216.34"]


async def _url_check(handler, *, url="https://example.com/profile", resolver=_public_resolver, check_type="portfolio_url"):
    transport = httpx.MockTransport(handler)
    return await url_reachability_check(url, timeout=0.1, check_type=check_type, enabled=True, transport=transport, resolver=resolver)


@pytest.mark.asyncio
async def test_reachable_same_host_url_passes_and_sends_no_cookies_or_auth():
    def handler(request):
        assert "cookie" not in request.headers
        assert "authorization" not in request.headers
        return httpx.Response(200)

    result = await _url_check(handler)
    assert result.status == "passed"
    assert "proves nothing about skills or employment" in result.signal


@pytest.mark.asyncio
async def test_cross_host_redirect_needs_review_without_following_target():
    def handler(request):
        return httpx.Response(302, headers={"location": "https://other.example/profile"})

    result = await _url_check(handler)
    assert result.status == "needs_review"
    assert result.details["reason_code"] == "url_redirect_different_host"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "reason"),
    [(404, "url_not_found"), (403, "url_forbidden"), (503, "url_server_error")],
    ids=["not-found", "forbidden", "server-error"],
)
async def test_url_http_error_statuses_need_review(status_code, reason):
    result = await _url_check(lambda request: httpx.Response(status_code))
    assert result.status == "needs_review"
    assert result.details["reason_code"] == reason


@pytest.mark.asyncio
async def test_url_timeout_and_dns_failure_are_not_verified():
    async def timeout_handler(request):
        raise httpx.ConnectTimeout("mocked timeout")

    timed_out = await _url_check(timeout_handler)

    def failed_dns(host, port):
        raise socket.gaierror("mocked DNS failure")

    dns = await _url_check(lambda request: httpx.Response(200), resolver=failed_dns)
    assert timed_out.status == dns.status == "not_verified"
    assert timed_out.details["reason_code"] == "timeout"
    assert dns.details["reason_code"] == "dns_failure"


@pytest.mark.asyncio
async def test_url_reachability_disabled_and_absent_are_not_verified():
    disabled = await url_reachability_check("https://example.com", enabled=False, resolver=_public_resolver,
                                             transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    absent = await url_reachability_check(None, enabled=True)
    assert disabled.status == absent.status == "not_verified"


@pytest.mark.parametrize(
    "url",
    [
        "not a url",
        "ftp://example.com/file",
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.1.2/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://[fd00:ec2::254]/",
    ],
    ids=["malformed", "non-http", "loopback-v4", "private-v4", "link-local-v4", "metadata-v4", "loopback-v6", "link-local-v6", "metadata-v6"],
)
def test_malformed_non_http_and_ssrf_addresses_fail(url):
    result = portfolio_url_check(url)
    assert result.status == "failed"
    if "127." in url or "10." in url or "169." in url or "::" in url or "fe80" in url or "fd00" in url:
        assert result.details["reason_code"] == "ssrf_blocked"


@pytest.mark.asyncio
async def test_benign_redirect_chain_and_blocked_second_hop_are_revalidated():
    def benign(request):
        if request.url.path == "/profile":
            return httpx.Response(301, headers={"location": "/canonical"})
        return httpx.Response(200)

    benign_result = await _url_check(benign)
    assert benign_result.status == "passed"
    calls = 0

    def resolver(host, port):
        nonlocal calls
        calls += 1
        return ["93.184.216.34"] if calls == 1 else ["169.254.169.254"]

    blocked_result = await _url_check(
        lambda request: httpx.Response(302, headers={"location": "/redirected"}), resolver=resolver
    )
    assert blocked_result.status == "failed"
    assert blocked_result.details["reason_code"] == "ssrf_blocked"
    assert blocked_result.details["redirect_hop"] == 1


@pytest.mark.asyncio
async def test_redirect_loop_and_more_than_three_hops_need_review():
    def loop(request):
        destination = "/b" if request.url.path == "/a" else "/a"
        return httpx.Response(302, headers={"location": destination})

    loop_result = await _url_check(loop, url="https://example.com/a")
    assert loop_result.status == "needs_review"
    assert loop_result.details["reason_code"] == "url_redirect_loop"

    def long_chain(request):
        hop = int(request.url.path.strip("/") or "0")
        return httpx.Response(302, headers={"location": f"/{hop + 1}"})

    limit_result = await _url_check(long_chain, url="https://example.com/0")
    assert limit_result.status == "needs_review"
    assert limit_result.details["reason_code"] == "url_redirect_limit"


@pytest.mark.asyncio
async def test_head_405_uses_one_get_fallback():
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(405 if request.method == "HEAD" else 200)

    result = await _url_check(handler)
    assert result.status == "passed"
    assert methods == ["HEAD", "GET"]


def test_github_host_and_path_matrix():
    assert github_url_check("https://notgithub.com/alice").status == "failed"
    assert github_url_check("https://github.com/alice").status == "passed"
    assert github_url_check("https://github.com/alice/project").status == "passed"
    wrong = github_url_check("https://github.com/alice/project/issues/1")
    assert wrong.status == "needs_review"
    assert wrong.details["reason_code"] == "wrong_path_shape"


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["passed", "not_verified"], "not_verified"),
        (["passed", "needs_review"], "needs_review"),
        (["not_verified", "failed"], "failed"),
        (["passed"], "passed"),
    ],
)
def test_overall_precedence(statuses, expected):
    rows = [VerificationResultData("test", status, "signal") for status in statuses]
    assert overall_status(rows) == expected


def test_normalization_is_idempotent_and_does_not_mutate_raw_values(caplog):
    raw_email = " Person@Example.com "
    raw_phone = "+91 98765 43210"
    email_once = normalize_email(raw_email)
    phone_once = normalize_phone(raw_phone)
    assert normalize_email(email_once) == email_once
    assert normalize_phone(phone_once) == phone_once
    assert phone_once == normalize_phone("9876543210", "IN") == "+919876543210"
    email_check(raw_email)
    phone_check(raw_phone)
    assert raw_email == " Person@Example.com "
    assert raw_phone == "+91 98765 43210"
    assert raw_email not in caplog.text
    assert raw_phone not in caplog.text


@pytest.mark.asyncio
async def test_verify_response_always_includes_disclaimer(client: httpx.AsyncClient, db_session, company_with_admin, admin_headers):
    company, _ = company_with_admin
    job = Job(company_id=company.id, title="Verification Role", description="Test", employment_type=EmploymentType.FULL_TIME, work_mode=WorkMode.REMOTE)
    db_session.add(job)
    await db_session.flush()
    application = Application(company_id=company.id, job_id=job.id, status="applied")
    db_session.add(application)
    await db_session.flush()

    response = await client.post(f"/api/v1/applications/{application.id}/verify", headers=admin_headers)
    assert response.status_code == 200
    payload = response.json()["data"]
    assert "do not prove identity, employment or skill" in payload["disclaimer"]
