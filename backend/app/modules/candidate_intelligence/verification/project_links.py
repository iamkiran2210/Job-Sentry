"""Project link verification via safe HTML inspection and AI-based consistency checks.

Never follows private/SSRF targets, never forwards credentials, never bypasses
CAPTCHA/anti-bot gates, and never treats public HTML as proof of authorship or skill.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from html.parser import HTMLParser
import inspect
import ipaddress
import logging
import re
import socket
from typing import Any, Awaitable, Callable, Literal
from urllib.parse import urljoin, urlparse

import httpx

from app.ai_features.schemas.analysis import ProjectLinkAIVerdict
from app.modules.candidate_intelligence.evidence.providers import _extract_tokens, _tokens_match
from app.modules.candidate_intelligence.types import VerificationResultData
from app.modules.candidate_intelligence.verification.checks import overall_status

logger = logging.getLogger(__name__)

_MAX_HTML_BYTES = 200_000
_URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>()\"'\]]+", re.IGNORECASE)

_BOT_GATE_MARKERS = (
    "verify you are human",
    "checking your browser before accessing",
    "just a moment...",
    "cf-turnstile",
    "g-recaptcha",
    "h-captcha",
    "attention required! | cloudflare",
    "enable javascript and cookies to continue",
    "access denied | cloudflare",
)

_ERROR_OR_PARKED_MARKERS = (
    "404 not found",
    "page not found",
    "repository not found",
    "this page could not be found",
    "domain is for sale",
    "buy this domain",
    "this domain is parked",
    "parked free, courtesy of",
    "site not found",
    "deployment not found",
    "there isn't a github pages site here",
)


@dataclass(frozen=True)
class HtmlSummary:
    title: str
    og_title: str
    meta_description: str
    headings: tuple[str, ...]
    visible_text: str
    excerpt: str
    bot_gated: bool
    parked_or_error: bool


class _SafeHTMLTextExtractor(HTMLParser):
    _SKIP_TAGS = frozenset({"script", "style", "noscript", "svg", "template"})
    _HEADING_TAGS = frozenset({"h1", "h2", "h3"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._heading_tag: str | None = None
        self._title_parts: list[str] = []
        self._heading_parts: list[str] = []
        self._text_parts: list[str] = []
        self.og_title: str = ""
        self.meta_description: str = ""
        self.headings: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower = tag.casefold()
        if lower in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return
        if lower == "title":
            self._in_title = True
        elif lower in self._HEADING_TAGS:
            self._heading_tag = lower
            self._heading_parts = []
        elif lower == "meta":
            attr_map = {k.casefold(): (v or "").strip() for k, v in attrs if k}
            name = attr_map.get("name", "").casefold()
            prop = attr_map.get("property", "").casefold()
            content = attr_map.get("content", "")
            if content:
                if name == "description" and not self.meta_description:
                    self.meta_description = content[:400]
                elif prop == "og:description" and not self.meta_description:
                    self.meta_description = content[:400]
                elif prop == "og:title" and not self.og_title:
                    self.og_title = content[:300]

    def handle_endtag(self, tag: str) -> None:
        lower = tag.casefold()
        if lower in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if lower == "title":
            self._in_title = False
        elif lower == self._heading_tag:
            heading = re.sub(r"\s+", " ", " ".join(self._heading_parts)).strip()
            if heading and len(self.headings) < 10:
                self.headings.append(heading[:200])
            self._heading_tag = None
            self._heading_parts = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        stripped = data.strip()
        if not stripped:
            return
        if self._in_title:
            self._title_parts.append(stripped)
        if self._heading_tag:
            self._heading_parts.append(stripped)
        if len(self._text_parts) < 500:
            self._text_parts.append(stripped)

    @property
    def title(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._title_parts)).strip()[:300]

    @property
    def visible_text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._text_parts)).strip()[:4000]


def extract_html_summary(html_text: str) -> HtmlSummary:
    parser = _SafeHTMLTextExtractor()
    try:
        parser.feed(html_text[:_MAX_HTML_BYTES])
        parser.close()
    except Exception:
        pass
    title = parser.title
    og_title = parser.og_title
    meta_desc = parser.meta_description
    visible_text = parser.visible_text
    excerpt = (meta_desc or visible_text)[:260]
    combined_lower = f"{title}\n{og_title}\n{visible_text[:1500]}".casefold()
    raw_lower = html_text[:40_000].casefold()
    bot_gated = any(marker in combined_lower or marker in raw_lower for marker in _BOT_GATE_MARKERS)
    parked_or_error = any(marker in combined_lower for marker in _ERROR_OR_PARKED_MARKERS)
    return HtmlSummary(
        title=title,
        og_title=og_title,
        meta_description=meta_desc,
        headings=tuple(parser.headings),
        visible_text=visible_text,
        excerpt=excerpt,
        bot_gated=bot_gated,
        parked_or_error=parked_or_error,
    )


def _normalize_project_url(raw: str | None) -> str | None:
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.strip().rstrip(".,;)")
    if not cleaned:
        return None
    if re.match(r"^(?:www\.|github\.com/|gitlab\.com/|bitbucket\.org/)", cleaned, re.IGNORECASE):
        cleaned = "https://" + cleaned
    return cleaned


def _validate_public_url(url: str) -> tuple[bool, str | None]:
    try:
        parsed = urlparse(url)
        _ = parsed.port
    except ValueError:
        return False, "invalid_authority"
    if len(url) > 2048:
        return False, "url_too_long"
    if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
    ):
        return False, "invalid_url"
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        if not ip.is_global:
            return False, "ssrf_blocked"
    except ValueError:
        pass
    return True, None


async def _resolve_and_check_global(hostname: str, port: int, timeout: float, resolver=None) -> tuple[bool, str | None]:
    try:
        if resolver is None:
            infos = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(hostname, port, type=socket.SOCK_STREAM),
                timeout=timeout,
            )
            addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
        else:
            resolved = resolver(hostname, port)
            if inspect.isawaitable(resolved):
                resolved = await asyncio.wait_for(resolved, timeout=timeout)
            addresses = {ipaddress.ip_address(address) for address in resolved}
        if not addresses or any(not addr.is_global for addr in addresses):
            return False, "ssrf_blocked"
        return True, None
    except asyncio.TimeoutError:
        return False, "timeout"
    except socket.gaierror:
        return False, "dns_failure"
    except OSError:
        return False, "network_unavailable"


async def fetch_project_html(
        url: str,
        *,
        timeout: float = 5.0,
        transport=None,
        resolver=None,
) -> dict[str, Any]:
    """Safely fetch a public project URL's HTML with SSRF checks on every hop."""
    ok, err_code = _validate_public_url(url)
    if not ok:
        return {"ok": False, "status": "failed", "reason_code": err_code, "final_url": url}

    current = url
    seen: set[str] = set()
    try:
        async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=False, transport=transport, trust_env=False
        ) as client:
            for hop in range(4):
                parsed = urlparse(current)
                key = current.split("#", 1)[0]
                if key in seen:
                    return {
                        "ok": False,
                        "status": "needs_review",
                        "reason_code": "url_redirect_loop",
                        "final_url": current,
                    }
                seen.add(key)

                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                dns_ok, dns_err = await _resolve_and_check_global(
                    parsed.hostname or "", port, timeout, resolver=resolver
                )
                if not dns_ok:
                    return {
                        "ok": False,
                        "status": "failed" if dns_err == "ssrf_blocked" else "not_verified",
                        "reason_code": dns_err,
                        "final_url": current,
                    }

                headers = {
                    "User-Agent": "Job-Sentry-verification/1.0",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                }
                req = client.build_request("GET", current, headers=headers)
                req.headers.pop("cookie", None)
                req.headers.pop("authorization", None)
                resp = await client.send(req, follow_redirects=False)
                client.cookies.clear()

                status_code = resp.status_code
                location = resp.headers.get("location")
                if status_code in {301, 302, 303, 307, 308}:
                    if not location:
                        return {
                            "ok": False,
                            "status": "needs_review",
                            "reason_code": "invalid_redirect",
                            "http_status": status_code,
                            "final_url": current,
                        }
                    if hop == 3:
                        return {
                            "ok": False,
                            "status": "needs_review",
                            "reason_code": "url_redirect_limit",
                            "http_status": status_code,
                            "final_url": current,
                        }
                    next_url = urljoin(current, location)
                    next_ok, next_err = _validate_public_url(next_url)
                    if not next_ok:
                        return {
                            "ok": False,
                            "status": "failed" if next_err == "ssrf_blocked" else "needs_review",
                            "reason_code": next_err,
                            "http_status": status_code,
                            "final_url": next_url,
                        }
                    next_parsed = urlparse(next_url)
                    if parsed.scheme == "https" and next_parsed.scheme != "https":
                        return {
                            "ok": False,
                            "status": "needs_review",
                            "reason_code": "url_redirect_downgrade",
                            "http_status": status_code,
                            "final_url": next_url,
                        }
                    current = next_url
                    continue

                raw_bytes = resp.content[:_MAX_HTML_BYTES]
                encoding = resp.encoding or "utf-8"
                body_text = raw_bytes.decode(encoding, errors="replace")
                content_type = resp.headers.get("content-type", "")
                html_summary = extract_html_summary(body_text)

                if status_code == 404:
                    return {
                        "ok": False,
                        "status": "needs_review",
                        "reason_code": "url_not_found",
                        "http_status": status_code,
                        "final_url": current,
                        "content_type": content_type,
                        "html": html_summary,
                    }
                if status_code == 403 or html_summary.bot_gated:
                    return {
                        "ok": False,
                        "status": "needs_review",
                        "reason_code": "bot_or_access_gated",
                        "http_status": status_code,
                        "final_url": current,
                        "content_type": content_type,
                        "html": html_summary,
                    }
                if status_code >= 500:
                    return {
                        "ok": False,
                        "status": "needs_review",
                        "reason_code": "url_server_error",
                        "http_status": status_code,
                        "final_url": current,
                        "content_type": content_type,
                        "html": html_summary,
                    }
                if status_code >= 400:
                    return {
                        "ok": False,
                        "status": "needs_review",
                        "reason_code": "url_http_error",
                        "http_status": status_code,
                        "final_url": current,
                        "content_type": content_type,
                        "html": html_summary,
                    }

                return {
                    "ok": True,
                    "status": "passed",
                    "reason_code": "html_fetched",
                    "http_status": status_code,
                    "final_url": current,
                    "content_type": content_type,
                    "html": html_summary,
                }
    except (asyncio.TimeoutError, httpx.TimeoutException):
        return {
            "ok": False,
            "status": "not_verified",
            "reason_code": "timeout",
            "final_url": current,
        }
    except (OSError, httpx.HTTPError):
        return {
            "ok": False,
            "status": "not_verified",
            "reason_code": "network_unavailable",
            "final_url": current,
        }
    return {
        "ok": False,
        "status": "not_verified",
        "reason_code": "network_unavailable",
        "final_url": current,
    }


def _heuristic_project_html_check(
        project: dict[str, Any], html: HtmlSummary, final_url: str
) -> ProjectLinkAIVerdict:
    if html.parked_or_error:
        return ProjectLinkAIVerdict(
            verdict="parked_or_error",
            relevance_score=0.0,
            matched_claims=[],
            discrepancies=["HTML output indicates a 404, missing repository, or parked domain page."],
            summary="Page HTML appears to be an error, missing repository, or parked domain.",
        )

    html_corpus = " ".join(
        part
        for part in (
            html.title,
            html.og_title,
            html.meta_description,
            " ".join(html.headings),
            html.visible_text,
        )
        if part
    )
    html_tokens = set(_extract_tokens(html_corpus, drop_stopwords=True))
    content_length = len(html.title) + len(html.meta_description) + len(html.visible_text)

    if content_length < 30:
        return ProjectLinkAIVerdict(
            verdict="insufficient_content",
            relevance_score=0.2,
            matched_claims=[],
            discrepancies=["HTML response contained minimal visible text (possibly a client-rendered SPA)."],
            summary="Reachable URL, but HTML output contains too little static text to verify project claims.",
        )

    name = str(project.get("name") or "").strip()
    description = str(project.get("description") or "").strip()
    techs = [str(t).strip() for t in (project.get("technologies") or []) if str(t).strip()]

    name_tokens = list(dict.fromkeys(_extract_tokens(name, drop_stopwords=True)))
    desc_tokens = list(dict.fromkeys(_extract_tokens(description, drop_stopwords=True)))

    matched_claims: list[str] = []
    discrepancies: list[str] = []

    name_hits = [t for t in name_tokens if _tokens_match(t, html_tokens)]
    if name_hits:
        matched_claims.append(f"title/name: {', '.join(name_hits[:4])}")
    elif name_tokens:
        discrepancies.append(f"Project name '{name}' not found in HTML output.")

    matched_techs = []
    missing_techs = []
    for tech in techs:
        t_toks = _extract_tokens(tech, drop_stopwords=False)
        if t_toks and any(_tokens_match(tok, html_tokens) for tok in t_toks):
            matched_techs.append(tech)
        else:
            missing_techs.append(tech)
    if matched_techs:
        matched_claims.extend(f"tech: {t}" for t in matched_techs[:6])
    if missing_techs and not matched_techs and techs:
        discrepancies.append(f"Claimed technologies ({', '.join(missing_techs[:4])}) not seen in HTML.")

    desc_hits = [t for t in desc_tokens if _tokens_match(t, html_tokens)]
    if desc_hits:
        matched_claims.append(f"keywords: {', '.join(desc_hits[:5])}")

    # Weighted relevance computation
    components: list[tuple[float, float]] = []
    if name_tokens:
        components.append((0.45, len(name_hits) / len(name_tokens)))
    if techs:
        components.append((0.30, len(matched_techs) / len(techs)))
    if desc_tokens:
        components.append((0.25, min(1.0, len(desc_hits) / max(1, min(len(desc_tokens), 6)))))

    if components:
        total_w = sum(w for w, _ in components)
        score = sum(w * val for w, val in components) / total_w
    else:
        score = 0.5 if content_length >= 80 else 0.2
    score = round(max(0.0, min(1.0, score)), 3)

    if score >= 0.45 or (name_hits and matched_techs):
        verdict: Literal[
            "consistent",
            "partially_consistent",
            "inconsistent",
            "parked_or_error",
            "insufficient_content",
        ] = "consistent"
        summary = (
            f"HTML output aligns with claimed project '{name or 'project'}' "
            f"(page title: '{html.title[:80] or 'untitled'}')."
        )
    elif score >= 0.15 or matched_claims:
        verdict = "partially_consistent"
        summary = (
            f"HTML output partially matches '{name or 'project'}'; "
            "some claimed details were not directly visible in static HTML."
        )
    else:
        verdict = "inconsistent"
        discrepancies.append("HTML page content does not appear to match the claimed project.")
        summary = (
            f"HTML page ('{html.title[:80] or final_url}') does not match the claimed project details."
        )

    return ProjectLinkAIVerdict(
        verdict=verdict,
        relevance_score=score,
        matched_claims=matched_claims[:12],
        discrepancies=discrepancies[:8],
        summary=summary[:320],
    )


async def _run_ai_project_html_check(
        project: dict[str, Any], html: HtmlSummary, final_url: str, *, timeout: float = 25.0
) -> tuple[ProjectLinkAIVerdict, str]:
    """Run structured AI verification via task-specific engine (DSPy ChainOfThought in auto mode, Pydantic AI fallback)."""
    try:
        from app.ai_features.ai.settings import get_ai_settings
        from app.ai_features.ai.tasks import get_extractor

        ai_settings = get_ai_settings()
        if ai_settings.model in {"heuristic", "test"} or not ai_settings.model:
            return _heuristic_project_html_check(project, html, final_url), "heuristic"

        payload = (
            "<untrusted_claim>\n"
            f"Project name: {project.get('name') or ''}\n"
            f"Role: {project.get('role') or ''}\n"
            f"Technologies: {', '.join(str(t) for t in (project.get('technologies') or []))}\n"
            f"Description: {str(project.get('description') or '')[:800]}\n"
            "</untrusted_claim>\n\n"
            "<untrusted_html>\n"
            f"URL: {final_url}\n"
            f"Title: {html.title}\n"
            f"OG Title: {html.og_title}\n"
            f"Meta Description: {html.meta_description}\n"
            f"Headings: {' | '.join(html.headings)}\n"
            f"Visible Text Excerpt: {html.visible_text[:2500]}\n"
            "</untrusted_html>"
        )
        extractor = get_extractor("project_link_verification")
        run = await asyncio.wait_for(extractor.run(payload), timeout=timeout)
        return run.output, f"{run.engine}:{ai_settings.model}"
    except Exception as exc:
        logger.info(
            "Project link AI check fell back to heuristic analyzer",
            extra={"error_type": type(exc).__name__},
        )
        return _heuristic_project_html_check(project, html, final_url), "heuristic_fallback"


def _status_from_verdict(verdict: str) -> str:
    if verdict == "consistent":
        return "passed"
    if verdict == "parked_or_error":
        return "failed"
    return "needs_review"


async def verify_project_links(
        projects: list[dict[str, Any]] | None,
        *,
        enabled: bool = True,
        ai_enabled: bool = True,
        timeout: float = 5.0,
        max_links: int = 5,
        transport=None,
        resolver=None,
        ai_analyzer: Callable[[dict[str, Any], HtmlSummary, str], Awaitable[
                                                                      ProjectLinkAIVerdict] | ProjectLinkAIVerdict] | None = None,
) -> VerificationResultData:
    """Verify project URLs via bounded HTML fetch + AI consistency checks."""
    if not enabled:
        return VerificationResultData(
            "project_links",
            "not_verified",
            "Project link verification is disabled",
            {"reason_code": "check_disabled", "projects": []},
        )

    candidates: list[tuple[dict[str, Any], str]] = []
    seen_urls: set[str] = set()
    for proj in projects or []:
        if not isinstance(proj, dict):
            continue
        raw_url = _normalize_project_url(proj.get("url"))
        if not raw_url:
            desc = str(proj.get("description") or "")
            found = _URL_IN_TEXT_RE.search(desc)
            if found:
                raw_url = _normalize_project_url(found.group(0))
        if raw_url and raw_url not in seen_urls:
            seen_urls.add(raw_url)
            candidates.append((proj, raw_url))
            if len(candidates) >= max_links:
                break

    if not candidates:
        return VerificationResultData(
            "project_links",
            "not_verified",
            "No project links provided in candidate profile",
            {"reason_code": "missing_value", "projects": []},
        )

    async def inspect_one(proj: dict[str, Any], url: str) -> tuple[dict[str, Any], str]:
        project_name = str(proj.get("name") or "Unnamed project")
        fetched = await fetch_project_html(
            url, timeout=timeout, transport=transport, resolver=resolver
        )
        html: HtmlSummary | None = fetched.get("html")
        entry: dict[str, Any] = {
            "project_name": project_name,
            "url": url,
            "final_url": fetched.get("final_url", url),
            "http_status": fetched.get("http_status"),
            "reason_code": fetched.get("reason_code"),
            "html_title": html.title if html else None,
            "html_meta_description": html.meta_description if html else None,
            "html_headings": list(html.headings[:5]) if html else [],
            "html_excerpt": html.excerpt if html else None,
        }
        if not fetched.get("ok") or html is None:
            status = fetched.get("status", "not_verified")
            entry["status"] = status
            entry["ai_verdict"] = "parked_or_error" if fetched.get("reason_code") == "url_not_found" else None
            entry["ai_relevance_score"] = None
            entry["ai_summary"] = (
                "Page access was gated by bot protection or HTTP 403; manual review recommended."
                if fetched.get("reason_code") == "bot_or_access_gated"
                else f"Could not inspect HTML output ({fetched.get('reason_code', 'unavailable')})."
            )
            entry["matched_claims"] = []
            entry["discrepancies"] = [entry["ai_summary"]]
            entry["analysis_mode"] = "http_only"
            return entry, status

        if ai_analyzer is not None:
            verdict_res = ai_analyzer(proj, html, fetched["final_url"])
            verdict = await verdict_res if inspect.isawaitable(verdict_res) else verdict_res
            mode = "custom_ai"
        elif ai_enabled:
            verdict, mode = await _run_ai_project_html_check(proj, html, fetched["final_url"])
        else:
            verdict = _heuristic_project_html_check(proj, html, fetched["final_url"])
            mode = "heuristic"

        status = _status_from_verdict(verdict.verdict)
        entry.update(
            {
                "status": status,
                "ai_verdict": verdict.verdict,
                "ai_relevance_score": verdict.relevance_score,
                "ai_summary": verdict.summary,
                "matched_claims": list(verdict.matched_claims),
                "discrepancies": list(verdict.discrepancies),
                "analysis_mode": mode,
            }
        )
        return entry, status

    results = await asyncio.gather(*(inspect_one(proj, url) for proj, url in candidates))
    project_entries = [item[0] for item in results]
    statuses = [VerificationResultData("project_links", item[1], "") for item in results]
    agg_status = overall_status(statuses)
    passed_count = sum(1 for item in results if item[1] == "passed")
    total_count = len(results)

    if agg_status == "passed":
        signal = (
            f"All {total_count} project link(s) returned HTML consistent with candidate claims; "
            "HTML & AI checks do not prove authorship or skill."
        )
    elif agg_status == "failed":
        signal = (
            f"{passed_count}/{total_count} project link(s) matched; one or more links are invalid, "
            "blocked, or point to an error/parked page."
        )
    elif agg_status == "needs_review":
        signal = (
            f"{passed_count}/{total_count} project link(s) consistent; "
            "remaining link(s) require manual review."
        )
    else:
        signal = (
            f"Checked {total_count} project link(s), but HTML output could not be retrieved."
        )

    return VerificationResultData(
        "project_links",
        agg_status,
        signal,
        {
            "total_links": total_count,
            "consistent_links": passed_count,
            "projects": project_entries,
        },
    )
