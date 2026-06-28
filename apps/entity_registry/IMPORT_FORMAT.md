# Entity Registry Import Format

## Overview

The Entity Registry bulk import uses **JSONL** (JSON Lines) — one JSON object per
line. There are six file types, split into two groups:

**Reference type files** (small, loaded into memory):

1. **Entity types** — defines `type_key` values for entities
2. **Categories** — defines `category_key` values for entity categorization
3. **Location types** — defines `type_key` values for entity locations
4. **Relationship types** — defines `type_key` values for entity relationships

**Data files** (potentially large, streamed line-by-line):

5. **Entities** — one entity per line with nested aliases, identifiers, categories, locations
6. **Relationships** — one relationship per line, processed after all entities

All files can be generated from an existing database using:

```bash
# Export everything to a directory
python entity_registry/entity_export_jsonl.py --all ./export/

# Or individually
python entity_registry/entity_export_jsonl.py \
    --entity-types entity_types.jsonl \
    --categories categories.jsonl \
    --location-types location_types.jsonl \
    --relationship-types relationship_types.jsonl \
    --entities entities.jsonl \
    --relationships relationships.jsonl
```

---

## Import Order and Validation

Files must be processed in this order:

```
1. entity_types.jsonl        (small, load into memory)
2. categories.jsonl           (small, load into memory)
3. location_types.jsonl       (small, load into memory)
4. relationship_types.jsonl   (small, load into memory)
5. entities.jsonl             (large, streamed)
6. relationships.jsonl        (large, streamed)
```

### Two-Pass Processing (required)

The import always performs **two full passes** over each data file:

**Pass 1 — Validation (no writes):**

Stream the entire file line-by-line, validating every record against the
in-memory reference type sets. Entity IDs are also validated against the
database in batches (default 1000 IDs per query) to detect collisions.
Collect all errors. If any errors are found, report them to the error log
and **abort before any database writes**. This guarantees zero partial imports.

**Pass 2 — Insert (after validation succeeds):**

Stream the file a second time, accumulating records into batches of a
configurable size (default 100, set via `--batch-size`). Each batch is
inserted into PostgreSQL in a single transaction using `executemany`.
Since all records were validated in Pass 1, foreign key violations from
missing types are impossible.

The two-pass approach is required because data files may be arbitrarily large
(millions of lines) and cannot be held in memory. Streaming twice is cheap —
Pass 1 is JSON parse + set lookups + batched ID existence checks.

### Pre-Scan Details (Pass 1)

Before starting the validation pass, the import script must:

1. **Load current reference types from the database** — query `entity_type`,
   `category`, `entity_location_type`, and `relationship_type` tables into
   in-memory sets. These are always small (tens of rows).

2. **Load reference type files** (if provided) — insert new types into the
   database first, then merge them into the in-memory sets. These are also
   small and can be fully loaded into memory.

3. **Stream-scan the entity file** — read each line and check that:
   - `entity_id` is present and well-formed
   - `entity_id` does not already exist in the database (checked in batches
     of 1000 IDs at a time via `SELECT entity_id FROM entity WHERE entity_id = ANY($1)`)
   - `entity_id` is not duplicated within the file
   - `type_key` exists in the entity types set
   - Each `categories[]` entry exists in the categories set
   - Each `locations[].location_type` exists in the location types set
   - JSON is well-formed and required fields (`entity_id`, `type_key`, `primary_name`) exist
   - Collect all errors with line numbers

4. **Stream-scan the relationship file** (if provided) — check that:
   - `source` and `destination` are valid entity IDs (format check)
   - `type_key` exists in the relationship types set
   - JSON is well-formed and required fields exist

If any errors are found, report them all and stop. No data is written.

```
$ python entity_registry/entity_import_jsonl.py \
    --entities data.jsonl --dry-run --error-log errors.jsonl

Pass 1 — Validation:
  Entities:  1,250,000 lines scanned
  Duplicate entity_id in file:                ← line 89002 (e_abc123)
  entity_id already in database:              ← line 4521 (e_xyz789)
  Missing entity types: ['vendor_intl']       ← line 4521, 89002
  Missing categories:   ['premium_client']    ← line 12044
  Missing location types: (none)
  Malformed JSON:                             ← line 500321
Validation FAILED — 5 errors. No data was written.
Errors written to: errors.jsonl
```

The `--dry-run` flag runs only Pass 1 and exits.

### Why Reference Types Are Separate Files

- **Portability** — type definitions can be shared across environments
  (dev → staging → prod) independent of entity data
- **Pre-creation** — types must exist before entities that reference them;
  loading them first avoids foreign key violations
- **Small and reviewable** — typically < 50 rows each, safe to load fully
  into memory and easy to audit
- **Idempotent** — imported with `ON CONFLICT DO NOTHING` or `DO UPDATE`,
  so re-importing is safe

---

## Reference Type Files

### Entity Types

One entity type per line.

```json
{"type_key": "person", "type_label": "Person", "type_description": "An individual person"}
{"type_key": "business", "type_label": "Business", "type_description": "A business or company"}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type_key` | string | **Yes** | Unique key (e.g. `person`, `business`). |
| `type_label` | string | **Yes** | Human-readable label. |
| `type_description` | string | No | Description. |

Sample: `entity_registry/sample_entity_types.jsonl`

### Categories

One category per line.

```json
{"category_key": "customer", "category_label": "Customer", "category_description": "A customer or client"}
{"category_key": "vendor", "category_label": "Vendor", "category_description": "A vendor or supplier"}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `category_key` | string | **Yes** | Unique key. |
| `category_label` | string | **Yes** | Human-readable label. |
| `category_description` | string | No | Description. |

Sample: `entity_registry/sample_categories.jsonl`

### Location Types

One location type per line.

```json
{"type_key": "headquarters", "type_label": "Headquarters", "type_description": "Primary headquarters"}
{"type_key": "branch", "type_label": "Branch Office", "type_description": "A branch or satellite office"}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type_key` | string | **Yes** | Unique key. |
| `type_label` | string | **Yes** | Human-readable label. |
| `type_description` | string | No | Description. |

Sample: `entity_registry/sample_location_types.jsonl`

### Relationship Types

One relationship type per line.

```json
{"type_key": "employer_of", "type_label": "Employer Of", "type_description": "Employs a person", "inverse_key": "employee_of"}
{"type_key": "employee_of", "type_label": "Employee Of", "type_description": "Employed by an organization", "inverse_key": "employer_of"}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type_key` | string | **Yes** | Unique key. |
| `type_label` | string | **Yes** | Human-readable label. |
| `type_description` | string | No | Description. |
| `inverse_key` | string | No | Key of the inverse relationship type. |

Sample: `entity_registry/sample_relationship_types.jsonl`

---

## Entity File

Each line is a self-contained JSON object representing one entity and all its
associated data (aliases, identifiers, categories, locations).

### Minimal Example

```json
{"entity_id": "e_a7b3x9k2m1", "type_key": "business", "primary_name": "Acme Corporation"}
```

### Full Example

```json
{
  "entity_id": "e_a7b3x9k2m1",
  "type_key": "business",
  "primary_name": "Acme Corporation",
  "description": "A manufacturing company",
  "country": "US",
  "region": "California",
  "locality": "San Francisco",
  "website": "https://acme.example.com",
  "latitude": 37.7749,
  "longitude": -122.4194,
  "metadata": {"founding_year": 1985, "employee_count": 450},
  "notes": "Imported from CRM system",
  "created_by": "bulk_import_2026",
  "aliases": [
    {"alias_name": "Acme Corp", "alias_type": "abbreviation"},
    {"alias_name": "ACME", "alias_type": "dba", "is_primary": true}
  ],
  "identifiers": [
    {"namespace": "DUNS", "value": "123456789", "is_primary": true},
    {"namespace": "EIN", "value": "47-1234567"}
  ],
  "categories": ["customer", "vendor"],
  "locations": [
    {
      "location_type": "headquarters",
      "location_name": "Acme HQ",
      "address_line_1": "100 Market Street",
      "address_line_2": "Suite 3200",
      "locality": "San Francisco",
      "admin_area_2": "San Francisco County",
      "admin_area_1": "California",
      "country": "United States",
      "country_code": "US",
      "postal_code": "94105",
      "formatted_address": "100 Market St, Suite 3200, San Francisco, CA 94105, US",
      "latitude": 37.7936,
      "longitude": -122.3950,
      "timezone": "America/Los_Angeles",
      "google_place_id": "ChIJ...",
      "effective_from": "2020-01-01",
      "is_primary": true
    }
  ]
}
```

### Entity Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_id` | string | **Yes** | Must be provided. Validated for uniqueness in the database and within the file during pre-scan. See **Reserved ID Ranges** below. |
| `type_key` | string | **Yes** | Must match an existing entity type: `person`, `business`, `organization`, `government`, or any custom type. |
| `primary_name` | string | **Yes** | The entity's canonical name. |
| `description` | string | No | Free-text description. |
| `country` | string | No | Country name or ISO code (e.g. `US`, `DE`). |
| `region` | string | No | State, province, or region. |
| `locality` | string | No | City or locality. |
| `website` | string | No | URL. |
| `latitude` | float | No | Entity-level latitude (-90 to 90). |
| `longitude` | float | No | Entity-level longitude (-180 to 180). |
| `metadata` | object | No | Arbitrary JSON metadata (stored as JSONB). |
| `notes` | string | No | Internal notes. |
| `created_by` | string | No | Identifier of who/what created this record. Defaults to `bulk_load`. |
| `aliases` | array | No | List of alias objects (see below). |
| `identifiers` | array | No | List of identifier objects (see below). |
| `categories` | array | No | List of category key strings (see below). |
| `locations` | array | No | List of location objects (see below). |

### Alias Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `alias_name` | string | **Yes** | The alias text. |
| `alias_type` | string | No | Type of alias. Default: `aka`. Common values: `aka`, `abbreviation`, `dba`, `legal`, `nickname`, `former`. |
| `is_primary` | boolean | No | Whether this is the primary alias. Default: `false`. |
| `notes` | string | No | Notes about this alias. |

### Identifier Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `namespace` | string | **Yes** | Identifier namespace (e.g. `DUNS`, `EIN`, `LEI`, `CRD`, `SEC_CIK`, `CUSIP`). |
| `value` | string | **Yes** | The identifier value. |
| `is_primary` | boolean | No | Whether this is the primary identifier in its namespace. Default: `false`. |
| `notes` | string | No | Notes about this identifier. |

### Categories

A flat array of `category_key` strings. Each key must match an existing category
in the database.

**Seed categories:** `customer`, `partner`, `vendor`, `competitor`, `prospect`,
`investor`, `regulator`.

```json
"categories": ["customer", "vendor"]
```

### Location Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `location_type` | string | **Yes** | Must match an existing location type: `headquarters`, `branch`, `warehouse`, `mailing`, `residence`, `registered`. |
| `location_name` | string | No | Display name for this location. |
| `description` | string | No | Description of this location. |
| `address_line_1` | string | No | Street address line 1. |
| `address_line_2` | string | No | Street address line 2. |
| `locality` | string | No | City. |
| `admin_area_2` | string | No | County or district. |
| `admin_area_1` | string | No | State or province. |
| `country` | string | No | Country name. |
| `country_code` | string | No | ISO 2-letter country code (e.g. `US`, `GB`). |
| `postal_code` | string | No | Postal or ZIP code. |
| `formatted_address` | string | No | Full formatted address string. |
| `latitude` | float | No | Location latitude. |
| `longitude` | float | No | Location longitude. |
| `timezone` | string | No | IANA timezone (e.g. `America/New_York`). |
| `google_place_id` | string | No | Google Maps Place ID. |
| `effective_from` | string | No | Start date (ISO format `YYYY-MM-DD`). |
| `effective_to` | string | No | End date (ISO format `YYYY-MM-DD`). |
| `is_primary` | boolean | No | Whether this is the entity's primary location. Default: `false`. |
| `notes` | string | No | Notes about this location. |

---

## Relationship File

Each line is a JSON object representing one relationship between two entities.
The relationship file is processed **after** all entities are loaded, since both
endpoints must exist.

### Example

```json
{"source": "e_a7b3x9k2m1", "destination": "e_x2y4z6w8m0", "type_key": "employer_of", "description": "Since 2020", "start_datetime": "2020-01-15T00:00:00Z"}
```

### Relationship Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source` | string | **Yes** | Source entity ID (e.g. `e_a7b3x9k2m1`). Must exist in the database. |
| `destination` | string | **Yes** | Destination entity ID (e.g. `e_x2y4z6w8m0`). Must exist in the database. |
| `type_key` | string | **Yes** | Must match an existing relationship type (see below). |
| `description` | string | No | Description of the relationship. |
| `start_datetime` | string | No | Start timestamp (ISO 8601). |
| `end_datetime` | string | No | End timestamp (ISO 8601). |
| `created_by` | string | No | Who created this relationship. |
| `notes` | string | No | Internal notes. |

### Seed Relationship Types

| `type_key` | Label | Inverse |
|------------|-------|---------|
| `parent_of` | Parent Of | `subsidiary_of` |
| `subsidiary_of` | Subsidiary Of | `parent_of` |
| `employer_of` | Employer Of | `employee_of` |
| `employee_of` | Employee Of | `employer_of` |
| `investor_in` | Investor In | `funded_by` |
| `funded_by` | Funded By | `investor_in` |
| `partner_of` | Partner Of | `partner_of` |
| `advisor_to` | Advisor To | `advised_by` |
| `advised_by` | Advised By | `advisor_to` |
| `supplier_to` | Supplier To | `customer_of` |
| `customer_of` | Customer Of | `supplier_to` |
| `board_member_of` | Board Member Of | `has_board_member` |
| `has_board_member` | Has Board Member | `board_member_of` |

---

## Seed / Reference Values

These are the default seed values created by the schema migration. Custom types
can be added via the reference type files above.

### Default Entity Types

| `type_key` | Label |
|------------|-------|
| `person` | Person |
| `business` | Business |
| `organization` | Organization |
| `government` | Government |

### Default Categories

| `category_key` | Label |
|----------------|-------|
| `customer` | Customer |
| `partner` | Partner |
| `vendor` | Vendor |
| `competitor` | Competitor |
| `prospect` | Prospect |
| `investor` | Investor |
| `regulator` | Regulator |

### Default Location Types

| `type_key` | Label |
|------------|-------|
| `headquarters` | Headquarters |
| `branch` | Branch Office |
| `warehouse` | Warehouse |
| `mailing` | Mailing Address |
| `residence` | Residence |
| `registered` | Registered Office |

### Default Relationship Types

| `type_key` | Label | Inverse |
|------------|-------|----------|
| `parent_of` | Parent Of | `subsidiary_of` |
| `subsidiary_of` | Subsidiary Of | `parent_of` |
| `employer_of` | Employer Of | `employee_of` |
| `employee_of` | Employee Of | `employer_of` |
| `investor_in` | Investor In | `funded_by` |
| `funded_by` | Funded By | `investor_in` |
| `partner_of` | Partner Of | `partner_of` |
| `advisor_to` | Advisor To | `advised_by` |
| `advised_by` | Advised By | `advisor_to` |
| `supplier_to` | Supplier To | `customer_of` |
| `customer_of` | Customer Of | `supplier_to` |
| `board_member_of` | Board Member Of | `has_board_member` |
| `has_board_member` | Has Board Member | `board_member_of` |

### Alias Types (conventions, not enforced)

| Value | Usage |
|-------|-------|
| `aka` | Also known as (default) |
| `abbreviation` | Short form (e.g. IBM, GE) |
| `dba` | Doing business as |
| `legal` | Legal / registered name |
| `nickname` | Informal name |
| `former` | Former / historical name |

---

## Validation Rules

1. `entity_id` is **required** on every entity. Must not exist in the database or appear more than once in the file.
2. `type_key` must match an existing `entity_type` record.
3. Each `categories[]` entry must match an existing `category.category_key`.
4. Each `locations[].location_type` must match an existing `entity_location_type.type_key`.
5. Each relationship `type_key` must match an existing `relationship_type.type_key`.
6. Both `source` and `destination` in relationships must be valid entity IDs that exist in the database (including entities inserted earlier in the same import).
7. `latitude` must be between -90 and 90; `longitude` between -180 and 180.
8. Date fields must be ISO format (`YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SSZ`).

---

## Reserved Entity ID Ranges

Certain entity ID prefixes are reserved for externally-managed IDs so that they
will never collide with randomly generated IDs (which use the `e_` prefix +
10-char random suffix).

| Prefix | Purpose |
|--------|---------|
| `e_` | System-generated (random, 10-char suffix) |
| `ext_` | Reserved for external systems |
| `imp_` | Reserved for bulk imports with external ID schemes |
| *custom* | Additional prefixes can be registered as needed |

The `generate_entity_id()` function in `entity_registry_id.py` only produces
`e_`-prefixed IDs, so any other prefix is safe for external use.

---

## Changelog

The import script writes a **single** changelog entry per import run (not per
entity). The entry includes the import file path and the number of entities
and relationships imported.

```json
{
  "action": "bulk_import",
  "file_path": "/data/imports/entities_2026-02.jsonl",
  "entities_imported": 125000,
  "relationships_imported": 48000,
  "created_by": "bulk_import"
}
```

---

## Error Log

When validation fails (or with `--error-log`), errors are written to a JSONL
file with one error per line:

```json
{"line": 4521, "file": "entities.jsonl", "field": "entity_id", "error": "already exists in database", "value": "e_xyz789"}
{"line": 12044, "file": "entities.jsonl", "field": "categories", "error": "unknown category_key", "value": "premium_client"}
```

---

## Import Script

The import script is `entity_registry/entity_import_jsonl.py` (separate from
`entity_admin.py`).

```bash
python entity_registry/entity_import_jsonl.py \
    --entity-types export/entity_types.jsonl \
    --categories export/categories.jsonl \
    --location-types export/location_types.jsonl \
    --relationship-types export/relationship_types.jsonl \
    --entities export/entities.jsonl \
    --relationships export/relationships.jsonl \
    --batch-size 100 \
    --error-log errors.jsonl
```

| Flag | Default | Description |
|------|---------|-------------|
| `--entities` | — | Path to entity JSONL file (required) |
| `--relationships` | — | Path to relationship JSONL file |
| `--entity-types` | — | Path to entity types JSONL file |
| `--categories` | — | Path to categories JSONL file |
| `--location-types` | — | Path to location types JSONL file |
| `--relationship-types` | — | Path to relationship types JSONL file |
| `--batch-size` | 100 | Number of records per INSERT batch |
| `--dry-run` | — | Run Pass 1 validation only, no writes |
| `--error-log` | — | Path to write validation errors (JSONL) |

The script does **not** trigger dedup or Weaviate index rebuilds. Use the
admin rebuild endpoint or `entity_admin.py` commands separately after import.

---

## Export → Edit → Import Round-Trip

```bash
# Export everything
python entity_registry/entity_export_jsonl.py --all ./export/

# Edit externally (spreadsheet, script, etc.)

# Import
python entity_registry/entity_import_jsonl.py \
    --entity-types export/entity_types.jsonl \
    --categories export/categories.jsonl \
    --location-types export/location_types.jsonl \
    --relationship-types export/relationship_types.jsonl \
    --entities export/entities.jsonl \
    --relationships export/relationships.jsonl \
    --error-log errors.jsonl

# Rebuild indexes separately
python entity_registry/entity_admin.py dedup-sync
python entity_registry/entity_admin.py weaviate-rebuild
```

---

## Sample Files

All sample files are in the `entity_registry/` directory:

| File | Description |
|------|-------------|
| `sample_entity_types.jsonl` | 4 seed entity types |
| `sample_categories.jsonl` | 7 seed categories |
| `sample_location_types.jsonl` | 6 seed location types |
| `sample_relationship_types.jsonl` | 13 seed relationship types |
| `sample_entities.jsonl` | 101 entities from test data |
| `sample_relationships.jsonl` | 5 relationships from test data |
