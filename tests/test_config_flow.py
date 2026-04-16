"""Tests for the Claude Usage config flow."""

from __future__ import annotations

import base64
import hashlib
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import pytest

from custom_components.claude_usage.config_flow import (
    _async_exchange_code,
    _async_validate_refresh_token,
    _build_authorize_url,
    _compute_code_challenge,
    _generate_pkce_pair,
    _split_code_and_state,
    _token_data_to_entry,
)
from custom_components.claude_usage.const import (
    AUTH_REDIRECT_URI,
    AUTHORIZE_URL,
    CLIENT_ID,
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    OAUTH_AUTHORIZE_SCOPES,
)

from .conftest import MOCK_TOKEN_RESPONSE, create_mock_response


# --- _async_validate_refresh_token tests ---


@pytest.mark.asyncio
async def test_validate_token_success() -> None:
    """Test successful token validation."""
    session = MagicMock()
    session.post = MagicMock(return_value=create_mock_response(200, MOCK_TOKEN_RESPONSE))

    data, error = await _async_validate_refresh_token(session, "good-token")

    assert data == MOCK_TOKEN_RESPONSE
    assert error == ""


@pytest.mark.asyncio
async def test_validate_token_invalid() -> None:
    """Test invalid token returns invalid_token error."""
    session = MagicMock()
    session.post = MagicMock(return_value=create_mock_response(401))

    data, error = await _async_validate_refresh_token(session, "bad-token")

    assert data is None
    assert error == "invalid_token"


@pytest.mark.asyncio
async def test_validate_token_server_error_500() -> None:
    """Test 500 server error returns cannot_connect, not invalid_token."""
    session = MagicMock()
    session.post = MagicMock(return_value=create_mock_response(500))

    data, error = await _async_validate_refresh_token(session, "any-token")

    assert data is None
    assert error == "cannot_connect"


@pytest.mark.asyncio
async def test_validate_token_server_error_502() -> None:
    """Test 502 returns cannot_connect."""
    session = MagicMock()
    session.post = MagicMock(return_value=create_mock_response(502))

    data, error = await _async_validate_refresh_token(session, "any-token")

    assert data is None
    assert error == "cannot_connect"


@pytest.mark.asyncio
async def test_validate_token_403_is_invalid() -> None:
    """Test 403 returns invalid_token (client error, not server error)."""
    session = MagicMock()
    session.post = MagicMock(return_value=create_mock_response(403))

    data, error = await _async_validate_refresh_token(session, "forbidden-token")

    assert data is None
    assert error == "invalid_token"


@pytest.mark.asyncio
async def test_validate_token_connection_error() -> None:
    """Test network error returns cannot_connect."""
    import aiohttp

    session = MagicMock()
    resp = AsyncMock()
    resp.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("connection failed"))
    session.post = MagicMock(return_value=resp)

    data, error = await _async_validate_refresh_token(session, "any-token")

    assert data is None
    assert error == "cannot_connect"


@pytest.mark.asyncio
async def test_validate_token_timeout() -> None:
    """Test timeout returns cannot_connect."""
    session = MagicMock()
    resp = AsyncMock()
    resp.__aenter__ = AsyncMock(side_effect=TimeoutError)
    session.post = MagicMock(return_value=resp)

    data, error = await _async_validate_refresh_token(session, "any-token")

    assert data is None
    assert error == "cannot_connect"


@pytest.mark.asyncio
async def test_validate_token_custom_client_id() -> None:
    """Test that a custom client ID is used in the request."""
    session = MagicMock()
    mock_resp = create_mock_response(200, MOCK_TOKEN_RESPONSE)
    session.post = MagicMock(return_value=mock_resp)

    data, error = await _async_validate_refresh_token(
        session, "good-token", client_id="custom-id"
    )

    assert data == MOCK_TOKEN_RESPONSE
    assert error == ""
    call_kwargs = session.post.call_args
    assert call_kwargs.kwargs["json"]["client_id"] == "custom-id"


@pytest.mark.asyncio
async def test_validate_token_default_client_id() -> None:
    """Test that the default client ID is used when none is provided."""
    session = MagicMock()
    mock_resp = create_mock_response(200, MOCK_TOKEN_RESPONSE)
    session.post = MagicMock(return_value=mock_resp)

    await _async_validate_refresh_token(session, "good-token")

    call_kwargs = session.post.call_args
    assert call_kwargs.kwargs["json"]["client_id"] == CLIENT_ID


# --- PKCE helper tests ---


def test_compute_code_challenge_is_s256_url_safe_no_padding() -> None:
    """The challenge must be base64url-encoded SHA256 of the verifier, no padding."""
    verifier = "test-verifier"
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert _compute_code_challenge(verifier) == expected
    assert "=" not in _compute_code_challenge(verifier)


def test_generate_pkce_pair_matches() -> None:
    """The generated challenge must match SHA256(verifier)."""
    verifier, challenge = _generate_pkce_pair()
    # Verifier length must be within the RFC 7636 43-128 char range.
    assert 43 <= len(verifier) <= 128
    assert challenge == _compute_code_challenge(verifier)


def test_generate_pkce_pair_is_random() -> None:
    """Every call must produce a fresh verifier."""
    v1, _ = _generate_pkce_pair()
    v2, _ = _generate_pkce_pair()
    assert v1 != v2


def test_build_authorize_url_has_required_params() -> None:
    """The authorize URL must carry PKCE + OAuth params the server expects."""
    url = _build_authorize_url("cid", "challenge", "state-abc")
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTHORIZE_URL
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert q["client_id"] == "cid"
    assert q["response_type"] == "code"
    assert q["redirect_uri"] == AUTH_REDIRECT_URI
    assert q["scope"] == OAUTH_AUTHORIZE_SCOPES
    assert q["code_challenge"] == "challenge"
    assert q["code_challenge_method"] == "S256"
    assert q["state"] == "state-abc"


# --- _split_code_and_state tests ---


def test_split_code_and_state_with_hash() -> None:
    assert _split_code_and_state("abc123#state456") == ("abc123", "state456")


def test_split_code_and_state_without_hash() -> None:
    assert _split_code_and_state("just-a-code") == ("just-a-code", None)


def test_split_code_and_state_trims_whitespace() -> None:
    assert _split_code_and_state("  abc#xyz  \n") == ("abc", "xyz")


def test_split_code_and_state_empty_state_is_none() -> None:
    assert _split_code_and_state("abc#") == ("abc", None)


# --- _async_exchange_code tests ---


MOCK_CODE_RESPONSE = {
    "access_token": "oauth-access",
    "refresh_token": "oauth-refresh",
    "expires_in": 28800,
}


@pytest.mark.asyncio
async def test_exchange_code_success() -> None:
    session = MagicMock()
    session.post = MagicMock(return_value=create_mock_response(200, MOCK_CODE_RESPONSE))

    data, err = await _async_exchange_code(session, "code", "verifier")

    assert data == MOCK_CODE_RESPONSE
    assert err == ""
    body = session.post.call_args.kwargs["json"]
    assert body["grant_type"] == "authorization_code"
    assert body["code"] == "code"
    assert body["code_verifier"] == "verifier"
    assert body["redirect_uri"] == AUTH_REDIRECT_URI
    # `state` is an authorize-endpoint param only (RFC 6749 §4.1.3); must NOT
    # be included in the token exchange body.
    assert "state" not in body


@pytest.mark.asyncio
async def test_exchange_code_invalid() -> None:
    session = MagicMock()
    session.post = MagicMock(return_value=create_mock_response(400))

    data, err = await _async_exchange_code(session, "bad", "v")

    assert data is None
    assert err == "invalid_code"


@pytest.mark.asyncio
async def test_exchange_code_server_error() -> None:
    session = MagicMock()
    session.post = MagicMock(return_value=create_mock_response(503))

    data, err = await _async_exchange_code(session, "code", "v")

    assert data is None
    assert err == "cannot_connect"


@pytest.mark.asyncio
async def test_exchange_code_network_error() -> None:
    import aiohttp

    session = MagicMock()
    resp = AsyncMock()
    resp.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("boom"))
    session.post = MagicMock(return_value=resp)

    data, err = await _async_exchange_code(session, "code", "v")

    assert data is None
    assert err == "cannot_connect"


# --- _token_data_to_entry tests ---


def test_token_data_to_entry_success() -> None:
    entry = _token_data_to_entry(MOCK_CODE_RESPONSE)
    assert entry is not None
    assert entry[CONF_ACCESS_TOKEN] == "oauth-access"
    assert entry[CONF_REFRESH_TOKEN] == "oauth-refresh"
    assert entry[CONF_EXPIRES_AT] > 0


def test_token_data_to_entry_missing_refresh_token() -> None:
    assert _token_data_to_entry({"access_token": "a"}) is None


def test_token_data_to_entry_missing_access_token() -> None:
    assert _token_data_to_entry({"refresh_token": "r"}) is None


# --- async_step_auth state-validation tests (I1) ---


def _make_auth_flow():
    """Build a ClaudeUsageConfigFlow with HA-session glue mocked."""
    from custom_components.claude_usage.config_flow import ClaudeUsageConfigFlow

    flow = ClaudeUsageConfigFlow()
    flow.hass = MagicMock()
    flow.async_show_form = MagicMock(
        side_effect=lambda **kwargs: {"type": "form", **kwargs}
    )
    flow.async_create_entry = MagicMock(
        side_effect=lambda **kwargs: {"type": "create_entry", **kwargs}
    )
    return flow


@pytest.mark.asyncio
async def test_auth_step_rejects_bare_code_without_state(monkeypatch) -> None:
    """I1: a paste with no `#state` must be rejected, not silently accepted."""
    from custom_components.claude_usage import config_flow as cf

    flow = _make_auth_flow()
    # Prime the flow with known verifier/state so the initial generation is
    # skipped on re-entry (simulates the resubmit path).
    flow._code_verifier = "v" * 64
    flow._state = "expected-state"

    # If the code path ever calls exchange, force-fail the test.
    async def _fail_exchange(*a, **kw):
        raise AssertionError("exchange should not be called without valid state")

    monkeypatch.setattr(cf, "_async_exchange_code", _fail_exchange)

    result = await flow.async_step_auth({"code": "raw-code-no-hash"})

    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_state"}


@pytest.mark.asyncio
async def test_auth_step_rejects_mismatched_state(monkeypatch) -> None:
    """I1: a paste with a non-matching state must be rejected."""
    from custom_components.claude_usage import config_flow as cf

    flow = _make_auth_flow()
    flow._code_verifier = "v" * 64
    flow._state = "expected-state"

    async def _fail_exchange(*a, **kw):
        raise AssertionError("exchange should not be called with bad state")

    monkeypatch.setattr(cf, "_async_exchange_code", _fail_exchange)

    result = await flow.async_step_auth({"code": "the-code#attacker-state"})

    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_state"}


@pytest.mark.asyncio
async def test_auth_step_accepts_matching_state(monkeypatch) -> None:
    """Good path: matching state allows the exchange to proceed."""
    from custom_components.claude_usage import config_flow as cf

    flow = _make_auth_flow()
    flow._code_verifier = "v" * 64
    flow._state = "good-state"
    flow.source = "user"

    async def _ok_exchange(session, code, verifier, *_, **__):
        assert code == "the-code"
        assert verifier == "v" * 64
        return MOCK_CODE_RESPONSE, ""

    monkeypatch.setattr(cf, "_async_exchange_code", _ok_exchange)
    monkeypatch.setattr(
        cf, "async_get_clientsession", lambda _hass: MagicMock()
    )

    result = await flow.async_step_auth({"code": "the-code#good-state"})

    assert result["type"] == "create_entry"


# --- _async_finish branching tests (S7) ---


@pytest.mark.asyncio
async def test_finish_creates_entry_on_initial_setup() -> None:
    from custom_components.claude_usage.config_flow import ClaudeUsageConfigFlow

    flow = ClaudeUsageConfigFlow()
    flow.source = "user"
    flow.async_create_entry = MagicMock(return_value="CREATED")
    flow.async_update_reload_and_abort = MagicMock(return_value="UPDATED")

    result = await flow._async_finish({CONF_ACCESS_TOKEN: "a"})

    assert result == "CREATED"
    flow.async_create_entry.assert_called_once()
    flow.async_update_reload_and_abort.assert_not_called()


@pytest.mark.asyncio
async def test_finish_updates_entry_on_reconfigure() -> None:
    from custom_components.claude_usage.config_flow import ClaudeUsageConfigFlow

    flow = ClaudeUsageConfigFlow()
    flow.source = "reconfigure"
    flow.async_create_entry = MagicMock(return_value="CREATED")
    flow.async_update_reload_and_abort = MagicMock(return_value="UPDATED")
    flow._get_reconfigure_entry = MagicMock(return_value="ENTRY")

    result = await flow._async_finish({CONF_ACCESS_TOKEN: "a"})

    assert result == "UPDATED"
    flow.async_update_reload_and_abort.assert_called_once()
    flow.async_create_entry.assert_not_called()
