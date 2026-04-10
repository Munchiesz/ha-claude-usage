"""Constants for the Claude Usage integration."""

DOMAIN = "claude_usage"

DEFAULT_SCAN_INTERVAL = 300  # seconds (5 minutes)
MIN_SCAN_INTERVAL = 60  # 1 minute
MAX_SCAN_INTERVAL = 1800  # 30 minutes

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
AUTHORIZE_URL = "https://platform.claude.com/v1/oauth/authorize"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
TOKEN_SCOPES = "user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload"
TOKEN_REFRESH_BUFFER_SECS = 300  # refresh when token expires within 5 min

CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES_AT = "expires_at"
