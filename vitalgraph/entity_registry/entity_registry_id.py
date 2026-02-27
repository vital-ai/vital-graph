"""
Entity ID generation and validation for the Entity Registry.

Entity ID format:
    {prefix}_{suffix}
    - prefix: 1–4 alphanumeric characters (a-z, 0-9)
    - suffix: exactly 10 alphanumeric characters (a-z, 0-9)
    - max total length: 15 characters

Examples of valid entity IDs:
    e_a7b3x9k2m1       (system-generated)
    ab_1234567890       (2-char external prefix)
    crm_abcdef1234      (4-char external prefix)
    ent1_9999999999     (4-char alphanumeric prefix)

The system generates IDs with prefix 'e_'. All other prefixes (1–4 chars)
are reserved for externally-managed IDs (bulk imports, CRM systems, etc.)
and will never be produced by generate_entity_id().
"""

import re
import secrets
import string


ALPHABET = string.ascii_lowercase + string.digits  # a-z, 0-9
SUFFIX_LENGTH = 10  # exactly 10 chars after prefix → 36^10 ≈ 3.6 × 10^15 possibilities
DEFAULT_LENGTH = SUFFIX_LENGTH  # backwards compat
PREFIX = 'e_'
MAX_ID_LENGTH = 15  # 4 (max prefix) + 1 (_) + 10 (suffix)

# Pattern: 1-4 lowercase alphanums, underscore, exactly 10 lowercase alphanums
_ENTITY_ID_RE = re.compile(r'^[a-z0-9]{1,4}_[a-z0-9]{10}$')


def generate_entity_id(length: int = SUFFIX_LENGTH) -> str:
    """
    Generate a unique entity ID like 'e_a7b3x9k2m1'.

    Always uses the 'e_' prefix. Other prefixes are reserved for
    externally-managed IDs.

    Args:
        length: Number of random characters after the prefix (default 10).

    Returns:
        String entity ID with 'e_' prefix.
    """
    suffix = ''.join(secrets.choice(ALPHABET) for _ in range(length))
    return f"{PREFIX}{suffix}"


def entity_id_to_uri(entity_id: str) -> str:
    """Convert entity ID to URN format: urn:entity:<entity_id>."""
    return f"urn:entity:{entity_id}"


def uri_to_entity_id(uri: str) -> str:
    """
    Extract entity ID from URN format.

    Args:
        uri: URN string like 'urn:entity:e_a7b3x9k2m1'

    Returns:
        Entity ID string like 'e_a7b3x9k2m1'

    Raises:
        ValueError: If URI is not in expected format.
    """
    urn_prefix = 'urn:entity:'
    if not uri.startswith(urn_prefix):
        raise ValueError(f"Invalid entity URI format: {uri}. Expected 'urn:entity:<id>'")
    return uri[len(urn_prefix):]


def is_valid_entity_id(entity_id: str) -> bool:
    """Check if a string is a valid entity ID format.

    Valid format: 1-4 lowercase alphanumeric prefix + '_' + exactly 10
    lowercase alphanumeric suffix. Max length 15.

    Examples:
        e_a7b3x9k2m1    → True   (system-generated)
        crm_abcdef1234  → True   (4-char external prefix)
        ent1_9999999999 → True   (alphanumeric prefix)
        abcde_1234567890→ False  (prefix too long: 5 chars)
        e_abc           → False  (suffix too short)
        E_A7B3X9K2M1   → False  (uppercase not allowed)
    """
    if not entity_id:
        return False
    return bool(_ENTITY_ID_RE.match(entity_id))
