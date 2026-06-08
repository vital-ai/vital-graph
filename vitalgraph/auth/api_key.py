"""
API Key generation and validation utilities.

Keys have the format: vg_<prefix><suffix>
- prefix: 8 alphanumeric chars (stored in DB for fast lookup)
- suffix: 29 alphanumeric chars
- Total: 3 (vg_) + 8 + 29 = 40 chars

Only the bcrypt hash of the full key is stored; the plaintext is shown once at creation.
"""

import secrets
import string
from typing import Optional, Tuple

from .password import hash_password, verify_password

API_KEY_PREFIX = "vg_"
API_KEY_PREFIX_LEN = 8  # chars after "vg_" used as lookup prefix
API_KEY_SUFFIX_LEN = 29
API_KEY_TOTAL_LEN = len(API_KEY_PREFIX) + API_KEY_PREFIX_LEN + API_KEY_SUFFIX_LEN  # 40

_ALPHABET = string.ascii_letters + string.digits


def generate_api_key() -> Tuple[str, str]:
    """Generate a new API key.

    Returns:
        (full_key, prefix) where full_key is shown once to the user
        and prefix is stored for fast DB lookup.
    """
    prefix = ''.join(secrets.choice(_ALPHABET) for _ in range(API_KEY_PREFIX_LEN))
    suffix = ''.join(secrets.choice(_ALPHABET) for _ in range(API_KEY_SUFFIX_LEN))
    full_key = f"{API_KEY_PREFIX}{prefix}{suffix}"
    return full_key, prefix


def hash_api_key(full_key: str) -> str:
    """Hash an API key for storage (bcrypt)."""
    return hash_password(full_key)


def verify_api_key(full_key: str, key_hash: str) -> bool:
    """Verify a full API key against its stored hash."""
    return verify_password(full_key, key_hash)


def extract_prefix(token: str) -> Optional[str]:
    """Extract the lookup prefix from a vg_ token.

    Returns None if the token is not a valid API key format.
    """
    if not token.startswith(API_KEY_PREFIX):
        return None
    if len(token) != API_KEY_TOTAL_LEN:
        return None
    return token[len(API_KEY_PREFIX):len(API_KEY_PREFIX) + API_KEY_PREFIX_LEN]


def is_api_key(token: str) -> bool:
    """Check if a token looks like an API key (starts with vg_)."""
    return token.startswith(API_KEY_PREFIX)
