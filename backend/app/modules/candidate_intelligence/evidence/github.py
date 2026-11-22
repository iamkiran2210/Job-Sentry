"""Public GitHub language signals. Never treat repository metadata as proof of skill."""

from __future__ import annotations

import re
import uuid

import httpx

from app.modules.candidate_intelligence.types import ScoreEvidence


def github_owner_repo(url: str | None) -> tuple[str, str] | None:
    if not url:
        return None
    match = re.fullmatch(
        r"https?://(?:www\.)?github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+)/?", url.strip(), re.I
    )
    if not match:
        return None
    owner, repo = match.groups()
    if repo.endswith(".git"):
        repo = repo[:-4]
    if repo.lower() in {"settings", "orgs", "topics", "marketplace", "features"}:
        return None
    return owner, repo


async def github_language_evidence(
        url: str | None,
        *,
        timeout: float = 4.0,
        max_repositories: int = 20,
        client: httpx.AsyncClient | None = None,
) -> tuple[list[ScoreEvidence], dict]:
    """Fetch public repo language byte counts through api.github.com only; no auth or redirects."""
    target = github_owner_repo(url)
    if not target:
        return [], {"status": "not_verified", "reason": "no_valid_github_profile"}
    owner, repo = target
    owned = client is None
    session = client or httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Job-Sentry-candidate-evidence",
        },
    )
    try:
        response = await session.get(
            f"https://api.github.com/users/{owner}/repos",
            params={"per_page": min(max_repositories, 100), "sort": "updated", "type": "owner"},
        )
        if response.status_code == 404:
            return [], {"status": "needs_review", "reason": "github_repository_not_found"}
        response.raise_for_status()
        repos = response.json()
        if not isinstance(repos, list):
            repos = []
        repos = [{"full_name": f"{owner}/{repo}"}] + repos
        found: dict[str, set[str]] = {}
        for item in repos[:max_repositories]:
            # Only call fixed GitHub API paths derived from validated owner/repo.
            full = item.get("full_name", "")
            if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", full):
                continue
            lang_response = await session.get(f"https://api.github.com/repos/{full}/languages")
            if lang_response.status_code == 404:
                continue
            lang_response.raise_for_status()
            payload = lang_response.json()
            if isinstance(payload, dict):
                for language, byte_count in payload.items():
                    if isinstance(language, str) and isinstance(byte_count, int) and byte_count > 0:
                        found.setdefault(language, set()).add(full)
        evidence = [
            ScoreEvidence(
                evidence_id=str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"github:{language.casefold()}:{','.join(sorted(repos_seen))}",
                    )
                ),
                category="skills",
                signal_type="github_language_signal",
                value=0.70,
                source_location=f"public_github:{owner}/{repo}",
                matched_term=language,
                requirement_term=language,
                canonical_term=language.casefold(),
                rationale="Public repository language metadata is a weak signal; it does not prove skill or employment.",
            )
            for language, repos_seen in sorted(found.items(), key=lambda pair: pair[0].casefold())
        ]
        return evidence, {
            "status": "passed",
            "repositories_checked": min(len(repos), max_repositories),
            "languages_found": len(evidence),
            "signal_limit": "Public GitHub metadata does not prove skill or employment.",
        }
    except (httpx.HTTPError, ValueError) as exc:
        return [], {"status": "not_verified", "reason": type(exc).__name__}
    finally:
        if owned:
            await session.aclose()
