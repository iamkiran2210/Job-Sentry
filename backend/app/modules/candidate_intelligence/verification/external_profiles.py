"""GitHub profile (projects, languages, activity) and AI-based portfolio verification.

Never forwards credentials or cookies, never follows SSRF/private targets, never bypasses
bot/CAPTCHA walls, and never treats public metadata as proof of identity, authorship, or skill.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
from typing import Any, Awaitable, Callable, Literal
from urllib.parse import urlparse

import httpx

from app.ai_features.schemas.analysis import (
    GitHubProfileAIVerdict,
    LinkedInProfileAIVerdict,
    PortfolioAIVerdict,
)
from app.modules.candidate_intelligence.evidence.providers import _extract_tokens, _tokens_match
from app.modules.candidate_intelligence.types import VerificationResultData
from app.modules.candidate_intelligence.verification.checks import github_url_check
from app.modules.candidate_intelligence.verification.project_links import (
    HtmlSummary,
    _normalize_project_url,
    fetch_project_html,
)

logger = logging.getLogger(__name__)


def _extract_github_username(
        github_url: str | None, projects: list[dict[str, Any]] | None = None
) -> tuple[str | None, str | None]:
    """Return (username, source_url) from contact.github_url or fallback project GitHub URL."""
    candidates: list[str] = []
    norm_primary = _normalize_project_url(github_url)
    if norm_primary:
        candidates.append(norm_primary)
    for proj in projects or []:
        if isinstance(proj, dict):
            norm_p = _normalize_project_url(proj.get("url"))
            if norm_p and "github.com" in norm_p.casefold():
                candidates.append(norm_p)
    for url in candidates:
        check = github_url_check(url)
        if check.status == "passed" and check.details.get("username"):
            return str(check.details["username"]), url
    return None, norm_primary


def _extract_profile_claims(profile: dict[str, Any] | None) -> dict[str, Any]:
    """Extract only job-relevant non-PII profile claims (never email/phone/protected attributes)."""
    profile = profile or {}
    skills: list[str] = []
    for item in profile.get("skills") or []:
        name = item.get("name") if isinstance(item, dict) else item
        if name and str(name).strip():
            skills.append(str(name).strip())

    projects: list[dict[str, Any]] = []
    for item in profile.get("projects") or []:
        if isinstance(item, dict) and (item.get("name") or item.get("description")):
            projects.append(
                {
                    "name": str(item.get("name") or "").strip(),
                    "description": str(item.get("description") or "").strip()[:300],
                    "technologies": [
                        str(t).strip() for t in (item.get("technologies") or []) if str(t).strip()
                    ][:12],
                }
            )

    roles: list[str] = []
    for item in profile.get("employment") or []:
        if isinstance(item, dict) and item.get("title"):
            roles.append(str(item["title"]).strip())

    summary = str(profile.get("summary") or "").strip()[:400]
    return {
        "skills": skills[:40],
        "projects": projects[:15],
        "roles": roles[:10],
        "summary": summary,
    }


def _heuristic_github_assessment(
        claims: dict[str, Any], gh_snapshot: dict[str, Any]
) -> GitHubProfileAIVerdict:
    repos = gh_snapshot.get("top_repositories") or []
    languages = gh_snapshot.get("languages") or []
    original_repos = int(gh_snapshot.get("original_repos") or 0)
    public_repos = int(gh_snapshot.get("public_repos") or len(repos))

    if public_repos == 0 and not repos:
        return GitHubProfileAIVerdict(
            verdict="sparse_profile",
            alignment_score=0.1,
            verified_languages=[],
            verified_projects=[],
            discrepancies=["GitHub profile has no public repositories available for inspection."],
            summary="GitHub account exists but has no public repositories to assess profile claims.",
        )

    gh_corpus_parts = [
        str(gh_snapshot.get("bio") or ""),
        *(str(lang.get("name") or "") for lang in languages),
    ]
    for r in repos:
        gh_corpus_parts.extend(
            [
                str(r.get("name") or "").replace("-", " ").replace("_", " "),
                str(r.get("description") or ""),
                str(r.get("language") or ""),
                " ".join(str(t) for t in (r.get("topics") or [])),
            ]
        )
    gh_tokens = set(_extract_tokens(" ".join(gh_corpus_parts), drop_stopwords=True))
    gh_lang_tokens = set(
        _extract_tokens(" ".join(str(l.get("name") or "") for l in languages), drop_stopwords=False)
    )

    verified_languages: list[str] = []
    unmatched_skills: list[str] = []
    for skill in claims["skills"]:
        toks = _extract_tokens(skill, drop_stopwords=False)
        if toks and any(_tokens_match(t, gh_tokens | gh_lang_tokens) for t in toks):
            if skill not in verified_languages:
                verified_languages.append(skill)
        else:
            unmatched_skills.append(skill)

    verified_projects: list[str] = []
    repo_text_list = [
        f"{str(r.get('name') or '').replace('-', ' ').replace('_', ' ')} {r.get('description') or ''}"
        for r in repos
    ]
    for proj in claims["projects"]:
        pname = proj.get("name") or ""
        ptoks = list(dict.fromkeys(_extract_tokens(pname, drop_stopwords=True)))
        if not ptoks:
            continue
        for rtext in repo_text_list:
            rtoks = set(_extract_tokens(rtext, drop_stopwords=True))
            hits = sum(1 for t in ptoks if _tokens_match(t, rtoks))
            if hits / len(ptoks) >= 0.5:
                verified_projects.append(pname)
                break

    discrepancies: list[str] = []
    if original_repos == 0 and public_repos > 0:
        discrepancies.append("All inspected public repositories are forks with no original repos.")

    skill_ratio = (
        len(verified_languages) / max(1, min(len(claims["skills"]), 6))
        if claims["skills"]
        else (0.6 if languages else 0.2)
    )
    proj_ratio = (
        len(verified_projects) / max(1, len(claims["projects"]))
        if claims["projects"]
        else (0.6 if original_repos > 0 else 0.2)
    )
    orig_ratio = min(1.0, original_repos / 3.0) if public_repos > 0 else 0.0

    score = round(
        max(0.0, min(1.0, 0.50 * skill_ratio + 0.30 * proj_ratio + 0.20 * orig_ratio)), 3
    )

    if not verified_languages and claims["skills"]:
        discrepancies.append(
            f"Claimed skills ({', '.join(unmatched_skills[:5])}) were not observed in public GitHub languages or repo metadata."
        )
    if claims["projects"] and not verified_projects:
        discrepancies.append(
            "None of the resume's named projects directly matched public GitHub repository names."
        )

    if original_repos == 0 and not verified_languages:
        verdict: Literal["consistent", "partially_consistent", "inconsistent", "sparse_profile"] = (
            "inconsistent"
        )
        summary = (
            f"GitHub @{gh_snapshot.get('username')} shows only forked/unrelated repos and lacks "
            "evidence of the candidate's claimed technical stack."
        )
    elif score >= 0.45 and (verified_languages or verified_projects):
        verdict = "consistent"
        top_langs = ", ".join(str(l["name"]) for l in languages[:4]) or "multiple languages"
        summary = (
            f"GitHub @{gh_snapshot.get('username')} ({original_repos} original public repo(s), "
            f"languages: {top_langs}) aligns with candidate profile claims."
        )
    elif score >= 0.20 or verified_languages or verified_projects:
        verdict = "partially_consistent"
        summary = (
            f"GitHub @{gh_snapshot.get('username')} partially aligns with resume claims; "
            "some claimed skills or projects are not reflected in public repositories."
        )
    else:
        verdict = "inconsistent"
        summary = (
            f"Public GitHub activity for @{gh_snapshot.get('username')} shows minimal alignment "
            "with the candidate's claimed skills and projects."
        )

    return GitHubProfileAIVerdict(
        verdict=verdict,
        alignment_score=score,
        verified_languages=verified_languages[:15],
        verified_projects=verified_projects[:10],
        discrepancies=discrepancies[:8],
        summary=summary[:320],
    )


async def _run_ai_github_assessment(
        claims: dict[str, Any], gh_snapshot: dict[str, Any], *, timeout: float = 25.0
) -> tuple[GitHubProfileAIVerdict, str]:
    try:
        from app.ai_features.ai.settings import get_ai_settings
        from app.ai_features.ai.tasks import get_extractor

        ai_settings = get_ai_settings()
        if ai_settings.model in {"heuristic", "test"} or not ai_settings.model:
            return _heuristic_github_assessment(claims, gh_snapshot), "heuristic"

        repos_text = "\n".join(
            f"- {r['name']} (lang={r.get('language')}, stars={r.get('stars')}, fork={r.get('is_fork')}, "
            f"topics={','.join(r.get('topics') or [])}): {r.get('description') or ''}"
            for r in (gh_snapshot.get("top_repositories") or [])[:12]
        )
        langs_text = ", ".join(
            f"{l['name']} ({l.get('share_pct', 0)}%)" for l in (gh_snapshot.get("languages") or [])[:10]
        )
        payload = (
            "<untrusted_resume>\n"
            f"Skills: {', '.join(claims['skills'])}\n"
            f"Roles: {', '.join(claims['roles'])}\n"
            f"Projects: {', '.join(p['name'] for p in claims['projects'])}\n"
            "</untrusted_resume>\n\n"
            "<untrusted_github>\n"
            f"Username: {gh_snapshot.get('username')}\n"
            f"Public repos: {gh_snapshot.get('public_repos')} (original: {gh_snapshot.get('original_repos')}, forks: {gh_snapshot.get('forked_repos')})\n"
            f"Total stars: {gh_snapshot.get('total_stars')}\n"
            f"Languages: {langs_text}\n"
            f"Bio: {gh_snapshot.get('bio') or ''}\n"
            f"Repositories:\n{repos_text}\n"
            "</untrusted_github>"
        )
        extractor = get_extractor("github_profile_verification")
        run = await asyncio.wait_for(extractor.run(payload), timeout=timeout)
        return run.output, f"{run.engine}:{ai_settings.model}"
    except Exception as exc:
        logger.info(
            "GitHub profile AI assessment fell back to heuristic",
            extra={"error_type": type(exc).__name__},
        )
        return _heuristic_github_assessment(claims, gh_snapshot), "heuristic_fallback"


async def verify_github_profile(
        github_url: str | None,
        profile: dict[str, Any] | None,
        *,
        enabled: bool = True,
        ai_enabled: bool = True,
        timeout: float = 5.0,
        max_repositories: int = 15,
        client: httpx.AsyncClient | None = None,
        transport=None,
        ai_analyzer: Callable[
                         [dict[str, Any], dict[str, Any]], Awaitable[GitHubProfileAIVerdict] | GitHubProfileAIVerdict
                     ]
                     | None = None,
) -> VerificationResultData:
    """Inspect a candidate's public GitHub profile, repos, and used languages to assess claims."""
    if not enabled:
        return VerificationResultData(
            "github_profile",
            "not_verified",
            "GitHub profile verification is disabled",
            {"reason_code": "check_disabled"},
        )

    projects = (profile or {}).get("projects") or []
    username, source_url = _extract_github_username(github_url, projects)
    if not username:
        if source_url:
            base = github_url_check(source_url)
            return VerificationResultData(
                "github_profile",
                base.status,
                base.signal,
                {**base.details, "url": source_url},
            )
        return VerificationResultData(
            "github_profile",
            "not_verified",
            "No GitHub profile or repository URL provided",
            {"reason_code": "missing_value"},
        )

    owned = client is None
    gh_headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Job-Sentry-verification/1.0",
    }
    gh_token = (os.getenv("GITHUB_TOKEN") or "").strip()
    if gh_token:
        # Sent exclusively to api.github.com by this dedicated client (never to candidate URLs).
        gh_headers["Authorization"] = f"Bearer {gh_token}"
    session = client or httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        transport=transport,
        trust_env=False,
        headers=gh_headers,
    )
    try:
        user_resp = await session.get(f"https://api.github.com/users/{username}")
        if user_resp.status_code == 404:
            return VerificationResultData(
                "github_profile",
                "needs_review",
                f"GitHub user '@{username}' was not found",
                {"reason_code": "github_user_not_found", "username": username, "url": source_url},
            )
        if user_resp.status_code in {403, 429}:
            return VerificationResultData(
                "github_profile",
                "not_verified",
                "GitHub API rate limit reached; could not inspect public profile",
                {
                    "reason_code": "github_rate_limited",
                    "http_status": user_resp.status_code,
                    "username": username,
                    "url": source_url,
                },
            )
        user_resp.raise_for_status()
        user_data = user_resp.json() if isinstance(user_resp.json(), dict) else {}

        repos_resp = await session.get(
            f"https://api.github.com/users/{username}/repos",
            params={"per_page": min(max_repositories, 30), "sort": "updated", "type": "owner"},
        )
        repos_raw = (
            repos_resp.json()
            if repos_resp.status_code == 200 and isinstance(repos_resp.json(), list)
            else []
        )

        # Fetch per-repo language bytes for top original repos (capped at 6 to stay gentle on rate limits)
        lang_bytes: dict[str, int] = {}
        lang_repo_counts: dict[str, int] = {}
        original_repos = 0
        forked_repos = 0
        total_stars = 0
        last_active_at: str | None = None
        top_repositories: list[dict[str, Any]] = []

        original_full_names: list[str] = []
        for repo in repos_raw[:max_repositories]:
            if not isinstance(repo, dict):
                continue
            is_fork = bool(repo.get("fork"))
            if is_fork:
                forked_repos += 1
            else:
                original_repos += 1
            stars = int(repo.get("stargazers_count") or 0)
            total_stars += stars
            pushed = repo.get("pushed_at") or repo.get("updated_at")
            if isinstance(pushed, str) and (last_active_at is None or pushed > last_active_at):
                last_active_at = pushed
            primary_lang = repo.get("language")
            if isinstance(primary_lang, str) and primary_lang.strip():
                lang_repo_counts[primary_lang] = lang_repo_counts.get(primary_lang, 0) + 1
                lang_bytes.setdefault(primary_lang, 0)
            full_name = str(repo.get("full_name") or "")
            if not is_fork and re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", full_name):
                original_full_names.append(full_name)
            top_repositories.append(
                {
                    "name": str(repo.get("name") or ""),
                    "full_name": full_name,
                    "url": str(repo.get("html_url") or f"https://github.com/{full_name}"),
                    "description": str(repo.get("description") or "")[:240] or None,
                    "language": primary_lang if isinstance(primary_lang, str) else None,
                    "stars": stars,
                    "forks": int(repo.get("forks_count") or 0),
                    "is_fork": is_fork,
                    "topics": [str(t) for t in (repo.get("topics") or [])][:8],
                    "updated_at": pushed if isinstance(pushed, str) else None,
                }
            )

        async def _fetch_repo_languages(full_name: str) -> dict[str, int]:
            try:
                l_resp = await session.get(f"https://api.github.com/repos/{full_name}/languages")
                if l_resp.status_code == 200 and isinstance(l_resp.json(), dict):
                    return {
                        lang: bcount
                        for lang, bcount in l_resp.json().items()
                        if isinstance(lang, str) and isinstance(bcount, int) and bcount > 0
                    }
            except (httpx.HTTPError, ValueError, asyncio.TimeoutError):
                pass
            return {}

        if original_full_names:
            lang_maps = await asyncio.gather(
                *(_fetch_repo_languages(fn) for fn in original_full_names[:6])
            )
            for lmap in lang_maps:
                for lang, bcount in lmap.items():
                    lang_bytes[lang] = lang_bytes.get(lang, 0) + bcount
                    if lang not in lang_repo_counts:
                        lang_repo_counts[lang] = 1

        total_bytes = sum(lang_bytes.values())
        sorted_langs = sorted(
            lang_bytes.keys(),
            key=lambda l: (-lang_bytes[l], -lang_repo_counts.get(l, 0), l.casefold()),
        )
        languages_summary = [
            {
                "name": lang,
                "bytes": lang_bytes[lang],
                "repo_count": lang_repo_counts.get(lang, 1),
                "share_pct": round((lang_bytes[lang] / total_bytes) * 100.0, 1)
                if total_bytes > 0
                else round(
                    (lang_repo_counts.get(lang, 1) / max(1, sum(lang_repo_counts.values()))) * 100.0,
                    1,
                ),
            }
            for lang in sorted_langs[:12]
        ]

        gh_snapshot = {
            "username": str(user_data.get("login") or username),
            "profile_url": str(user_data.get("html_url") or f"https://github.com/{username}"),
            "bio": str(user_data.get("bio") or "")[:300] or None,
            "public_repos": int(user_data.get("public_repos") or len(repos_raw)),
            "original_repos": original_repos,
            "forked_repos": forked_repos,
            "total_stars": total_stars,
            "followers": int(user_data.get("followers") or 0),
            "account_created_at": user_data.get("created_at"),
            "last_active_at": last_active_at,
            "languages": languages_summary,
            "top_repositories": top_repositories[:8],
        }

        claims = _extract_profile_claims(profile)
        if ai_analyzer is not None:
            verdict_res = ai_analyzer(claims, gh_snapshot)
            verdict = await verdict_res if inspect.isawaitable(verdict_res) else verdict_res
            mode = "custom_ai"
        elif ai_enabled:
            verdict, mode = await _run_ai_github_assessment(claims, gh_snapshot)
        else:
            verdict = _heuristic_github_assessment(claims, gh_snapshot)
            mode = "heuristic"

        status = "passed" if verdict.verdict == "consistent" else "needs_review"
        signal = (
            f"GitHub @{gh_snapshot['username']}: {gh_snapshot['public_repos']} public repo(s), "
            f"{len(languages_summary)} language(s) detected ({verdict.verdict.replace('_', ' ')}); "
            "public metadata does not prove identity or skill."
        )
        return VerificationResultData(
            "github_profile",
            status,
            signal,
            {
                **gh_snapshot,
                "ai_verdict": verdict.verdict,
                "ai_alignment_score": verdict.alignment_score,
                "ai_summary": verdict.summary,
                "verified_languages": list(verdict.verified_languages),
                "verified_projects": list(verdict.verified_projects),
                "discrepancies": list(verdict.discrepancies),
                "analysis_mode": mode,
            },
        )
    except (asyncio.TimeoutError, httpx.TimeoutException):
        return VerificationResultData(
            "github_profile",
            "not_verified",
            "GitHub profile inspection timed out",
            {"reason_code": "timeout", "username": username, "url": source_url},
        )
    except (OSError, httpx.HTTPError, ValueError):
        return VerificationResultData(
            "github_profile",
            "not_verified",
            "GitHub profile could not be fetched",
            {"reason_code": "network_unavailable", "username": username, "url": source_url},
        )
    finally:
        if owned:
            await session.aclose()


def _heuristic_portfolio_assessment(
        claims: dict[str, Any], html: HtmlSummary, final_url: str
) -> PortfolioAIVerdict:
    if html.parked_or_error:
        return PortfolioAIVerdict(
            verdict="parked_or_error",
            alignment_score=0.0,
            matched_skills=[],
            matched_projects=[],
            matched_roles=[],
            discrepancies=["Portfolio URL points to an error, 404, or parked domain page."],
            summary="Portfolio webpage HTML appears to be an error page or parked domain.",
        )

    content_len = len(html.title) + len(html.meta_description) + len(html.visible_text)
    if content_len < 35:
        return PortfolioAIVerdict(
            verdict="insufficient_content",
            alignment_score=0.2,
            matched_skills=[],
            matched_projects=[],
            matched_roles=[],
            discrepancies=["Portfolio HTML contains minimal static text (likely a client-side SPA shell)."],
            summary="Portfolio URL is reachable, but static HTML has too little content to verify claims.",
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

    matched_skills: list[str] = []
    for skill in claims["skills"]:
        toks = _extract_tokens(skill, drop_stopwords=False)
        if toks and any(_tokens_match(t, html_tokens) for t in toks):
            if skill not in matched_skills:
                matched_skills.append(skill)

    matched_projects: list[str] = []
    for proj in claims["projects"]:
        pname = proj.get("name") or ""
        ptoks = list(dict.fromkeys(_extract_tokens(pname, drop_stopwords=True)))
        if ptoks and sum(1 for t in ptoks if _tokens_match(t, html_tokens)) / len(ptoks) >= 0.5:
            matched_projects.append(pname)

    matched_roles: list[str] = []
    for role in claims["roles"]:
        rtoks = list(dict.fromkeys(_extract_tokens(role, drop_stopwords=True)))
        if rtoks and sum(1 for t in rtoks if _tokens_match(t, html_tokens)) / len(rtoks) >= 0.5:
            matched_roles.append(role)

    components: list[tuple[float, float]] = []
    if claims["skills"]:
        components.append((0.45, min(1.0, len(matched_skills) / max(1, min(len(claims["skills"]), 5)))))
    if claims["projects"]:
        components.append((0.30, len(matched_projects) / len(claims["projects"])))
    if claims["roles"]:
        components.append((0.25, min(1.0, len(matched_roles) / max(1, min(len(claims["roles"]), 2)))))

    if components:
        total_w = sum(w for w, _ in components)
        score = sum(w * val for w, val in components) / total_w
    else:
        score = 0.5 if content_len >= 100 else 0.2
    score = round(max(0.0, min(1.0, score)), 3)

    discrepancies: list[str] = []
    if claims["skills"] and not matched_skills:
        discrepancies.append("None of the candidate's claimed skills appeared in portfolio HTML.")
    if claims["projects"] and not matched_projects:
        discrepancies.append("None of the candidate's named projects appeared in portfolio HTML.")

    if score >= 0.40 or (len(matched_skills) >= 2 and (matched_projects or matched_roles)):
        verdict: Literal[
            "consistent",
            "partially_consistent",
            "inconsistent",
            "parked_or_error",
            "insufficient_content",
        ] = "consistent"
        summary = (
            f"Portfolio HTML ('{html.title[:80] or urlparse(final_url).hostname}') "
            "aligns with the candidate's skills, projects, or role history."
        )
    elif score >= 0.15 or matched_skills or matched_projects or matched_roles:
        verdict = "partially_consistent"
        summary = (
            f"Portfolio HTML ('{html.title[:80] or urlparse(final_url).hostname}') "
            "partially aligns with resume claims."
        )
    else:
        verdict = "inconsistent"
        discrepancies.append("Portfolio HTML content does not appear to match the candidate's profile.")
        summary = (
            f"Portfolio HTML ('{html.title[:80] or final_url}') does not match the candidate's claimed background."
        )

    return PortfolioAIVerdict(
        verdict=verdict,
        alignment_score=score,
        matched_skills=matched_skills[:15],
        matched_projects=matched_projects[:10],
        matched_roles=matched_roles[:6],
        discrepancies=discrepancies[:8],
        summary=summary[:320],
    )


async def _run_ai_portfolio_assessment(
        claims: dict[str, Any], html: HtmlSummary, final_url: str, *, timeout: float = 25.0
) -> tuple[PortfolioAIVerdict, str]:
    try:
        from app.ai_features.ai.settings import get_ai_settings
        from app.ai_features.ai.tasks import get_extractor

        ai_settings = get_ai_settings()
        if ai_settings.model in {"heuristic", "test"} or not ai_settings.model:
            return _heuristic_portfolio_assessment(claims, html, final_url), "heuristic"

        payload = (
            "<untrusted_resume>\n"
            f"Skills: {', '.join(claims['skills'])}\n"
            f"Roles: {', '.join(claims['roles'])}\n"
            f"Projects: {', '.join(p['name'] for p in claims['projects'])}\n"
            f"Summary: {claims['summary']}\n"
            "</untrusted_resume>\n\n"
            "<untrusted_html>\n"
            f"URL: {final_url}\n"
            f"Title: {html.title}\n"
            f"OG Title: {html.og_title}\n"
            f"Meta Description: {html.meta_description}\n"
            f"Headings: {' | '.join(html.headings)}\n"
            f"Visible Text Excerpt: {html.visible_text[:2500]}\n"
            "</untrusted_html>"
        )
        extractor = get_extractor("portfolio_ai_verification")
        run = await asyncio.wait_for(extractor.run(payload), timeout=timeout)
        active_model = run.model.split(",")[0] if run.model else ai_settings.model
        return run.output, f"{run.engine}:{active_model}"
    except Exception as exc:
        logger.info(
            "Portfolio AI verification fell back to heuristic",
            extra={"error_type": type(exc).__name__},
        )
        return _heuristic_portfolio_assessment(claims, html, final_url), "heuristic_fallback"


async def verify_portfolio_ai(
        portfolio_url: str | None,
        profile: dict[str, Any] | None,
        *,
        enabled: bool = True,
        ai_enabled: bool = True,
        timeout: float = 5.0,
        transport=None,
        resolver=None,
        ai_analyzer: Callable[
                         [dict[str, Any], HtmlSummary, str], Awaitable[PortfolioAIVerdict] | PortfolioAIVerdict
                     ]
                     | None = None,
) -> VerificationResultData:
    """Verify a candidate's portfolio website via safe HTML inspection + AI consistency check."""
    if not enabled:
        return VerificationResultData(
            "portfolio_ai",
            "not_verified",
            "AI portfolio verification is disabled",
            {"reason_code": "check_disabled"},
        )

    url = _normalize_project_url(portfolio_url)
    if not url:
        return VerificationResultData(
            "portfolio_ai",
            "not_verified",
            "No portfolio URL provided in candidate profile",
            {"reason_code": "missing_value"},
        )

    fetched = await fetch_project_html(url, timeout=timeout, transport=transport, resolver=resolver)
    html: HtmlSummary | None = fetched.get("html")
    base_details: dict[str, Any] = {
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
        summary = (
            "Portfolio access was gated by bot protection or HTTP 403; manual review recommended."
            if fetched.get("reason_code") == "bot_or_access_gated"
            else f"Could not inspect portfolio HTML ({fetched.get('reason_code', 'unavailable')})."
        )
        return VerificationResultData(
            "portfolio_ai",
            status,
            summary,
            {
                **base_details,
                "ai_verdict": "parked_or_error"
                if fetched.get("reason_code") == "url_not_found"
                else None,
                "ai_alignment_score": None,
                "ai_summary": summary,
                "matched_skills": [],
                "matched_projects": [],
                "matched_roles": [],
                "discrepancies": [summary],
                "analysis_mode": "http_only",
            },
        )

    claims = _extract_profile_claims(profile)
    if ai_analyzer is not None:
        verdict_res = ai_analyzer(claims, html, fetched["final_url"])
        verdict = await verdict_res if inspect.isawaitable(verdict_res) else verdict_res
        mode = "custom_ai"
    elif ai_enabled:
        verdict, mode = await _run_ai_portfolio_assessment(claims, html, fetched["final_url"])
    else:
        verdict = _heuristic_portfolio_assessment(claims, html, fetched["final_url"])
        mode = "heuristic"

    status = (
        "passed"
        if verdict.verdict == "consistent"
        else "failed"
        if verdict.verdict == "parked_or_error"
        else "needs_review"
    )
    signal = (
        f"Portfolio AI check: {verdict.verdict.replace('_', ' ')} "
        f"({round(verdict.alignment_score * 100)}% alignment); "
        "public portfolio HTML does not prove identity or skill."
    )
    return VerificationResultData(
        "portfolio_ai",
        status,
        signal,
        {
            **base_details,
            "ai_verdict": verdict.verdict,
            "ai_alignment_score": verdict.alignment_score,
            "ai_summary": verdict.summary,
            "matched_skills": list(verdict.matched_skills),
            "matched_projects": list(verdict.matched_projects),
            "matched_roles": list(verdict.matched_roles),
            "discrepancies": list(verdict.discrepancies),
            "analysis_mode": mode,
        },
    )


# ---------------------------------------------------------------------------
# LinkedIn Profile Verification via Bright Data Python SDK (brightdata-sdk)
# ---------------------------------------------------------------------------

_BRIGHT_DATA_SCRAPE_URL = "https://api.brightdata.com/datasets/v3/scrape"
_BRIGHT_DATA_SNAPSHOT_URL = "https://api.brightdata.com/datasets/v3/snapshot"


def _normalize_linkedin_url(raw: str | None) -> str | None:
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.strip().rstrip(".,;)")
    if not cleaned:
        return None
    if re.match(r"^(?:www\.)?(?:[a-z]{2}\.)?linkedin\.com/", cleaned, re.IGNORECASE):
        cleaned = "https://" + cleaned
    try:
        parsed = urlparse(cleaned)
    except ValueError:
        return None
    host = (parsed.hostname or "").casefold()
    if parsed.scheme not in {"http", "https"} or not (
            host == "linkedin.com" or host.endswith(".linkedin.com")
    ):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2 or parts[0].casefold() != "in":
        return None
    slug = parts[1].strip()
    if not slug or not re.fullmatch(r"[A-Za-z0-9._%-]{2,120}", slug):
        return None
    return f"https://www.linkedin.com/in/{slug}/"


def _extract_year(raw: Any) -> int | None:
    if raw is None:
        return None
    match = re.search(r"\b(19\d{2}|20\d{2})\b", str(raw))
    return int(match.group(1)) if match else None


def _extract_resume_linkedin_claims(
        profile: dict[str, Any] | None, *, candidate_name: str | None = None
) -> dict[str, Any]:
    """Extract structured professional claims from resume for thorough LinkedIn cross-checking."""
    base = _extract_profile_claims(profile)
    profile = profile or {}

    resolved_name = (candidate_name or "").strip() or None
    if not resolved_name:
        for key in ("full_name", "name"):
            v = profile.get(key)
            if isinstance(v, dict) and v.get("value"):
                resolved_name = str(v["value"]).strip()
                break
            if isinstance(v, str) and v.strip():
                resolved_name = v.strip()
                break

    companies: list[str] = []
    employment_records: list[dict[str, Any]] = []
    for item in (profile.get("employment") or profile.get("experience") or [])[:15]:
        if not isinstance(item, dict):
            continue
        c = str(item.get("company") or "").strip()
        role = str(item.get("title") or item.get("role") or "").strip()
        start_y = _extract_year(item.get("start_date"))
        end_y = _extract_year(item.get("end_date"))
        if c and c not in companies:
            companies.append(c)
        if c or role:
            employment_records.append(
                {
                    "company": c or None,
                    "role": role or None,
                    "start_year": start_y,
                    "end_year": end_y,
                }
            )

    education: list[str] = []
    for item in (profile.get("education") or [])[:8]:
        if isinstance(item, dict):
            parts = [
                str(item.get(k) or "").strip()
                for k in ("degree", "field_of_study", "field", "institution", "school")
            ]
            dedup_parts = list(dict.fromkeys(p for p in parts if p))
            label = " · ".join(dedup_parts)
            if label and label not in education:
                education.append(label)

    certifications: list[str] = []
    for item in (profile.get("certifications") or [])[:10]:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("title") or "").strip()
            if name and name not in certifications:
                certifications.append(name)
        elif isinstance(item, str) and item.strip():
            certifications.append(item.strip())

    return {
        **base,
        "candidate_name": resolved_name,
        "companies": companies[:12],
        "employment_records": employment_records[:12],
        "education": education[:8],
        "certifications": certifications[:10],
    }


def _parse_bright_data_linkedin_record(
        raw: Any, fallback_url: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Normalize Bright Data LinkedIn person payload (SDK ScrapeResult.data, list, dict, or NDJSON)."""
    import json as _json

    record: dict[str, Any] | None = None
    if isinstance(raw, list):
        record = next((item for item in raw if isinstance(item, dict)), None)
    elif isinstance(raw, dict):
        if isinstance(raw.get("data"), list) and raw["data"]:
            record = next((item for item in raw["data"] if isinstance(item, dict)), None)
        elif isinstance(raw.get("data"), dict):
            record = raw["data"]
        else:
            record = raw
    elif isinstance(raw, str):
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = _json.loads(line)
                if isinstance(parsed, dict):
                    record = parsed
                    break
                if isinstance(parsed, list):
                    record = next((item for item in parsed if isinstance(item, dict)), None)
                    if record:
                        break
            except ValueError:
                continue

    if not record:
        return None, "empty_response"
    if record.get("error") or record.get("error_code"):
        return None, str(record.get("error") or record.get("error_code"))[:180]

    def _str_val(v: Any, cap: int = 240) -> str | None:
        if isinstance(v, str) and v.strip():
            return v.strip()[:cap]
        if isinstance(v, dict):
            for k in ("name", "title", "company_name", "school", "value"):
                if isinstance(v.get(k), str) and v[k].strip():
                    return v[k].strip()[:cap]
        return None

    exp_list: list[dict[str, Any]] = []
    for item in (record.get("experience") or [])[:15]:
        if not isinstance(item, dict):
            continue
        company = _str_val(item.get("company") or item.get("company_name"))
        # Bright Data LinkedIn profiles often nest multiple roles under `positions` for one company
        nested_positions = item.get("positions")
        if isinstance(nested_positions, list) and nested_positions:
            for pos in nested_positions[:6]:
                if not isinstance(pos, dict):
                    continue
                title = _str_val(pos.get("title") or pos.get("position") or pos.get("subtitle"))
                start_raw = _str_val(pos.get("start_date"), 40)
                end_raw = _str_val(pos.get("end_date"), 40)
                duration = _str_val(pos.get("duration") or pos.get("meta"), 80) or (
                        f"{start_raw or ''} - {end_raw or ''}".strip(" -") or None
                )
                if title or company:
                    exp_list.append(
                        {
                            "title": title,
                            "company": company,
                            "start_date": start_raw,
                            "end_date": end_raw,
                            "start_year": _extract_year(start_raw or duration),
                            "end_year": _extract_year(end_raw),
                            "duration": duration,
                            "description": _str_val(
                                pos.get("description") or pos.get("description_html"), 260
                            ),
                        }
                    )
            continue
        title = _str_val(item.get("title") or item.get("position"))
        start_raw = _str_val(item.get("start_date"), 40)
        end_raw = _str_val(item.get("end_date"), 40)
        duration = _str_val(item.get("duration") or item.get("meta"), 80) or (
                f"{start_raw or ''} - {end_raw or ''}".strip(" -") or None
        )
        if title or company:
            exp_list.append(
                {
                    "title": title,
                    "company": company,
                    "start_date": start_raw,
                    "end_date": end_raw,
                    "start_year": _extract_year(start_raw or duration),
                    "end_year": _extract_year(end_raw),
                    "duration": duration,
                    "description": _str_val(
                        item.get("description") or item.get("description_html"), 260
                    ),
                }
            )

    edu_list: list[dict[str, Any]] = []
    for item in (record.get("education") or [])[:8]:
        if not isinstance(item, dict):
            continue
        school = _str_val(item.get("title") or item.get("school") or item.get("institution"))
        degree = _str_val(item.get("degree"))
        field = _str_val(item.get("field") or item.get("field_of_study"))
        start_year = _extract_year(item.get("start_year") or item.get("start_date"))
        end_year = _extract_year(item.get("end_year") or item.get("end_date"))
        if school or degree:
            edu_list.append(
                {
                    "school": school,
                    "degree": degree,
                    "field": field,
                    "start_year": start_year,
                    "end_year": end_year,
                }
            )

    certs_list: list[str] = []
    for item in (record.get("certifications") or [])[:12]:
        val = _str_val(item, 140)
        if val and val not in certs_list:
            certs_list.append(val)

    projects_list: list[dict[str, Any]] = []
    for item in (record.get("projects") or [])[:10]:
        if isinstance(item, dict):
            pname = _str_val(item.get("title") or item.get("name"), 140)
            pdesc = _str_val(item.get("description"), 220)
            if pname:
                projects_list.append({"name": pname, "description": pdesc})
        else:
            pname = _str_val(item, 140)
            if pname:
                projects_list.append({"name": pname, "description": None})

    skills_list: list[str] = []
    for item in (record.get("skills") or record.get("top_skills") or [])[:35]:
        val = _str_val(item, 80)
        if val and val not in skills_list:
            skills_list.append(val)

    languages_list: list[str] = []
    for item in (record.get("languages") or [])[:10]:
        val = _str_val(item, 60)
        if val and val not in languages_list:
            languages_list.append(val)

    cur_company = _str_val(record.get("current_company_name") or record.get("current_company"), 160)
    recs_raw = record.get("recommendations_count")
    recs_count = recs_raw if isinstance(recs_raw, int) else (
        len(record["recommendations"]) if isinstance(record.get("recommendations"), list) else None
    )
    activity_count = len(record["activity"]) if isinstance(record.get("activity"), list) else None

    populated_sections = sum(
        1
        for flag in (
            bool(_str_val(record.get("position") or record.get("headline"))),
            bool(_str_val(record.get("about"))),
            bool(exp_list),
            bool(edu_list),
            bool(skills_list or certs_list or projects_list),
        )
        if flag
    )
    profile_completeness = (
        "rich" if populated_sections >= 4 else "moderate" if populated_sections >= 2 else "sparse"
    )

    snapshot = {
        "profile_url": _str_val(record.get("url") or record.get("input_url"), 300) or fallback_url,
        "name": _str_val(record.get("name") or record.get("full_name"), 160),
        "headline": _str_val(record.get("position") or record.get("headline"), 240),
        "current_company": cur_company,
        "location": _str_val(
            record.get("city") or record.get("location") or record.get("country_code"), 120
        ),
        "about": _str_val(record.get("about"), 500),
        "followers": record.get("followers") if isinstance(record.get("followers"), int) else None,
        "connections": record.get("connections") if isinstance(record.get("connections"), int) else None,
        "recommendations_count": recs_count,
        "activity_count": activity_count,
        "profile_completeness": profile_completeness,
        "experience_count": len(exp_list),
        "education_count": len(edu_list),
        "certifications_count": len(certs_list),
        "projects_count": len(projects_list),
        "experience": exp_list,
        "education": edu_list,
        "certifications": certs_list,
        "projects": projects_list,
        "skills": skills_list,
        "languages": languages_list,
    }
    return snapshot, None


def _compare_names(
        resume_name: str | None, linkedin_name: str | None
) -> Literal["match", "partial", "mismatch", "unknown"]:
    if not resume_name or not linkedin_name:
        return "unknown"
    r_toks = [t for t in _extract_tokens(resume_name, drop_stopwords=False) if len(t) >= 2]
    l_toks = [t for t in _extract_tokens(linkedin_name, drop_stopwords=False) if len(t) >= 2]
    if not r_toks or not l_toks:
        return "unknown"
    r_set, l_set = set(r_toks), set(l_toks)
    overlap = r_set & l_set
    if len(overlap) >= min(2, len(r_set), len(l_set)) or (
            len(overlap) / max(1, min(len(r_set), len(l_set))) >= 0.65
    ):
        return "match"
    if overlap:
        return "partial"
    return "mismatch"


def _compare_timelines(
        resume_emp: list[dict[str, Any]], li_exp: list[dict[str, Any]]
) -> tuple[Literal["aligned", "minor_differences", "conflicts", "unknown"], list[str]]:
    if not resume_emp or not li_exp:
        return "unknown", []
    notes: list[str] = []
    compared = 0
    conflicts = 0
    minor = 0
    for remp in resume_emp:
        rcomp = remp.get("company")
        rstart = remp.get("start_year")
        if not rcomp or rstart is None:
            continue
        rtoks = set(_extract_tokens(rcomp, drop_stopwords=True))
        if not rtoks:
            continue
        for lexp in li_exp:
            lcomp = lexp.get("company")
            lstart = lexp.get("start_year")
            if not lcomp or lstart is None:
                continue
            ltoks = set(_extract_tokens(lcomp, drop_stopwords=True))
            if ltoks and (len(rtoks & ltoks) / max(1, len(rtoks)) >= 0.5):
                compared += 1
                diff = abs(int(rstart) - int(lstart))
                if diff >= 2:
                    conflicts += 1
                    notes.append(
                        f"Start year for {rcomp} differs by {diff} years (resume: {rstart}, LinkedIn: {lstart})."
                    )
                elif diff == 1:
                    minor += 1
                break
    if compared == 0:
        return "unknown", notes
    if conflicts > 0:
        return "conflicts", notes[:3]
    if minor > 0:
        return "minor_differences", notes[:3]
    return "aligned", notes


def _heuristic_linkedin_assessment(
        claims: dict[str, Any], li_snapshot: dict[str, Any]
) -> LinkedInProfileAIVerdict:
    exp = li_snapshot.get("experience") or []
    edu = li_snapshot.get("education") or []
    li_certs = li_snapshot.get("certifications") or []
    li_projs = li_snapshot.get("projects") or []
    li_skills = li_snapshot.get("skills") or []
    headline = str(li_snapshot.get("headline") or "")
    about = str(li_snapshot.get("about") or "")
    cur_company = str(li_snapshot.get("current_company") or "")

    name_match = _compare_names(claims.get("candidate_name"), li_snapshot.get("name"))
    timeline_alignment, timeline_notes = _compare_timelines(
        claims.get("employment_records") or [], exp
    )

    if not exp and not edu and not li_skills and not headline and not about and not li_certs:
        return LinkedInProfileAIVerdict(
            verdict="sparse_profile",
            alignment_score=0.1,
            name_match=name_match,
            timeline_alignment="unknown",
            discrepancies=["Public LinkedIn profile contains minimal experience, education, or skills data."],
            summary="LinkedIn profile was found but has very little public career data to compare.",
        )

    li_corpus = " ".join(
        [
            headline,
            about,
            cur_company,
            " ".join(li_skills),
            " ".join(li_certs),
            " ".join(f"{p.get('name') or ''} {p.get('description') or ''}" for p in li_projs),
            " ".join(
                f"{e.get('title') or ''} {e.get('company') or ''} {e.get('description') or ''}"
                for e in exp
            ),
            " ".join(
                f"{e.get('school') or ''} {e.get('degree') or ''} {e.get('field') or ''}"
                for e in edu
            ),
        ]
    )
    li_tokens = set(_extract_tokens(li_corpus, drop_stopwords=True))

    matched_companies: list[str] = []
    for comp in claims.get("companies") or []:
        ctoks = list(dict.fromkeys(_extract_tokens(comp, drop_stopwords=True)))
        if ctoks and sum(1 for t in ctoks if _tokens_match(t, li_tokens)) / len(ctoks) >= 0.5:
            matched_companies.append(comp)

    matched_roles: list[str] = []
    for role in claims.get("roles") or []:
        rtoks = list(dict.fromkeys(_extract_tokens(role, drop_stopwords=True)))
        if rtoks and sum(1 for t in rtoks if _tokens_match(t, li_tokens)) / len(rtoks) >= 0.5:
            matched_roles.append(role)

    matched_education: list[str] = []
    for ed in claims.get("education") or []:
        etoks = list(dict.fromkeys(_extract_tokens(ed, drop_stopwords=True)))
        if etoks and sum(1 for t in etoks if _tokens_match(t, li_tokens)) / len(etoks) >= 0.4:
            matched_education.append(ed)

    matched_certifications: list[str] = []
    for cert in claims.get("certifications") or []:
        ctoks = list(dict.fromkeys(_extract_tokens(cert, drop_stopwords=True)))
        if ctoks and sum(1 for t in ctoks if _tokens_match(t, li_tokens)) / len(ctoks) >= 0.5:
            matched_certifications.append(cert)

    matched_projects: list[str] = []
    for proj in claims.get("projects") or []:
        pname = proj.get("name") if isinstance(proj, dict) else str(proj)
        if not pname:
            continue
        ptoks = list(dict.fromkeys(_extract_tokens(pname, drop_stopwords=True)))
        if ptoks and sum(1 for t in ptoks if _tokens_match(t, li_tokens)) / len(ptoks) >= 0.5:
            matched_projects.append(pname)

    matched_skills: list[str] = []
    for skill in claims.get("skills") or []:
        stoks = _extract_tokens(skill, drop_stopwords=False)
        if stoks and any(_tokens_match(t, li_tokens) for t in stoks):
            if skill not in matched_skills:
                matched_skills.append(skill)

    components: list[tuple[float, float]] = []
    if claims.get("companies"):
        components.append((0.30, len(matched_companies) / len(claims["companies"])))
    if claims.get("roles"):
        components.append((0.20, len(matched_roles) / len(claims["roles"])))
    if claims.get("education"):
        components.append((0.18, len(matched_education) / len(claims["education"])))
    if claims.get("skills"):
        components.append((0.17, min(1.0, len(matched_skills) / max(1, min(len(claims["skills"]), 6)))))
    if claims.get("certifications"):
        components.append((0.08, len(matched_certifications) / len(claims["certifications"])))
    if claims.get("projects"):
        components.append((0.07, len(matched_projects) / len(claims["projects"])))

    score = (
        sum(w * v for w, v in components) / sum(w for w, _ in components)
        if components
        else (0.5 if (exp or edu) else 0.15)
    )
    if name_match == "mismatch":
        score = min(score, 0.20)
    elif timeline_alignment == "conflicts":
        score = max(0.0, score - 0.15)
    score = round(max(0.0, min(1.0, score)), 3)

    discrepancies: list[str] = []
    if name_match == "mismatch":
        discrepancies.append(
            f"LinkedIn profile name ({li_snapshot.get('name')}) does not match candidate name on resume."
        )
    discrepancies.extend(timeline_notes)
    if claims.get("companies") and not matched_companies:
        discrepancies.append("Resume employers were not found in the public LinkedIn experience list.")
    if claims.get("education") and not matched_education:
        discrepancies.append("Resume education details were not matched on the LinkedIn profile.")

    if name_match == "mismatch":
        verdict: Literal["consistent", "partially_consistent", "inconsistent", "sparse_profile"] = (
            "inconsistent"
        )
        summary = "LinkedIn profile name does not match the candidate on the resume; manual verification required."
    elif (score >= 0.55 or (
            matched_companies and (matched_roles or matched_education))) and timeline_alignment != "conflicts":
        verdict = "consistent"
        summary = "Public LinkedIn profile aligns well with the candidate's resume experience, education, and skills."
    elif score >= 0.22 or matched_companies or matched_roles or matched_education or len(matched_skills) >= 2:
        verdict = "partially_consistent"
        summary = "LinkedIn profile partially matches resume details; some roles, dates, or credentials differ or are unlisted."
    else:
        verdict = "inconsistent"
        discrepancies.append("Public LinkedIn profile shows little overlap with the candidate's resume history.")
        summary = "LinkedIn profile details do not align closely with the career history on the resume."

    return LinkedInProfileAIVerdict(
        verdict=verdict,
        alignment_score=score,
        name_match=name_match,
        timeline_alignment=timeline_alignment,
        matched_companies=matched_companies[:10],
        matched_roles=matched_roles[:10],
        matched_education=matched_education[:6],
        matched_certifications=matched_certifications[:8],
        matched_projects=matched_projects[:8],
        matched_skills=matched_skills[:15],
        discrepancies=discrepancies[:8],
        summary=summary[:320],
    )


async def _run_ai_linkedin_assessment(
        claims: dict[str, Any], li_snapshot: dict[str, Any], *, timeout: float = 25.0
) -> tuple[LinkedInProfileAIVerdict, str]:
    try:
        from app.ai_features.ai.settings import get_ai_settings
        from app.ai_features.ai.tasks import get_extractor

        ai_settings = get_ai_settings()
        if ai_settings.model in {"heuristic", "test"} or not ai_settings.model:
            return _heuristic_linkedin_assessment(claims, li_snapshot), "heuristic"

        resume_emp_lines = "\n".join(
            f"- {e.get('role') or 'Role'} at {e.get('company') or 'Company'} "
            f"({e.get('start_year') or '?'}–{e.get('end_year') or 'present'})"
            for e in (claims.get("employment_records") or [])[:10]
        )
        exp_lines = "\n".join(
            f"- {e.get('title') or 'Role'} at {e.get('company') or 'Company'} ({e.get('duration') or ''})"
            for e in (li_snapshot.get("experience") or [])[:12]
        )
        edu_lines = "\n".join(
            f"- {e.get('degree') or ''} {e.get('field') or ''} at {e.get('school') or ''} "
            f"({e.get('start_year') or ''}-{e.get('end_year') or ''})".strip()
            for e in (li_snapshot.get("education") or [])[:6]
        )
        proj_lines = ", ".join(
            p.get("name") or "" for p in (li_snapshot.get("projects") or [])[:8] if p.get("name")
        )
        payload = (
            "<untrusted_resume>\n"
            f"Candidate Name: {claims.get('candidate_name') or 'Unknown'}\n"
            f"Employment:\n{resume_emp_lines}\n"
            f"Companies: {', '.join(claims.get('companies') or [])}\n"
            f"Roles: {', '.join(claims.get('roles') or [])}\n"
            f"Education: {', '.join(claims.get('education') or [])}\n"
            f"Certifications: {', '.join(claims.get('certifications') or [])}\n"
            f"Projects: {', '.join(p['name'] for p in (claims.get('projects') or []) if p.get('name'))}\n"
            f"Skills: {', '.join(claims.get('skills') or [])}\n"
            "</untrusted_resume>\n\n"
            "<untrusted_linkedin>\n"
            f"Profile Name: {li_snapshot.get('name') or 'Unknown'}\n"
            f"Headline: {li_snapshot.get('headline') or ''}\n"
            f"Current Company: {li_snapshot.get('current_company') or ''}\n"
            f"Location: {li_snapshot.get('location') or ''}\n"
            f"Profile Depth: {li_snapshot.get('profile_completeness') or 'unknown'} "
            f"(connections={li_snapshot.get('connections')}, followers={li_snapshot.get('followers')})\n"
            f"About: {li_snapshot.get('about') or ''}\n"
            f"Experience:\n{exp_lines}\n"
            f"Education:\n{edu_lines}\n"
            f"Certifications: {', '.join(li_snapshot.get('certifications') or [])}\n"
            f"Projects: {proj_lines}\n"
            f"Skills: {', '.join(li_snapshot.get('skills') or [])}\n"
            "</untrusted_linkedin>"
        )
        extractor = get_extractor("linkedin_profile_verification")
        run = await asyncio.wait_for(extractor.run(payload), timeout=timeout)
        active_model = run.model.split(",")[0] if run.model else ai_settings.model
        return run.output, f"{run.engine}:{active_model}"
    except Exception as exc:
        logger.info(
            "LinkedIn profile AI assessment fell back to heuristic",
            extra={"error_type": type(exc).__name__},
        )
        return _heuristic_linkedin_assessment(claims, li_snapshot), "heuristic_fallback"


async def _fetch_linkedin_via_brightdata_sdk(
        norm_url: str,
        *,
        token: str,
        timeout: float,
        sdk_client: Any = None,
) -> tuple[Any | None, dict[str, Any], VerificationResultData | None]:
    """Fetch a LinkedIn profile using the official `brightdata-sdk` (`BrightDataClient`)."""
    from brightdata import BrightDataClient
    from brightdata.exceptions import (
        APIError,
        AuthenticationError,
        BrightDataError,
        DataNotReadyError,
        NetworkError,
        SSLError,
        ValidationError,
    )

    timeout_int = int(max(15, min(timeout, 120)))
    meta: dict[str, Any] = {"provider": "bright_data_sdk"}

    try:
        if sdk_client is not None:
            result = await sdk_client.scrape.linkedin.profiles(url=norm_url, timeout=timeout_int)
        else:
            async with BrightDataClient(
                    token=token,
                    timeout=timeout_int,
                    auto_create_zones=False,
                    validate_token=False,
            ) as bd_client:
                result = await bd_client.scrape.linkedin.profiles(
                    url=norm_url,
                    timeout=timeout_int,
                )

        if isinstance(result, list):
            result = result[0] if result else None
        if result is None:
            return (
                None,
                meta,
                VerificationResultData(
                    "linkedin_profile",
                    "needs_review",
                    "Bright Data SDK returned an empty LinkedIn response",
                    {
                        "reason_code": "linkedin_profile_unavailable",
                        **meta,
                        "url": norm_url,
                    },
                ),
            )

        snapshot_id = getattr(result, "snapshot_id", None)
        raw_elapsed = getattr(result, "elapsed_ms", None)
        elapsed_ms = raw_elapsed() if callable(raw_elapsed) else raw_elapsed
        if snapshot_id:
            meta["snapshot_id"] = str(snapshot_id)
        if isinstance(elapsed_ms, (int, float)):
            meta["elapsed_ms"] = round(float(elapsed_ms), 1)

        err = getattr(result, "error", None)
        data = getattr(result, "data", None)
        status_str = str(getattr(result, "status", "") or "").lower()

        if err and not data:
            err_msg = re.sub(r"\s+", " ", str(err)).strip()[:160]
            if any(tok in err_msg.lower() for tok in ("401", "403", "unauthorized", "auth")):
                return (
                    None,
                    meta,
                    VerificationResultData(
                        "linkedin_profile",
                        "not_verified",
                        "Bright Data authentication failed; check BRIGHT_DATA_API_KEY",
                        {"reason_code": "bright_data_auth_error", **meta, "provider_error": err_msg, "url": norm_url},
                    ),
                )
            if "429" in err_msg or "rate limit" in err_msg.lower():
                return (
                    None,
                    meta,
                    VerificationResultData(
                        "linkedin_profile",
                        "not_verified",
                        "Bright Data rate limit reached; could not fetch LinkedIn profile",
                        {"reason_code": "bright_data_rate_limited", **meta, "provider_error": err_msg, "url": norm_url},
                    ),
                )
            if any(tok in err_msg.lower() for tok in ("not active", "customer", "billing", "subscription", "400")):
                return (
                    None,
                    meta,
                    VerificationResultData(
                        "linkedin_profile",
                        "not_verified",
                        f"Bright Data SDK error: {err_msg}",
                        {"reason_code": "bright_data_api_error", **meta, "provider_error": err_msg, "url": norm_url},
                    ),
                )
            return (
                None,
                meta,
                VerificationResultData(
                    "linkedin_profile",
                    "needs_review",
                    "LinkedIn profile could not be retrieved (private, restricted, or not found)",
                    {"reason_code": "linkedin_profile_unavailable", **meta, "provider_error": err_msg, "url": norm_url},
                ),
            )

        if status_str in {"pending", "running"} and not data:
            return (
                None,
                meta,
                VerificationResultData(
                    "linkedin_profile",
                    "not_verified",
                    "LinkedIn profile scrape is still processing on Bright Data; re-run verification shortly",
                    {"reason_code": "linkedin_scrape_pending", **meta, "url": norm_url},
                ),
            )

        return data, meta, None

    except AuthenticationError as exc:
        err_msg = re.sub(r"\s+", " ", str(exc)).strip()[:140]
        return (
            None,
            meta,
            VerificationResultData(
                "linkedin_profile",
                "not_verified",
                "Bright Data authentication failed; check BRIGHT_DATA_API_KEY",
                {"reason_code": "bright_data_auth_error", **meta, "provider_error": err_msg or None, "url": norm_url},
            ),
        )
    except ValidationError as exc:
        err_msg = re.sub(r"\s+", " ", str(exc)).strip()[:140]
        return (
            None,
            meta,
            VerificationResultData(
                "linkedin_profile",
                "failed",
                f"Invalid LinkedIn profile URL: {err_msg}" if err_msg else "LinkedIn URL failed SDK validation",
                {"reason_code": "invalid_linkedin_url", **meta, "url": norm_url},
            ),
        )
    except DataNotReadyError:
        return (
            None,
            meta,
            VerificationResultData(
                "linkedin_profile",
                "not_verified",
                "LinkedIn profile scrape is still processing on Bright Data; re-run verification shortly",
                {"reason_code": "linkedin_scrape_pending", **meta, "url": norm_url},
            ),
        )
    except APIError as exc:
        status_code = getattr(exc, "status_code", None)
        err_msg = re.sub(r"\s+", " ", str(exc)).strip()[:140]
        if status_code in {401, 403}:
            return (
                None,
                meta,
                VerificationResultData(
                    "linkedin_profile",
                    "not_verified",
                    "Bright Data authentication failed; check BRIGHT_DATA_API_KEY",
                    {"reason_code": "bright_data_auth_error", "http_status": status_code, **meta,
                     "provider_error": err_msg or None, "url": norm_url},
                ),
            )
        if status_code == 429:
            return (
                None,
                meta,
                VerificationResultData(
                    "linkedin_profile",
                    "not_verified",
                    "Bright Data rate limit reached; could not fetch LinkedIn profile",
                    {"reason_code": "bright_data_rate_limited", "http_status": status_code, **meta,
                     "provider_error": err_msg or None, "url": norm_url},
                ),
            )
        signal_msg = (
            f"Bright Data SDK returned HTTP {status_code}: {err_msg}"
            if status_code and err_msg
            else f"Bright Data SDK error: {err_msg}" if err_msg else "Bright Data API error while inspecting LinkedIn profile"
        )
        return (
            None,
            meta,
            VerificationResultData(
                "linkedin_profile",
                "not_verified",
                signal_msg[:220],
                {
                    "reason_code": "bright_data_http_error",
                    "http_status": status_code,
                    **meta,
                    "provider_error": err_msg or None,
                    "url": norm_url,
                },
            ),
        )
    except (asyncio.TimeoutError, TimeoutError):
        return (
            None,
            meta,
            VerificationResultData(
                "linkedin_profile",
                "not_verified",
                "LinkedIn profile inspection timed out via Bright Data SDK",
                {"reason_code": "timeout", **meta, "url": norm_url},
            ),
        )
    except (NetworkError, SSLError, BrightDataError, OSError) as exc:
        err_msg = re.sub(r"\s+", " ", str(exc)).strip()[:140]
        return (
            None,
            meta,
            VerificationResultData(
                "linkedin_profile",
                "not_verified",
                f"LinkedIn profile could not be fetched via Bright Data SDK: {err_msg}" if err_msg else "LinkedIn profile could not be fetched via Bright Data SDK",
                {"reason_code": "network_unavailable", **meta, "provider_error": err_msg or None, "url": norm_url},
            ),
        )


async def verify_linkedin_profile(
        linkedin_url: str | None,
        profile: dict[str, Any] | None,
        *,
        candidate_name: str | None = None,
        enabled: bool = True,
        ai_enabled: bool = True,
        api_key: str | None = None,
        dataset_id: str = "gd_l1viktl72bvl7bjuj0",
        timeout: float = 45.0,
        sdk_client: Any = None,
        client: httpx.AsyncClient | None = None,
        transport=None,
        ai_analyzer: Callable[
                         [dict[str, Any], dict[str, Any]],
                         Awaitable[LinkedInProfileAIVerdict] | LinkedInProfileAIVerdict,
                     ]
                     | None = None,
) -> VerificationResultData:
    """Verify a candidate's public LinkedIn profile thoroughly via Bright Data SDK + AI cross-check."""
    if not enabled:
        return VerificationResultData(
            "linkedin_profile",
            "not_verified",
            "LinkedIn profile verification is disabled",
            {"reason_code": "check_disabled"},
        )

    if not linkedin_url or not str(linkedin_url).strip():
        return VerificationResultData(
            "linkedin_profile",
            "not_verified",
            "No LinkedIn profile URL provided in candidate profile",
            {"reason_code": "missing_value"},
        )

    norm_url = _normalize_linkedin_url(linkedin_url)
    if not norm_url:
        return VerificationResultData(
            "linkedin_profile",
            "failed",
            "LinkedIn URL is invalid (expected linkedin.com/in/<profile>)",
            {"reason_code": "invalid_linkedin_url", "url": str(linkedin_url).strip()[:200]},
        )

    token = (
            api_key or os.getenv("BRIGHT_DATA_API_KEY") or os.getenv("BRIGHTDATA_API_TOKEN") or ""
    ).strip()
    if not token and sdk_client is None and client is None and transport is None:
        return VerificationResultData(
            "linkedin_profile",
            "not_verified",
            "LinkedIn verification requires BRIGHT_DATA_API_KEY configuration",
            {"reason_code": "bright_data_not_configured", "url": norm_url},
        )

    provider_meta: dict[str, Any] = {"provider": "bright_data_sdk"}
    raw_payload: Any = None

    # Use official brightdata-sdk unless a legacy httpx test client/transport was explicitly injected.
    if sdk_client is not None or (client is None and transport is None):
        raw_payload, provider_meta, early_result = await _fetch_linkedin_via_brightdata_sdk(
            norm_url,
            token=token,
            timeout=timeout,
            sdk_client=sdk_client,
        )
        if early_result is not None:
            return early_result
    else:
        owned = client is None
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Job-Sentry-verification/1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        session = client or httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            transport=transport,
            trust_env=False,
            headers=headers,
        )
        provider_meta = {"provider": "bright_data"}
        try:
            resp = await session.post(
                _BRIGHT_DATA_SCRAPE_URL,
                params={
                    "dataset_id": dataset_id,
                    "notify": "false",
                    "include_errors": "true",
                },
                json={"input": [{"url": norm_url}], "limit_per_input": None},
            )
            if resp.status_code in {401, 403}:
                return VerificationResultData(
                    "linkedin_profile",
                    "not_verified",
                    "Bright Data authentication failed; check BRIGHT_DATA_API_KEY",
                    {"reason_code": "bright_data_auth_error", "http_status": resp.status_code, "url": norm_url},
                )
            if resp.status_code == 429:
                return VerificationResultData(
                    "linkedin_profile",
                    "not_verified",
                    "Bright Data rate limit reached; could not fetch LinkedIn profile",
                    {"reason_code": "bright_data_rate_limited", "http_status": resp.status_code, "url": norm_url},
                )
            if resp.status_code >= 400:
                err_msg = re.sub(r"\s+", " ", (resp.text or "")).strip()[:140]
                return VerificationResultData(
                    "linkedin_profile",
                    "not_verified",
                    f"Bright Data returned HTTP {resp.status_code}: {err_msg}" if err_msg else f"Bright Data returned HTTP {resp.status_code} while inspecting LinkedIn profile",
                    {"reason_code": "bright_data_http_error", "http_status": resp.status_code,
                     "provider": "bright_data", "provider_error": err_msg or None, "url": norm_url},
                )
            try:
                raw_payload = resp.json()
            except ValueError:
                raw_payload = resp.text
        except (asyncio.TimeoutError, httpx.TimeoutException):
            return VerificationResultData(
                "linkedin_profile",
                "not_verified",
                "LinkedIn profile inspection timed out",
                {"reason_code": "timeout", "provider": "bright_data", "url": norm_url},
            )
        except (OSError, httpx.HTTPError, ValueError):
            return VerificationResultData(
                "linkedin_profile",
                "not_verified",
                "LinkedIn profile could not be fetched via Bright Data",
                {"reason_code": "network_unavailable", "provider": "bright_data", "url": norm_url},
            )
        finally:
            if owned:
                await session.aclose()

    li_snapshot, parse_err = _parse_bright_data_linkedin_record(raw_payload, norm_url)
    if parse_err or li_snapshot is None:
        return VerificationResultData(
            "linkedin_profile",
            "needs_review",
            "LinkedIn profile could not be retrieved (private, restricted, or not found)",
            {
                "reason_code": "linkedin_profile_unavailable",
                **provider_meta,
                "provider_error": parse_err,
                "url": norm_url,
            },
        )

    claims = _extract_resume_linkedin_claims(profile, candidate_name=candidate_name)
    if ai_analyzer is not None:
        verdict_res = ai_analyzer(claims, li_snapshot)
        verdict = await verdict_res if inspect.isawaitable(verdict_res) else verdict_res
        mode = "custom_ai"
    elif ai_enabled:
        verdict, mode = await _run_ai_linkedin_assessment(claims, li_snapshot)
    else:
        verdict = _heuristic_linkedin_assessment(claims, li_snapshot)
        mode = "heuristic"

    # Compute deterministic name/timeline guards even if AI left them unknown
    det_name_match = _compare_names(claims.get("candidate_name"), li_snapshot.get("name"))
    det_timeline, _ = _compare_timelines(
        claims.get("employment_records") or [], li_snapshot.get("experience") or []
    )
    final_name_match = verdict.name_match if verdict.name_match != "unknown" else det_name_match
    final_timeline = (
        verdict.timeline_alignment if verdict.timeline_alignment != "unknown" else det_timeline
    )

    if final_name_match == "mismatch":
        status: Literal["passed", "needs_review", "not_verified", "failed"] = "needs_review"
    else:
        status = "passed" if verdict.verdict == "consistent" else "needs_review"

    checks_performed = {
        "name_match": final_name_match,
        "timeline_alignment": final_timeline,
        "companies_matched": len(verdict.matched_companies),
        "companies_claimed": len(claims.get("companies") or []),
        "roles_matched": len(verdict.matched_roles),
        "education_matched": len(verdict.matched_education),
        "certifications_matched": len(verdict.matched_certifications),
        "projects_matched": len(verdict.matched_projects),
        "skills_matched": len(verdict.matched_skills),
        "profile_completeness": li_snapshot.get("profile_completeness"),
    }

    signal = (
        f"LinkedIn profile ({verdict.verdict.replace('_', ' ')}, "
        f"{round(verdict.alignment_score * 100)}% alignment); "
        "public profile data is self-reported and does not prove identity."
    )
    return VerificationResultData(
        "linkedin_profile",
        status,
        signal,
        {
            **li_snapshot,
            **provider_meta,
            "url": norm_url,
            "ai_verdict": verdict.verdict,
            "ai_alignment_score": verdict.alignment_score,
            "name_match": final_name_match,
            "timeline_alignment": final_timeline,
            "ai_summary": verdict.summary,
            "matched_companies": list(verdict.matched_companies),
            "matched_roles": list(verdict.matched_roles),
            "matched_education": list(verdict.matched_education),
            "matched_certifications": list(verdict.matched_certifications),
            "matched_projects": list(verdict.matched_projects),
            "matched_skills": list(verdict.matched_skills),
            "discrepancies": list(verdict.discrepancies),
            "checks_performed": checks_performed,
            "analysis_mode": mode,
        },
    )
