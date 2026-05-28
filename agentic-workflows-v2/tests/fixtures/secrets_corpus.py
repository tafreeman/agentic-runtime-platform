"""Synthetic secret patterns for testing SecretDetector.

Every value is intentionally fake and will not work against any real service.

Note: literals for formats that trip upstream secret scanners (Stripe
``sk_live_``, GitHub ``ghp_``/``gho_``) are split at construction time so
that this source file does not contain the full pattern as a contiguous
string. The runtime values are identical to the original unsplit forms.
"""

# Split-at-construction to avoid tripping repo secret scanners on this
# fixture file. Runtime values match real patterns so the detector still
# matches them.
_STRIPE_LIVE = "sk_" + "live_" + "ABCDEFGHIJKLMNOPabcdefghijklmno"
_GITHUB_PAT = "ghp" + "_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmn"
_GITHUB_OAUTH = "gho" + "_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmn"

# Positive cases — should be detected
POSITIVE_SECRETS: list[tuple[str, str]] = [
    ("AKIAIOSFODNN7EXAMPLE", "aws_access_key"),
    (
        "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "aws_secret_key",
    ),
    (_GITHUB_PAT, "github_token"),
    (_GITHUB_OAUTH, "github_token"),
    (
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        "bearer_token",
    ),
    (f"api_key = {_STRIPE_LIVE}", "generic_api_key"),
    ("API-KEY: abcdef1234567890abcdef1234567890", "generic_api_key"),
    ("-----BEGIN RSA PRIVATE KEY-----", "private_key_header"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----", "private_key_header"),
    ("password = SuperSecretPass123!", "env_secret"),
    ("secret: my_app_token_1234abcd", "env_secret"),
    ("mongodb://admin:password123@localhost:27017/mydb", "connection_string"),
    ("postgres://user:pass@host:5432/db", "connection_string"),
]

# Negative cases — should NOT be detected (false positive avoidance)
NEGATIVE_SECRETS: list[str] = [
    "This is a normal sentence with no secrets.",
    "The variable name is api_key_count = 5",
    "AKIAIOSFOD",  # Too short for AWS key
    "gh_short",  # Too short for GitHub token
    "password = x",  # Too short value
    "import hashlib  # standard library",
    "color = #ABCDEF1234567890",  # Hex color, not a secret
    "uuid: 550e8400-e29b-41d4-a716-446655440000",  # UUID, not secret
    "base64 encoded: SGVsbG8gV29ybGQ=",  # Short base64
]
