"""
Entity ID generation for the Entity Registry.

Generates unique, URL-safe entity identifiers with an 'e_' prefix.
"""

import secrets
import string


ALPHABET = string.ascii_lowercase + string.digits  # a-z, 0-9
DEFAULT_LENGTH = 10  # 10 chars after prefix → 36^10 ≈ 3.6 × 10^15 possibilities
PREFIX = 'e_'


def generate_entity_id(length: int = DEFAULT_LENGTH) -> str:
    """
    Generate a unique entity ID like 'e_a7b3x9k2m1'.

    Args:
        length: Number of random characters after the prefix.

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
    """Check if a string is a valid entity ID format."""
    if not entity_id or not entity_id.startswith(PREFIX):
        return False
    suffix = entity_id[len(PREFIX):]
    if len(suffix) != DEFAULT_LENGTH:
        return False
    return all(c in ALPHABET for c in suffix)
