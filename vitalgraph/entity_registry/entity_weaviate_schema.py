"""
Weaviate collection schema for the Entity Registry.

Defines two collections:
  - EntityIndex: entities with semantic search + property filters
  - LocationIndex: locations with geo coordinates + cross-ref to EntityIndex
"""

import os
import uuid
from typing import List

import weaviate.classes.config as wvc


DEFAULT_COLLECTION_PREFIX = "dev"


def get_collection_name(env: str = None) -> str:
    """Return the environment-scoped EntityIndex collection name.

    Uses 'xxx' as separator (underscore is technically allowed but problematic in Weaviate).
    Examples: devxxxEntityIndex, prodxxxEntityIndex, testxxxEntityIndex
    """
    if env is None:
        env = os.getenv('ENTITY_WEAVIATE_ENV', DEFAULT_COLLECTION_PREFIX)
    return f"{env}xxxEntityIndex"


def get_location_collection_name(env: str = None) -> str:
    """Return the environment-scoped LocationIndex collection name."""
    if env is None:
        env = os.getenv('ENTITY_WEAVIATE_ENV', DEFAULT_COLLECTION_PREFIX)
    return f"{env}xxxLocationIndex"


def entity_id_to_weaviate_uuid(entity_id: str) -> str:
    """Deterministic UUID from entity_id for idempotent upserts."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"vitalgraph:entity:{entity_id}"))


def location_id_to_weaviate_uuid(location_id: int) -> str:
    """Deterministic UUID from location_id for idempotent upserts."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"vitalgraph:location:{location_id}"))


def build_locations_text(locations: list) -> str:
    """Build a text summary of entity locations for search enrichment.

    Includes location names and formatted addresses (or component parts).
    """
    if not locations:
        return ""
    loc_parts = []
    for loc in locations:
        name = loc.get('location_name') or ''
        addr = loc.get('formatted_address') or ''
        if not addr:
            addr_components = []
            for f in ('locality', 'admin_area_1', 'country'):
                v = loc.get(f)
                if v:
                    addr_components.append(v)
            addr = ', '.join(addr_components)
        text = f"{name}: {addr}".strip(': ') if name or addr else ''
        if text:
            loc_parts.append(text)
    return '; '.join(loc_parts)


def build_search_text(entity: dict) -> str:
    """Build composite search text for vectorization.

    Concatenates key fields into a single string for a rich embedding:
    "{primary_name}. {type_label}: {type_description}. {description}.
     Categories: {category_labels}. {locality}, {region}, {country}.
     Locations: {location summaries}"
    """
    parts = []
    if entity.get('primary_name'):
        parts.append(entity['primary_name'])
    if entity.get('type_label'):
        type_str = entity['type_label']
        if entity.get('type_description'):
            type_str += f": {entity['type_description']}"
        parts.append(type_str)
    if entity.get('description'):
        parts.append(entity['description'])
    if entity.get('category_labels'):
        parts.append(f"Categories: {entity['category_labels']}")
    return '. '.join(parts)


def build_aliases_text(aliases: List[dict]) -> str:
    """Build pipe-separated alias string from alias dicts."""
    if not aliases:
        return ""
    return '|'.join(a['alias_name'] for a in aliases if a.get('alias_name'))


def build_category_keys(categories: List[dict]) -> List[str]:
    """Extract category keys from category dicts."""
    if not categories:
        return []
    return [c['category_key'] for c in categories if c.get('category_key')]


def build_identifier_keys(identifiers: List[dict]) -> List[str]:
    """Build list of 'namespace:value' composite keys for Weaviate filtering."""
    if not identifiers:
        return []
    keys = []
    for ident in identifiers:
        ns = ident.get('identifier_namespace') or ''
        val = ident.get('identifier_value') or ''
        if val:
            keys.append(f"{ns}:{val}")
    return keys


def build_identifier_values(identifiers: List[dict]) -> List[str]:
    """Extract unique identifier values for cross-namespace filtering."""
    if not identifiers:
        return []
    return list({ident['identifier_value'] for ident in identifiers
                 if ident.get('identifier_value')})


def build_category_labels(categories: List[dict]) -> str:
    """Build pipe-separated category label string."""
    if not categories:
        return ""
    return '|'.join(c['category_label'] for c in categories if c.get('category_label'))


def build_location_search_text(location: dict) -> str:
    """Build composite search text for a location.

    Concatenates: "{location_name}. {location_type_label}. {description}. {formatted_address}"
    """
    parts = []
    if location.get('location_name'):
        parts.append(location['location_name'])
    if location.get('location_type_label'):
        parts.append(location['location_type_label'])
    if location.get('description'):
        parts.append(location['description'])
    if location.get('formatted_address'):
        parts.append(location['formatted_address'])
    return '. '.join(parts)


def location_to_weaviate_properties(location: dict) -> dict:
    """Convert a location dict to Weaviate object properties."""
    props = {
        "location_id": str(location.get('location_id', '')),
        "entity_id": location.get('entity_id', ''),
        "location_type_key": location.get('location_type_key') or '',
        "location_type_label": location.get('location_type_label') or '',
        "location_name": location.get('location_name') or '',
        "description": location.get('description') or '',
        "address_line_1": location.get('address_line_1') or '',
        "address_line_2": location.get('address_line_2') or '',
        "locality": location.get('locality') or '',
        "admin_area_1": location.get('admin_area_1') or '',
        "country": location.get('country') or '',
        "country_code": location.get('country_code') or '',
        "postal_code": location.get('postal_code') or '',
        "formatted_address": location.get('formatted_address') or '',
        "external_location_id": location.get('external_location_id') or '',
        "is_primary": bool(location.get('is_primary', False)),
        "status": location.get('status', 'active'),
        "search_text": build_location_search_text(location),
    }

    lat = location.get('latitude')
    lng = location.get('longitude')
    if lat is not None and lng is not None:
        props["geo_location"] = {
            "latitude": float(lat),
            "longitude": float(lng),
        }

    return props


def entity_to_weaviate_properties(entity: dict) -> dict:
    """Convert an entity dict (with aliases, categories) to Weaviate object properties."""
    aliases = entity.get('aliases', []) or []
    categories = entity.get('categories', []) or []

    aliases_text = build_aliases_text(aliases)
    cat_keys = build_category_keys(categories)
    cat_labels = build_category_labels(categories)

    props = {
        "entity_id": entity['entity_id'],
        "primary_name": entity['primary_name'],
        "description": entity.get('description') or "",
        "aliases": aliases_text,
        "notes": entity.get('notes') or "",
        "type_key": entity.get('type_key') or "",
        "type_label": entity.get('type_label') or "",
        "type_description": entity.get('type_description') or "",
        "country": entity.get('country') or "",
        "region": entity.get('region') or "",
        "locality": entity.get('locality') or "",
        "category_keys": cat_keys,
        "category_labels": cat_labels,
        "website": entity.get('website') or "",
        "status": entity.get('status', 'active'),
    }

    # Add geo coordinates if available
    lat = entity.get('latitude')
    lng = entity.get('longitude')
    if lat is not None and lng is not None:
        props["geo_location"] = {
            "latitude": float(lat),
            "longitude": float(lng),
        }

    # Identifiers
    identifiers = entity.get('identifiers', []) or []
    props["identifier_keys"] = build_identifier_keys(identifiers)
    props["identifier_values"] = build_identifier_values(identifiers)

    # Build composite search text using the denormalized fields
    search_entity = {**entity, 'category_labels': cat_labels}
    props["search_text"] = build_search_text(search_entity)

    return props


def get_collection_config(collection_name: str = None) -> dict:
    """Return the weaviate v4 collection configuration kwargs for EntityIndex.

    Note: The 'locations' cross-reference to LocationIndex is added separately
    after both collections exist (see ensure_collection).

    Usage:
        client.collections.create(**get_collection_config())
    """
    if collection_name is None:
        collection_name = get_collection_name()
    return {
        "name": collection_name,
        "description": "Searchable index of entities from the Entity Registry",
        "vectorizer_config": wvc.Configure.Vectorizer.text2vec_transformers(
            vectorize_collection_name=False,
        ),
        "properties": [
            # Identity (not vectorized)
            wvc.Property(
                name="entity_id",
                data_type=wvc.DataType.TEXT,
                description="Entity Registry ID (e.g. e_abc123)",
                tokenization=wvc.Tokenization.FIELD,
                skip_vectorization=True,
            ),
            # Core fields (vectorized)
            wvc.Property(
                name="primary_name",
                data_type=wvc.DataType.TEXT,
                description="Primary entity name",
                tokenization=wvc.Tokenization.WORD,
            ),
            wvc.Property(
                name="description",
                data_type=wvc.DataType.TEXT,
                description="Entity description (topic/industry text)",
                tokenization=wvc.Tokenization.WORD,
            ),
            wvc.Property(
                name="aliases",
                data_type=wvc.DataType.TEXT,
                description="Pipe-separated alias names",
                tokenization=wvc.Tokenization.WORD,
            ),
            wvc.Property(
                name="notes",
                data_type=wvc.DataType.TEXT,
                description="Free-text notes",
                tokenization=wvc.Tokenization.WORD,
            ),
            # Type fields
            wvc.Property(
                name="type_key",
                data_type=wvc.DataType.TEXT,
                description="Entity type key",
                tokenization=wvc.Tokenization.FIELD,
                skip_vectorization=True,
            ),
            wvc.Property(
                name="type_label",
                data_type=wvc.DataType.TEXT,
                description="Entity type label",
                tokenization=wvc.Tokenization.WORD,
            ),
            wvc.Property(
                name="type_description",
                data_type=wvc.DataType.TEXT,
                description="Entity type description",
                tokenization=wvc.Tokenization.WORD,
            ),
            # Location fields (not vectorized)
            wvc.Property(
                name="country",
                data_type=wvc.DataType.TEXT,
                description="Country code or name",
                tokenization=wvc.Tokenization.FIELD,
                skip_vectorization=True,
            ),
            wvc.Property(
                name="region",
                data_type=wvc.DataType.TEXT,
                description="State/region",
                tokenization=wvc.Tokenization.FIELD,
                skip_vectorization=True,
            ),
            wvc.Property(
                name="locality",
                data_type=wvc.DataType.TEXT,
                description="City/locality",
                tokenization=wvc.Tokenization.FIELD,
                skip_vectorization=True,
            ),
            # Geo coordinates (for radius/bounding-box queries)
            wvc.Property(
                name="geo_location",
                data_type=wvc.DataType.GEO_COORDINATES,
                description="Latitude/longitude for geo range filtering",
                skip_vectorization=True,
            ),
            # Category fields
            wvc.Property(
                name="category_keys",
                data_type=wvc.DataType.TEXT_ARRAY,
                description="Category keys assigned to entity",
                skip_vectorization=True,
            ),
            wvc.Property(
                name="category_labels",
                data_type=wvc.DataType.TEXT,
                description="Pipe-separated category labels",
                tokenization=wvc.Tokenization.WORD,
            ),
            # Identifiers (not vectorized, for exact-match filtering)
            wvc.Property(
                name="identifier_keys",
                data_type=wvc.DataType.TEXT_ARRAY,
                description="Composite namespace:value keys for exact identifier lookup",
                skip_vectorization=True,
            ),
            wvc.Property(
                name="identifier_values",
                data_type=wvc.DataType.TEXT_ARRAY,
                description="Identifier values (cross-namespace lookup)",
                skip_vectorization=True,
            ),
            # Metadata (not vectorized)
            wvc.Property(
                name="website",
                data_type=wvc.DataType.TEXT,
                description="Entity website URL",
                tokenization=wvc.Tokenization.FIELD,
                skip_vectorization=True,
            ),
            wvc.Property(
                name="status",
                data_type=wvc.DataType.TEXT,
                description="Entity status (active, deleted)",
                tokenization=wvc.Tokenization.FIELD,
                skip_vectorization=True,
            ),
            # Composite search field (vectorized)
            wvc.Property(
                name="search_text",
                data_type=wvc.DataType.TEXT,
                description="Concatenated text for vector embedding",
                tokenization=wvc.Tokenization.WORD,
            ),
        ],
    }


def get_location_collection_config(collection_name: str = None) -> dict:
    """Return the weaviate v4 collection configuration kwargs for LocationIndex.

    Note: The 'entity' cross-reference to EntityIndex is added separately
    after both collections exist (see ensure_collection).

    Usage:
        client.collections.create(**get_location_collection_config())
    """
    if collection_name is None:
        collection_name = get_location_collection_name()
    return {
        "name": collection_name,
        "description": "Searchable index of entity locations with geo coordinates",
        "vectorizer_config": wvc.Configure.Vectorizer.text2vec_transformers(
            vectorize_collection_name=False,
        ),
        "properties": [
            # Identity (not vectorized)
            wvc.Property(
                name="location_id",
                data_type=wvc.DataType.TEXT,
                description="PostgreSQL location_id (as string)",
                tokenization=wvc.Tokenization.FIELD,
                skip_vectorization=True,
            ),
            wvc.Property(
                name="entity_id",
                data_type=wvc.DataType.TEXT,
                description="Owning entity ID",
                tokenization=wvc.Tokenization.FIELD,
                skip_vectorization=True,
            ),
            # Type fields
            wvc.Property(
                name="location_type_key",
                data_type=wvc.DataType.TEXT,
                description="Location type key (headquarters, branch, etc.)",
                tokenization=wvc.Tokenization.FIELD,
                skip_vectorization=True,
            ),
            wvc.Property(
                name="location_type_label",
                data_type=wvc.DataType.TEXT,
                description="Location type label",
                tokenization=wvc.Tokenization.WORD,
            ),
            # Core fields (vectorized)
            wvc.Property(
                name="location_name",
                data_type=wvc.DataType.TEXT,
                description="Short display name",
                tokenization=wvc.Tokenization.WORD,
            ),
            wvc.Property(
                name="description",
                data_type=wvc.DataType.TEXT,
                description="Location description",
                tokenization=wvc.Tokenization.WORD,
            ),
            wvc.Property(
                name="formatted_address",
                data_type=wvc.DataType.TEXT,
                description="Full normalized address string",
                tokenization=wvc.Tokenization.WORD,
            ),
            # Address fields (not vectorized)
            wvc.Property(
                name="external_location_id",
                data_type=wvc.DataType.TEXT,
                description="Business-assigned location reference (e.g. building_001)",
                tokenization=wvc.Tokenization.FIELD,
                skip_vectorization=True,
            ),
            wvc.Property(
                name="address_line_1",
                data_type=wvc.DataType.TEXT,
                description="Street address line 1",
                tokenization=wvc.Tokenization.WORD,
                skip_vectorization=True,
            ),
            wvc.Property(
                name="address_line_2",
                data_type=wvc.DataType.TEXT,
                description="Street address line 2",
                tokenization=wvc.Tokenization.WORD,
                skip_vectorization=True,
            ),
            wvc.Property(
                name="locality",
                data_type=wvc.DataType.TEXT,
                description="City/locality",
                tokenization=wvc.Tokenization.FIELD,
                skip_vectorization=True,
            ),
            wvc.Property(
                name="admin_area_1",
                data_type=wvc.DataType.TEXT,
                description="State/province",
                tokenization=wvc.Tokenization.FIELD,
                skip_vectorization=True,
            ),
            wvc.Property(
                name="country",
                data_type=wvc.DataType.TEXT,
                description="Country name",
                tokenization=wvc.Tokenization.FIELD,
                skip_vectorization=True,
            ),
            wvc.Property(
                name="country_code",
                data_type=wvc.DataType.TEXT,
                description="ISO 3166-1 alpha-2 code",
                tokenization=wvc.Tokenization.FIELD,
                skip_vectorization=True,
            ),
            wvc.Property(
                name="postal_code",
                data_type=wvc.DataType.TEXT,
                description="ZIP/postal code",
                tokenization=wvc.Tokenization.FIELD,
                skip_vectorization=True,
            ),
            # Geo coordinates (for radius queries)
            wvc.Property(
                name="geo_location",
                data_type=wvc.DataType.GEO_COORDINATES,
                description="Latitude/longitude for geo range filtering",
                skip_vectorization=True,
            ),
            # Flags
            wvc.Property(
                name="is_primary",
                data_type=wvc.DataType.BOOL,
                description="Whether this is the primary location",
                skip_vectorization=True,
            ),
            wvc.Property(
                name="status",
                data_type=wvc.DataType.TEXT,
                description="Location status (active, removed)",
                tokenization=wvc.Tokenization.FIELD,
                skip_vectorization=True,
            ),
            # Composite search field (vectorized)
            wvc.Property(
                name="search_text",
                data_type=wvc.DataType.TEXT,
                description="Concatenated text for vector embedding",
                tokenization=wvc.Tokenization.WORD,
            ),
        ],
    }
