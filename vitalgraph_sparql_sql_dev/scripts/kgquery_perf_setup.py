#!/usr/bin/env python3
"""
kgquery_perf_setup.py — Create benchmark space with KGQuery test data.

Imports the identical data creation code from the test suite
(case_create_organizations, case_create_relations) and converts
VitalSigns objects to triples via to_triples(), then bulk-inserts
as quads.  No REST API or VitalGraph server needed.

Usage:
    python vitalgraph_sparql_sql/scripts/kgquery_perf_setup.py [--reset]
"""

import argparse
import asyncio
import logging
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from rdflib import URIRef

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
from vitalgraph_sparql_sql import db

# Import the SAME data definitions and creators used by test_sparql_sql_kgqueries.py
from vitalgraph_client_test.multi_kgentity.case_create_organizations import (
    ORGANIZATIONS, CreateOrganizationsTester,
)
from vitalgraph_client_test.multi_kgentity.case_create_relations import (
    PRODUCTS, CreateRelationsTester,
)
from vitalgraph_client_test.multi_kgentity.case_create_business_events import (
    BUSINESS_EVENTS,
)
from vitalgraph_client_test.client_test_data import ClientTestDataCreator
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGType import KGType
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ===================================================================
# Space / graph constants
# ===================================================================
SPACE_ID = "kgquery_perf"
GRAPH_URI = "urn:kgquery_perf"

# ===================================================================
# Relation type URIs (same as case_create_relations.py)
# ===================================================================
RELATION_TYPE_URIS = {
    'product_entity': 'http://vital.ai/test/kgtype/ProductEntity',
    'makes_product':  'http://vital.ai/test/kgtype/MakesProductRelation',
    'competitor_of':  'http://vital.ai/test/kgtype/CompetitorOfRelation',
    'partner_with':   'http://vital.ai/test/kgtype/PartnerWithRelation',
    'supplies':       'http://vital.ai/test/kgtype/SuppliesRelation',
}

# Relation instance definitions (same as case_create_relations.py)
MAKES_PRODUCT_RELS = [
    ("TechCorp Industries", "Enterprise Software Suite"),
    ("TechCorp Industries", "Cloud Platform Service"),
    ("Global Finance Group", "Financial Analytics Tool"),
    ("Healthcare Solutions Inc", "Medical Imaging System"),
    ("Energy Innovations LLC", "Solar Panel Array"),
    ("Retail Dynamics Corp", "Retail POS System"),
]

COMPETITOR_RELS = [
    ("TechCorp Industries", "Global Finance Group"),
    ("Healthcare Solutions Inc", "Education Systems Ltd"),
    ("Energy Innovations LLC", "Manufacturing Excellence"),
    ("Retail Dynamics Corp", "Transportation Networks"),
]

PARTNER_RELS = [
    ("TechCorp Industries", "Healthcare Solutions Inc"),
    ("Global Finance Group", "Retail Dynamics Corp"),
    ("Energy Innovations LLC", "Education Systems Ltd"),
]

SUPPLIES_RELS = [
    ("Manufacturing Excellence", "Retail Dynamics Corp"),
    ("Energy Innovations LLC", "TechCorp Industries"),
    ("Healthcare Solutions Inc", "Education Systems Ltd"),
]


# ===================================================================
# Convert VitalSigns objects → rdflib quads
# (Same pattern as SparqlSQLBackendAdapter.store_objects)
# ===================================================================

def objects_to_quads(objects, graph_uri):
    """Convert a list of VitalSigns GraphObjects to (s, p, o, g) quads."""
    g = URIRef(graph_uri)
    quads = []
    for obj in objects:
        for s, p, o in obj.to_triples():
            quads.append((s, p, o, g))
    return quads


# ===================================================================
# Build all test data objects (identical to test suite)
# ===================================================================

def build_all_objects():
    """Create all VitalSigns objects using the same code as the test suite."""
    all_objects = []
    org_uris = {}   # name → URI
    product_uris = {}  # name → URI

    # --- 1. Organization entity graphs ---
    # CreateOrganizationsTester.create_organization_entity_graph() doesn't use
    # self.client, so we can pass None.
    org_tester = CreateOrganizationsTester(client=None)
    for i, org_data in enumerate(ORGANIZATIONS):
        reference_id = f"ORG-{i + 1:04d}"
        objects = org_tester.create_organization_entity_graph(
            org_data, reference_id=reference_id, org_index=i,
        )
        entity = next(o for o in objects if isinstance(o, KGEntity))
        org_uris[org_data["name"]] = str(entity.URI)
        all_objects.extend(objects)

    # --- 2. Relation KGTypes ---
    kgtypes = []
    for name, uri in [
        ("ProductEntity", RELATION_TYPE_URIS['product_entity']),
        ("MakesProductRelation", RELATION_TYPE_URIS['makes_product']),
        ("CompetitorOfRelation", RELATION_TYPE_URIS['competitor_of']),
        ("PartnerWithRelation", RELATION_TYPE_URIS['partner_with']),
        ("SuppliesRelation", RELATION_TYPE_URIS['supplies']),
    ]:
        t = KGType()
        t.URI = uri
        t.name = name
        kgtypes.append(t)
    all_objects.extend(kgtypes)

    # --- 3. Product entities (same as CreateRelationsTester.create_product_entities) ---
    for product_data in PRODUCTS:
        product_name_normalized = product_data['name'].lower().replace(' ', '_')
        product = KGEntity()
        product.URI = f"http://vital.ai/test/kgentity/product/{product_name_normalized}"
        product.kGEntityType = RELATION_TYPE_URIS['product_entity']
        product.name = product_data['name']
        product.kGGraphURI = product.URI
        product_uris[product_data['name']] = str(product.URI)

        name_slot = KGTextSlot()
        name_slot.URI = f"urn:slot:{uuid.uuid4()}"
        name_slot.kGSlotType = "http://vital.ai/test/kgtype/ProductNameSlot"
        name_slot.textSlotValue = product_data['name']

        category_slot = KGTextSlot()
        category_slot.URI = f"urn:slot:{uuid.uuid4()}"
        category_slot.kGSlotType = "http://vital.ai/test/kgtype/ProductCategorySlot"
        category_slot.textSlotValue = product_data['category']

        price_slot = KGIntegerSlot()
        price_slot.URI = f"urn:slot:{uuid.uuid4()}"
        price_slot.kGSlotType = "http://vital.ai/test/kgtype/ProductPriceSlot"
        price_slot.integerSlotValue = product_data['price']

        all_objects.extend([product, name_slot, category_slot, price_slot])

    # --- 4. Business events (same as CreateBusinessEventsTester.run_tests) ---
    event_creator = ClientTestDataCreator()
    event_uris = []
    for i, event_data in enumerate(BUSINESS_EVENTS):
        org_uri = org_uris[ORGANIZATIONS[event_data["org_index"]]["name"]]
        event_reference_id = f"EVENT-{i + 1:04d}"
        event_objects = event_creator.create_business_event(
            event_type=event_data["event_type"],
            source_business_uri=org_uri,
            event_name=event_data["event_name"],
            reference_id=event_reference_id,
        )
        event_entity = next(o for o in event_objects if isinstance(o, KGEntity))
        event_uris.append(str(event_entity.URI))
        all_objects.extend(event_objects)

    # --- 5. Relation instances (same as CreateRelationsTester.create_relation_instances) ---
    def _make_rel(src_name, dst_name, rel_type_key, dst_map, tag):
        if src_name in org_uris and dst_name in dst_map:
            rel = Edge_hasKGRelation()
            rel.URI = f"urn:relation:{tag}:{uuid.uuid4()}"
            rel.edgeSource = org_uris[src_name]
            rel.edgeDestination = dst_map[dst_name]
            rel.kGRelationType = RELATION_TYPE_URIS[rel_type_key]
            return rel
        return None

    for src, dst in MAKES_PRODUCT_RELS:
        r = _make_rel(src, dst, 'makes_product', product_uris, 'makes_product')
        if r: all_objects.append(r)

    for src, dst in COMPETITOR_RELS:
        r = _make_rel(src, dst, 'competitor_of', org_uris, 'competitor')
        if r: all_objects.append(r)

    for src, dst in PARTNER_RELS:
        r = _make_rel(src, dst, 'partner_with', org_uris, 'partner')
        if r: all_objects.append(r)

    for src, dst in SUPPLIES_RELS:
        r = _make_rel(src, dst, 'supplies', org_uris, 'supplies')
        if r: all_objects.append(r)

    return all_objects, org_uris, product_uris, event_uris


# ===================================================================
# Main
# ===================================================================

async def main(reset: bool = False):
    print(f"kgquery_perf_setup — space={SPACE_ID}, graph={GRAPH_URI}")

    pool = await db.get_pool()

    async with pool.acquire() as conn:
        tables_exist = await SparqlSQLSchema.space_tables_exist(conn, SPACE_ID)

        if tables_exist and reset:
            print("  Dropping existing space tables …")
            await SparqlSQLSchema.drop_space(conn, SPACE_ID)
            tables_exist = False

        if not tables_exist:
            print("  Creating space tables …")
            await SparqlSQLSchema.create_space(conn, SPACE_ID)
        else:
            print("  Space tables already exist (use --reset to recreate)")

    # Build VitalSigns objects using same code as test suite
    all_objects, org_uris, product_uris, event_uris = build_all_objects()
    print(f"  Created {len(all_objects)} VitalSigns objects")

    # Convert to quads via to_triples() — same as SparqlSQLBackendAdapter.store_objects
    quads = objects_to_quads(all_objects, GRAPH_URI)
    print(f"  Converted to {len(quads)} quads")

    # Use SparqlSQLSpaceImpl for bulk insert
    dev = db.DevDbImpl()
    await dev.connect()

    pg_cfg = db.get_connection_params()
    space_impl = SparqlSQLSpaceImpl(pg_cfg)
    space_impl.db_impl = dev
    space_impl.schema = SparqlSQLSchema()

    t0 = time.monotonic()
    inserted = await space_impl.add_rdf_quads_batch_bulk(SPACE_ID, quads)
    t1 = time.monotonic()
    print(f"  Inserted {inserted} quads in {(t1 - t0) * 1000:.0f}ms")

    # ANALYZE
    t = SparqlSQLSchema.get_table_names(SPACE_ID)
    async with pool.acquire() as conn:
        for tbl in [t['rdf_quad'], t['term'], t['datatype']]:
            await conn.execute(f"ANALYZE {tbl}")
    print("  ANALYZE complete")

    # Verify counts
    async with pool.acquire() as conn:
        quad_count = await conn.fetchval(f"SELECT COUNT(*) FROM {t['rdf_quad']}")
        term_count = await conn.fetchval(f"SELECT COUNT(*) FROM {t['term']}")
    print(f"  Totals: {quad_count} quads, {term_count} terms")

    # Summary
    rel_count = len(MAKES_PRODUCT_RELS) + len(COMPETITOR_RELS) + len(PARTNER_RELS) + len(SUPPLIES_RELS)
    print(f"  Data: {len(org_uris)} orgs, {len(event_uris)} events, "
          f"{len(product_uris)} products, {rel_count} relations")
    print("  Done ✅")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup kgquery_perf benchmark space")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate space")
    args = parser.parse_args()
    asyncio.run(main(reset=args.reset))
