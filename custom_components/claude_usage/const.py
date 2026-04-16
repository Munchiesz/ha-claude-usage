"""Constants for the Claude Usage integration."""

DOMAIN = "claude_usage"

DEFAULT_SCAN_INTERVAL = 300  # seconds (5 minutes)
MIN_SCAN_INTERVAL = 60  # 1 minute
MAX_SCAN_INTERVAL = 1800  # 30 minutes

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
AUTH_REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
# WARNING: This is the Claude Code OAuth client ID, not one registered for this
# integration. Anthropic may revoke or restrict it at any time, which would break
# token refresh for all installations.
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
TOKEN_SCOPES = "user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload"
# Scopes requested on the authorize call — matches what the Claude Code CLI asks
# for with this same client ID.
OAUTH_AUTHORIZE_SCOPES = "org:create_api_key user:profile user:inference"
# Default access-token lifetime (8h) used as a fallback when the token response
# omits `expires_in`.
DEFAULT_TOKEN_LIFETIME_SECS = 28800
TOKEN_REFRESH_BUFFER_SECS = 300  # refresh when token expires within 5 min

CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES_AT = "expires_at"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_CLIENT_ID = "client_id"
