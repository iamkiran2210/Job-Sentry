"""Exercises the REAL seam (_compat.get_accessible_job -> JobsService.get_job). Runs only in the sandbox, where
JobsService is my reconstruction of the documented rules; in your repo, copy one of these as an integration
test with your real fixtures (company_with_admin, auth_headers, ...)."""

import pytest

from app.core.config import settings

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not getattr(settings, "SANDBOX", False), reason="sandbox-only"),
]


async def test_seam_matches_documented_job_access_rules(factory):
    from app.models.job import JobAccess
    from app.ai_features._compat import get_accessible_job, is_access_denied

    from .helpers import make_company, make_job, make_user

    a, b = await make_company(factory, "A"), await make_company(factory, "B")
    job = await make_job(factory, a)
    member, other, viewer, editor = (
        await make_user(factory, a),
        await make_user(factory, b),
        await make_user(factory),
        await make_user(factory),
    )
    async with factory() as s:
        s.add_all(
            [
                JobAccess(job_id=job, user_id=viewer.id, access_level="viewer"),
                JobAccess(job_id=job, user_id=editor.id, access_level="editor"),
            ]
        )
        await s.commit()

    async def attempt(user, edit):
        async with factory() as s:
            try:
                return (await get_accessible_job(s, user, job, require_edit=edit)).id
            except Exception as exc:  # noqa: BLE001
                assert is_access_denied(exc)
                return exc.status_code

    assert (
            await attempt(member, True) == job
            and await attempt(editor, True) == job
            and await attempt(viewer, False) == job
    )
    assert await attempt(viewer, True) == 403
    assert (
            await attempt(other, False) == 404
            and await attempt((await make_user(factory)), False) == 404
    )
