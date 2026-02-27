#!/usr/bin/env python3
"""
Falsey Values Trace Test

Traces exactly where boolean `false` and float `0.0` values get dropped
during entity graph creation. Tests each layer of the pipeline:

1. VitalSigns object creation (client-side)
2. to_jsonld() conversion (client-side)
3. Pydantic model serialization (client-side)
4. HTTP POST body (wire format)
5. Server-side VitalSigns round-trip
6. to_rdf() conversion (server-side)
7. Fuseki storage verification

Usage:
    /opt/homebrew/anaconda3/envs/vital-graph/bin/python vitalgraph_client_test/test_falsey_values_trace.py
"""

import asyncio
import json
import logging
import sys
import httpx
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# VitalSigns imports
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject

# KG domain imports
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGBooleanSlot import KGBooleanSlot
from ai_haley_kg_domain.model.KGCurrencySlot import KGCurrencySlot
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot

# Client imports
from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.jsonld_model import JsonLdObject, JsonLdDocument


SPACE_ID = "space_falsey_test"
GRAPH_ID = "urn:falsey_test"
ENTITY_URI = "urn:test:falsey:entity:1"
FRAME_URI = "urn:test:falsey:frame:1"
BOOL_SLOT_URI = "urn:test:falsey:slot:boolean_false"
CURRENCY_SLOT_URI = "urn:test:falsey:slot:currency_zero"
TEXT_SLOT_URI = "urn:test:falsey:slot:text_nonempty"
EDGE_ENTITY_FRAME_URI = "urn:test:falsey:edge:entity_frame"
EDGE_FRAME_BOOL_SLOT_URI = "urn:test:falsey:edge:frame_bool_slot"
EDGE_FRAME_CURRENCY_SLOT_URI = "urn:test:falsey:edge:frame_currency_slot"
EDGE_FRAME_TEXT_SLOT_URI = "urn:test:falsey:edge:frame_text_slot"


def create_test_objects():
    """Create a minimal entity graph with falsey slot values."""
    
    # Entity
    entity = KGEntity()
    entity.URI = ENTITY_URI
    entity.name = "Falsey Test Entity"
    
    # Frame
    frame = KGFrame()
    frame.URI = FRAME_URI
    frame.name = "Test Frame"
    
    # Boolean slot with FALSE value (the bug)
    bool_slot = KGBooleanSlot()
    bool_slot.URI = BOOL_SLOT_URI
    bool_slot.booleanSlotValue = False
    bool_slot.name = "Boolean False Slot"
    
    # Currency slot with 0.0 value (the bug)
    currency_slot = KGCurrencySlot()
    currency_slot.URI = CURRENCY_SLOT_URI
    currency_slot.currencySlotValue = 0.0
    currency_slot.name = "Currency Zero Slot"
    
    # Text slot with a non-empty value (control - should work)
    text_slot = KGTextSlot()
    text_slot.URI = TEXT_SLOT_URI
    text_slot.textSlotValue = "hello"
    text_slot.name = "Text Slot"
    
    # Edge: Entity -> Frame
    edge_ef = Edge_hasEntityKGFrame()
    edge_ef.URI = EDGE_ENTITY_FRAME_URI
    edge_ef.edgeSource = ENTITY_URI
    edge_ef.edgeDestination = FRAME_URI
    
    # Edge: Frame -> Boolean Slot
    edge_fb = Edge_hasKGSlot()
    edge_fb.URI = EDGE_FRAME_BOOL_SLOT_URI
    edge_fb.edgeSource = FRAME_URI
    edge_fb.edgeDestination = BOOL_SLOT_URI
    
    # Edge: Frame -> Currency Slot
    edge_fc = Edge_hasKGSlot()
    edge_fc.URI = EDGE_FRAME_CURRENCY_SLOT_URI
    edge_fc.edgeSource = FRAME_URI
    edge_fc.edgeDestination = CURRENCY_SLOT_URI
    
    # Edge: Frame -> Text Slot
    edge_ft = Edge_hasKGSlot()
    edge_ft.URI = EDGE_FRAME_TEXT_SLOT_URI
    edge_ft.edgeSource = FRAME_URI
    edge_ft.edgeDestination = TEXT_SLOT_URI
    
    return [entity, frame, bool_slot, currency_slot, text_slot, edge_ef, edge_fb, edge_fc, edge_ft]


def trace_step(step_num, title, detail=""):
    logger.info(f"\n{'='*80}")
    logger.info(f"  STEP {step_num}: {title}")
    if detail:
        logger.info(f"  {detail}")
    logger.info(f"{'='*80}")


async def main():
    tests_passed = 0
    tests_failed = 0
    
    trace_step(1, "Create VitalSigns objects with falsey values")
    
    objects = create_test_objects()
    
    # Verify the VitalSigns objects have the correct values
    bool_slot = [o for o in objects if isinstance(o, KGBooleanSlot)][0]
    currency_slot = [o for o in objects if isinstance(o, KGCurrencySlot)][0]
    text_slot = [o for o in objects if isinstance(o, KGTextSlot)][0]
    
    logger.info(f"  Boolean slot value: {bool_slot.booleanSlotValue} (type: {type(bool_slot.booleanSlotValue).__name__})")
    logger.info(f"  Currency slot value: {currency_slot.currencySlotValue} (type: {type(currency_slot.currencySlotValue).__name__})")
    logger.info(f"  Text slot value: {text_slot.textSlotValue} (type: {type(text_slot.textSlotValue).__name__})")
    
    assert bool_slot.booleanSlotValue == False, f"Expected False, got {bool_slot.booleanSlotValue}"
    assert currency_slot.currencySlotValue == 0.0, f"Expected 0.0, got {currency_slot.currencySlotValue}"
    logger.info("  ✅ VitalSigns objects have correct falsey values")
    
    # ---- STEP 2: to_jsonld conversion ----
    trace_step(2, "GraphObject.to_jsonld_list() conversion")
    
    jsonld_dict = GraphObject.to_jsonld_list(objects)
    
    # Find the boolean slot and currency slot in the JSON-LD
    bool_slot_jsonld = None
    currency_slot_jsonld = None
    text_slot_jsonld = None
    
    for item in jsonld_dict.get('@graph', []):
        item_id = item.get('@id', '')
        if item_id == BOOL_SLOT_URI:
            bool_slot_jsonld = item
        elif item_id == CURRENCY_SLOT_URI:
            currency_slot_jsonld = item
        elif item_id == TEXT_SLOT_URI:
            text_slot_jsonld = item
    
    logger.info(f"\n  Boolean slot JSON-LD:")
    logger.info(f"  {json.dumps(bool_slot_jsonld, indent=4, default=str)}")
    
    logger.info(f"\n  Currency slot JSON-LD:")
    logger.info(f"  {json.dumps(currency_slot_jsonld, indent=4, default=str)}")
    
    logger.info(f"\n  Text slot JSON-LD:")
    logger.info(f"  {json.dumps(text_slot_jsonld, indent=4, default=str)}")
    
    # Check if the falsey values survived to_jsonld_list
    bool_key = "http://vital.ai/ontology/haley-ai-kg#hasBooleanSlotValue"
    currency_key = "http://vital.ai/ontology/haley-ai-kg#hasCurrencySlotValue"
    text_key = "http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue"
    
    if bool_slot_jsonld and bool_key in bool_slot_jsonld:
        logger.info(f"  ✅ Boolean false IS in JSON-LD: {bool_slot_jsonld[bool_key]}")
        tests_passed += 1
    else:
        logger.info(f"  ❌ Boolean false is MISSING from JSON-LD!")
        logger.info(f"     Keys present: {list(bool_slot_jsonld.keys()) if bool_slot_jsonld else 'NONE'}")
        tests_failed += 1
    
    if currency_slot_jsonld and currency_key in currency_slot_jsonld:
        logger.info(f"  ✅ Currency 0.0 IS in JSON-LD: {currency_slot_jsonld[currency_key]}")
        tests_passed += 1
    else:
        logger.info(f"  ❌ Currency 0.0 is MISSING from JSON-LD!")
        logger.info(f"     Keys present: {list(currency_slot_jsonld.keys()) if currency_slot_jsonld else 'NONE'}")
        tests_failed += 1
    
    if text_slot_jsonld and text_key in text_slot_jsonld:
        logger.info(f"  ✅ Text value IS in JSON-LD: {text_slot_jsonld[text_key]}")
        tests_passed += 1
    else:
        logger.info(f"  ❌ Text value is MISSING from JSON-LD!")
        tests_failed += 1
    
    # ---- STEP 3: Pydantic model roundtrip ----
    trace_step(3, "Pydantic JsonLdDocument model_dump roundtrip")
    
    doc = JsonLdDocument(
        context=jsonld_dict.get('@context', 'http://vital.ai/ontology/vital-core'),
        graph=jsonld_dict['@graph']
    )
    doc.jsonld_type = 'document'
    
    dumped = doc.model_dump(by_alias=True)
    
    # Find the slots in the dumped output
    dumped_bool = None
    dumped_currency = None
    for item in dumped.get('@graph', []):
        if item.get('@id') == BOOL_SLOT_URI:
            dumped_bool = item
        elif item.get('@id') == CURRENCY_SLOT_URI:
            dumped_currency = item
    
    logger.info(f"\n  Dumped boolean slot:")
    logger.info(f"  {json.dumps(dumped_bool, indent=4, default=str)}")
    
    logger.info(f"\n  Dumped currency slot:")
    logger.info(f"  {json.dumps(dumped_currency, indent=4, default=str)}")
    
    if dumped_bool and bool_key in dumped_bool:
        logger.info(f"  ✅ Boolean false survived model_dump: {dumped_bool[bool_key]}")
        tests_passed += 1
    else:
        logger.info(f"  ❌ Boolean false DROPPED by model_dump!")
        tests_failed += 1
    
    if dumped_currency and currency_key in dumped_currency:
        logger.info(f"  ✅ Currency 0.0 survived model_dump: {dumped_currency[currency_key]}")
        tests_passed += 1
    else:
        logger.info(f"  ❌ Currency 0.0 DROPPED by model_dump!")
        tests_failed += 1
    
    # ---- STEP 4: JSON serialization (wire format) ----
    trace_step(4, "JSON serialization (simulating HTTP wire format)")
    
    json_str = json.dumps(dumped)
    parsed_back = json.loads(json_str)
    
    parsed_bool = None
    parsed_currency = None
    for item in parsed_back.get('@graph', []):
        if item.get('@id') == BOOL_SLOT_URI:
            parsed_bool = item
        elif item.get('@id') == CURRENCY_SLOT_URI:
            parsed_currency = item
    
    if parsed_bool and bool_key in parsed_bool:
        logger.info(f"  ✅ Boolean false survived JSON roundtrip: {parsed_bool[bool_key]}")
        tests_passed += 1
    else:
        logger.info(f"  ❌ Boolean false DROPPED in JSON roundtrip!")
        tests_failed += 1
    
    if parsed_currency and currency_key in parsed_currency:
        logger.info(f"  ✅ Currency 0.0 survived JSON roundtrip: {parsed_currency[currency_key]}")
        tests_passed += 1
    else:
        logger.info(f"  ❌ Currency 0.0 DROPPED in JSON roundtrip!")
        tests_failed += 1
    
    # ---- STEP 5: Server-side Pydantic model deserialization ----
    trace_step(5, "Server-side Pydantic deserialization (JsonLdDocument from JSON)")
    
    from vitalgraph.model.jsonld_model import get_jsonld_discriminator
    disc = get_jsonld_discriminator(parsed_back)
    logger.info(f"  Discriminator result: {disc}")
    
    # Simulate what FastAPI does - parse JSON into Pydantic model
    server_doc = JsonLdDocument(**parsed_back)
    server_dumped = server_doc.model_dump(by_alias=True)
    
    server_bool = None
    server_currency = None
    for item in server_dumped.get('@graph', []):
        if item.get('@id') == BOOL_SLOT_URI:
            server_bool = item
        elif item.get('@id') == CURRENCY_SLOT_URI:
            server_currency = item
    
    if server_bool and bool_key in server_bool:
        logger.info(f"  ✅ Boolean false survived server Pydantic roundtrip: {server_bool[bool_key]}")
        tests_passed += 1
    else:
        logger.info(f"  ❌ Boolean false DROPPED by server Pydantic!")
        tests_failed += 1
    
    if server_currency and currency_key in server_currency:
        logger.info(f"  ✅ Currency 0.0 survived server Pydantic roundtrip: {server_currency[currency_key]}")
        tests_passed += 1
    else:
        logger.info(f"  ❌ Currency 0.0 DROPPED by server Pydantic!")
        tests_failed += 1
    
    # ---- STEP 6: VitalSigns from_jsonld_list roundtrip ----
    trace_step(6, "VitalSigns from_jsonld_list() roundtrip on server side")
    
    vs = VitalSigns()
    reconstructed_objects = vs.from_jsonld_list(server_dumped)
    
    recon_bool = None
    recon_currency = None
    recon_text = None
    for obj in reconstructed_objects:
        if hasattr(obj, 'URI') and str(obj.URI) == BOOL_SLOT_URI:
            recon_bool = obj
        elif hasattr(obj, 'URI') and str(obj.URI) == CURRENCY_SLOT_URI:
            recon_currency = obj
        elif hasattr(obj, 'URI') and str(obj.URI) == TEXT_SLOT_URI:
            recon_text = obj
    
    logger.info(f"  Reconstructed {len(reconstructed_objects)} objects")
    
    if recon_bool:
        val = recon_bool.booleanSlotValue
        logger.info(f"  Boolean slot reconstructed value: {val} (type: {type(val).__name__})")
        if val is not None and val == False:
            logger.info(f"  ✅ Boolean false survived from_jsonld_list")
            tests_passed += 1
        else:
            logger.info(f"  ❌ Boolean false LOST in from_jsonld_list! Value is: {val}")
            tests_failed += 1
    else:
        logger.info(f"  ❌ Boolean slot object NOT FOUND in reconstructed objects!")
        tests_failed += 1
    
    if recon_currency:
        val = recon_currency.currencySlotValue
        logger.info(f"  Currency slot reconstructed value: {val} (type: {type(val).__name__})")
        if val is not None and val == 0.0:
            logger.info(f"  ✅ Currency 0.0 survived from_jsonld_list")
            tests_passed += 1
        else:
            logger.info(f"  ❌ Currency 0.0 LOST in from_jsonld_list! Value is: {val}")
            tests_failed += 1
    else:
        logger.info(f"  ❌ Currency slot object NOT FOUND in reconstructed objects!")
        tests_failed += 1
    
    # ---- STEP 7: to_rdf() conversion ----
    trace_step(7, "VitalSigns to_rdf() conversion")
    
    if recon_bool:
        rdf_output = recon_bool.to_rdf()
        logger.info(f"  Boolean slot RDF output:")
        logger.info(f"  {rdf_output}")
        if "hasBooleanSlotValue" in rdf_output or "booleanSlotValue" in rdf_output:
            logger.info(f"  ✅ Boolean value IS in RDF output")
            tests_passed += 1
        else:
            logger.info(f"  ❌ Boolean value MISSING from RDF output!")
            tests_failed += 1
    
    if recon_currency:
        rdf_output = recon_currency.to_rdf()
        logger.info(f"\n  Currency slot RDF output:")
        logger.info(f"  {rdf_output}")
        if "hasCurrencySlotValue" in rdf_output or "currencySlotValue" in rdf_output:
            logger.info(f"  ✅ Currency value IS in RDF output")
            tests_passed += 1
        else:
            logger.info(f"  ❌ Currency value MISSING from RDF output!")
            tests_failed += 1
    
    # ---- STEP 8: Full end-to-end via client ----
    trace_step(8, "Full end-to-end: Create entity graph via client, verify in Fuseki")
    
    client = VitalGraphClient()
    try:
        await client.open()
        if not client.is_connected():
            logger.error("  ❌ Could not connect to VitalGraph server")
            tests_failed += 1
            return
        logger.info("  ✅ Connected to VitalGraph server")
        
        # Create space (delete first if exists)
        from vitalgraph.model.spaces_model import Space
        try:
            await client.spaces.delete_space(SPACE_ID)
        except:
            pass
        
        space = Space(space=SPACE_ID, space_name="Falsey Values Test")
        await client.spaces.create_space(space)
        logger.info(f"  ✅ Created space {SPACE_ID}")
        
        # Recreate fresh objects for the upload
        fresh_objects = create_test_objects()
        
        # Create entity graph
        response = await client.kgentities.create_kgentities(
            space_id=SPACE_ID,
            graph_id=GRAPH_ID,
            objects=fresh_objects
        )
        
        logger.info(f"  Create response: success={response.is_success}, message={response.message}")
        if response.is_success:
            logger.info(f"  ✅ Entity graph created successfully")
            tests_passed += 1
        else:
            logger.info(f"  ❌ Entity graph creation failed: {response.error_message}")
            tests_failed += 1
        
        # ---- STEP 9: Query Fuseki directly ----
        trace_step(9, "Query Fuseki directly for stored values")
        
        # Determine Fuseki dataset name
        fuseki_dataset = f"vitalgraph_space_{SPACE_ID}"
        fuseki_url = f"http://localhost:3030/{fuseki_dataset}/query"
        
        # Query for boolean slot
        sparql_query = f"""
        SELECT ?p ?o WHERE {{
            GRAPH <{GRAPH_ID}> {{
                <{BOOL_SLOT_URI}> ?p ?o
            }}
        }}
        """
        
        logger.info(f"  Querying Fuseki at: {fuseki_url}")
        logger.info(f"  SPARQL: {sparql_query.strip()}")
        
        async with httpx.AsyncClient() as http:
            resp = await http.get(
                fuseki_url,
                params={'query': sparql_query},
                headers={'Accept': 'application/sparql-results+json'}
            )
            
            if resp.status_code == 200:
                fuseki_result = resp.json()
                bindings = fuseki_result.get('results', {}).get('bindings', [])
                
                logger.info(f"\n  Boolean slot triples in Fuseki ({len(bindings)} triples):")
                has_boolean_value = False
                for b in bindings:
                    p = b.get('p', {}).get('value', '')
                    o = b.get('o', {})
                    logger.info(f"    {p} = {o}")
                    if 'hasBooleanSlotValue' in p:
                        has_boolean_value = True
                
                if has_boolean_value:
                    logger.info(f"  ✅ Boolean false IS stored in Fuseki!")
                    tests_passed += 1
                else:
                    logger.info(f"  ❌ Boolean false is MISSING from Fuseki!")
                    tests_failed += 1
            else:
                logger.info(f"  ❌ Fuseki query failed: {resp.status_code} - {resp.text[:200]}")
                tests_failed += 1
        
        # Query for currency slot
        sparql_query2 = f"""
        SELECT ?p ?o WHERE {{
            GRAPH <{GRAPH_ID}> {{
                <{CURRENCY_SLOT_URI}> ?p ?o
            }}
        }}
        """
        
        async with httpx.AsyncClient() as http:
            resp2 = await http.get(
                fuseki_url,
                params={'query': sparql_query2},
                headers={'Accept': 'application/sparql-results+json'}
            )
            
            if resp2.status_code == 200:
                fuseki_result2 = resp2.json()
                bindings2 = fuseki_result2.get('results', {}).get('bindings', [])
                
                logger.info(f"\n  Currency slot triples in Fuseki ({len(bindings2)} triples):")
                has_currency_value = False
                for b in bindings2:
                    p = b.get('p', {}).get('value', '')
                    o = b.get('o', {})
                    logger.info(f"    {p} = {o}")
                    if 'hasCurrencySlotValue' in p:
                        has_currency_value = True
                
                if has_currency_value:
                    logger.info(f"  ✅ Currency 0.0 IS stored in Fuseki!")
                    tests_passed += 1
                else:
                    logger.info(f"  ❌ Currency 0.0 is MISSING from Fuseki!")
                    tests_failed += 1
            else:
                logger.info(f"  ❌ Fuseki query failed: {resp2.status_code}")
                tests_failed += 1
        
        # Query for text slot (control)
        sparql_query3 = f"""
        SELECT ?p ?o WHERE {{
            GRAPH <{GRAPH_ID}> {{
                <{TEXT_SLOT_URI}> ?p ?o
            }}
        }}
        """
        
        async with httpx.AsyncClient() as http:
            resp3 = await http.get(
                fuseki_url,
                params={'query': sparql_query3},
                headers={'Accept': 'application/sparql-results+json'}
            )
            
            if resp3.status_code == 200:
                fuseki_result3 = resp3.json()
                bindings3 = fuseki_result3.get('results', {}).get('bindings', [])
                
                logger.info(f"\n  Text slot triples in Fuseki ({len(bindings3)} triples):")
                has_text_value = False
                for b in bindings3:
                    p = b.get('p', {}).get('value', '')
                    o = b.get('o', {})
                    logger.info(f"    {p} = {o}")
                    if 'hasTextSlotValue' in p:
                        has_text_value = True
                
                if has_text_value:
                    logger.info(f"  ✅ Text value IS stored in Fuseki (control)")
                    tests_passed += 1
                else:
                    logger.info(f"  ❌ Text value is MISSING from Fuseki! (control test failed too)")
                    tests_failed += 1
            else:
                logger.info(f"  ❌ Fuseki query failed: {resp3.status_code}")
                tests_failed += 1
        
        # ---- STEP 10: Read back via client API ----
        trace_step(10, "Read back entity graph via client API, check boolean/currency values")
        
        try:
            response = await client.kgentities.list_kgentities(
                space_id=SPACE_ID,
                graph_id=GRAPH_ID,
                include_entity_graph=True,
                page_size=100
            )
            
            logger.info(f"  list_kgentities response: success={response.is_success}, message={response.message}")
            
            # Collect all objects from the entity graphs
            all_read_objects = []
            if hasattr(response, 'graph_list') and response.graph_list:
                for eg in response.graph_list:
                    if hasattr(eg, 'objects') and eg.objects:
                        all_read_objects.extend(eg.objects)
            elif hasattr(response, 'objects') and response.objects:
                all_read_objects = response.objects
            
            logger.info(f"  Retrieved {len(all_read_objects)} objects from API")
            
            read_bool_slot = None
            read_currency_slot = None
            read_text_slot = None
            
            for obj in all_read_objects:
                obj_uri = str(obj.URI) if hasattr(obj, 'URI') else ''
                obj_type = type(obj).__name__
                logger.info(f"    Object: {obj_uri} ({obj_type})")
                
                if obj_uri == BOOL_SLOT_URI:
                    read_bool_slot = obj
                elif obj_uri == CURRENCY_SLOT_URI:
                    read_currency_slot = obj
                elif obj_uri == TEXT_SLOT_URI:
                    read_text_slot = obj
            
            # Check boolean slot
            if read_bool_slot:
                val = read_bool_slot.booleanSlotValue
                logger.info(f"\n  Boolean slot from API: booleanSlotValue = {val!r} (type: {type(val).__name__})")
                
                # Also dump the raw JSON-LD for this object
                try:
                    jsonld = read_bool_slot.to_jsonld()
                    logger.info(f"  Boolean slot JSON-LD: {json.dumps(json.loads(jsonld) if isinstance(jsonld, str) else jsonld, indent=2)}")
                except Exception as je:
                    logger.info(f"  (Could not dump JSON-LD: {je})")
                
                # CombinedProperty wraps the value; use == and bool() for comparison
                if val is not None and bool(val) == False:
                    logger.info(f"  ✅ Boolean false correctly read back from API!")
                    tests_passed += 1
                elif val is not None and bool(val) == True:
                    logger.info(f"  ❌ Boolean value is TRUE — read-path is corrupting false→true!")
                    tests_failed += 1
                elif val is None:
                    logger.info(f"  ❌ Boolean value is None — value was lost on read-back!")
                    tests_failed += 1
                else:
                    logger.info(f"  ❌ Boolean value is unexpected: {val!r}")
                    tests_failed += 1
            else:
                logger.info(f"  ❌ Boolean slot NOT FOUND in read-back objects!")
                tests_failed += 1
            
            # Check currency slot
            if read_currency_slot:
                val = read_currency_slot.currencySlotValue
                logger.info(f"\n  Currency slot from API: currencySlotValue = {val!r} (type: {type(val).__name__})")
                
                if val is not None and val == 0.0:
                    logger.info(f"  ✅ Currency 0.0 correctly read back from API!")
                    tests_passed += 1
                else:
                    logger.info(f"  ❌ Currency value wrong on read-back: {val!r}")
                    tests_failed += 1
            else:
                logger.info(f"  ❌ Currency slot NOT FOUND in read-back objects!")
                tests_failed += 1
            
            # Check text slot (control)
            if read_text_slot:
                val = read_text_slot.textSlotValue
                logger.info(f"\n  Text slot from API: textSlotValue = {val!r} (type: {type(val).__name__})")
                
                if val == "hello":
                    logger.info(f"  ✅ Text value correctly read back from API (control)!")
                    tests_passed += 1
                else:
                    logger.info(f"  ❌ Text value wrong on read-back: {val!r}")
                    tests_failed += 1
            else:
                logger.info(f"  ❌ Text slot NOT FOUND in read-back objects!")
                tests_failed += 1
                
        except Exception as e:
            logger.error(f"  ❌ Error during read-back test: {e}")
            import traceback
            traceback.print_exc()
            tests_failed += 1
        
    except Exception as e:
        logger.error(f"  ❌ Error during end-to-end test: {e}")
        import traceback
        traceback.print_exc()
        tests_failed += 1
    finally:
        await client.close()
    
    # ---- SUMMARY ----
    logger.info(f"\n{'='*80}")
    logger.info(f"  TEST SUMMARY")
    logger.info(f"{'='*80}")
    logger.info(f"  Passed: {tests_passed}")
    logger.info(f"  Failed: {tests_failed}")
    logger.info(f"  Total:  {tests_passed + tests_failed}")
    
    if tests_failed > 0:
        logger.info(f"\n  ⚠️  FALSEY VALUES ARE BEING DROPPED!")
        logger.info(f"  Look at the first ❌ to identify which layer drops the value.")
    else:
        logger.info(f"\n  ✅ All falsey values preserved correctly!")
    
    return tests_failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
