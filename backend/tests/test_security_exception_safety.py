import pytest

from app.core.exceptions import UnauthorizedException
from app.core.security import verify_google_id_token


@pytest.mark.parametrize(
    "error",
    [ValueError("provider response included a secret"), RuntimeError("raw verifier detail")],
)
def test_google_token_errors_do_not_expose_provider_details(monkeypatch, error):
    def fail_verification(*args, **kwargs):
        raise error

    monkeypatch.setattr("app.core.security.id_token.verify_oauth2_token", fail_verification)

    with pytest.raises(UnauthorizedException) as raised:
        verify_google_id_token("token-value")

    assert "secret" not in raised.value.message
    assert "raw verifier detail" not in raised.value.message
    assert raised.value.message == "Could not validate Google credentials"
