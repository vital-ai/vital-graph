#!/usr/bin/env python3
"""
KGRelations Test Data Creation

Creates relation types, product entities, and relation instances for testing.
This data is added to the multi-org test but not used by it until Phase 5.
"""

import logging
import uuid
from typing import Dict, Any, List, Tuple
from datetime import datetime

from vitalgraph_client_test.client_test_data import ClientTestDataCreator
from vital_ai_vitalsigns.model.GraphObject import GraphObject

from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGType import KGType
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation

logger = logging.getLogger(__name__)


# Product data for testing relations
PRODUCTS = [
    {
        "name": "Enterprise Software Suite",
        "category": "Software",
        "price": 50000
    },
    {
        "name": "Cloud Platform Service",
        "category": "Software",
        "price": 25000
    },
    {
        "name": "Financial Analytics Tool",
        "category": "Software",
        "price": 35000
    },
    {
        "name": "Medical Imaging System",
        "category": "Hardware",
        "price": 150000
    },
    {
        "name": "Solar Panel Array",
        "category": "Hardware",
        "price": 75000
    },
    {
        "name": "Retail POS System",
        "category": "Software",
        "price": 15000
    }
]


class CreateRelationsTester:
    """Test case for creating KGRelations test data."""
    
    def __init__(self):
        self.data_creator = ClientTestDataCreator()
    
    def create_relation_kgtypes(self, client, space_id: str, graph_id: str) -> Dict[str, Any]:
        """
        Create KGType definitions for relation types and ProductEntity.
        
        Returns dict with type URIs.
        """
        logger.info("\n=== Creating Relation KGTypes ===")
        
        types_to_create = []
        type_uris = {}
        
        # 1. ProductEntity type
        product_entity_type = KGType()
        product_entity_type.URI = "http://vital.ai/test/kgtype/ProductEntity"
        product_entity_type.name = "ProductEntity"
        product_entity_type.kGraphDescription = "Product entity for testing relations"
        types_to_create.append(product_entity_type)
        type_uris['product_entity'] = str(product_entity_type.URI)
        
        # 2. MakesProductRelation type (org → product)
        makes_product_type = KGType()
        makes_product_type.URI = "http://vital.ai/test/kgtype/MakesProductRelation"
        makes_product_type.name = "MakesProductRelation"
        makes_product_type.kGraphDescription = "Organization produces/manufactures a product"
        types_to_create.append(makes_product_type)
        type_uris['makes_product'] = str(makes_product_type.URI)
        
        # 3. CompetitorOfRelation type (org → org)
        competitor_type = KGType()
        competitor_type.URI = "http://vital.ai/test/kgtype/CompetitorOfRelation"
        competitor_type.name = "CompetitorOfRelation"
        competitor_type.kGraphDescription = "Organization competes with another organization"
        types_to_create.append(competitor_type)
        type_uris['competitor_of'] = str(competitor_type.URI)
        
        # 4. PartnerWithRelation type (org → org)
        partner_type = KGType()
        partner_type.URI = "http://vital.ai/test/kgtype/PartnerWithRelation"
        partner_type.name = "PartnerWithRelation"
        partner_type.kGraphDescription = "Organization has partnership with another organization"
        types_to_create.append(partner_type)
        type_uris['partner_with'] = str(partner_type.URI)
        
        # 5. SuppliesRelation type (org → org)
        supplies_type = KGType()
        supplies_type.URI = "http://vital.ai/test/kgtype/SuppliesRelation"
        supplies_type.name = "SuppliesRelation"
        supplies_type.kGraphDescription = "Organization supplies products/services to another"
        types_to_create.append(supplies_type)
        type_uris['supplies'] = str(supplies_type.URI)
        
        # Create all types - pass GraphObjects directly
        response = client.kgtypes.create_kgtypes(space_id, graph_id, types_to_create)
        
        if response.is_success:
            logger.info(f"✅ Created {len(types_to_create)} relation KGTypes")
            for type_name, type_uri in type_uris.items():
                logger.info(f"   - {type_name}: {type_uri}")
        else:
            logger.error(f"❌ Failed to create relation KGTypes: {response.message}")
        
        return type_uris
    
    def create_product_entities(
        self, 
        client, 
        space_id: str, 
        graph_id: str,
        product_entity_type_uri: str
    ) -> Dict[str, str]:
        """
        Create product entities.
        
        Returns dict mapping product name to URI.
        """
        logger.info("\n=== Creating Product Entities ===")
        
        product_uris = {}
        
        for product_data in PRODUCTS:
            # Create product entity
            product = KGEntity()
            product_name_normalized = product_data['name'].lower().replace(' ', '_')
            product.URI = f"http://vital.ai/test/kgentity/product/{product_name_normalized}"
            product.kGEntityType = product_entity_type_uri
            product.name = product_data['name']
            product.kGGraphURI = product.URI
            
            # Create slots for product properties
            objects = [product]
            
            # Product name slot
            name_slot = KGTextSlot()
            name_slot.URI = f"urn:slot:{uuid.uuid4()}"
            name_slot.kGSlotType = "http://vital.ai/test/kgtype/ProductNameSlot"
            name_slot.textSlotValue = product_data['name']
            objects.append(name_slot)
            
            # Category slot
            category_slot = KGTextSlot()
            category_slot.URI = f"urn:slot:{uuid.uuid4()}"
            category_slot.kGSlotType = "http://vital.ai/test/kgtype/ProductCategorySlot"
            category_slot.textSlotValue = product_data['category']
            objects.append(category_slot)
            
            # Price slot
            price_slot = KGIntegerSlot()
            price_slot.URI = f"urn:slot:{uuid.uuid4()}"
            price_slot.kGSlotType = "http://vital.ai/test/kgtype/ProductPriceSlot"
            price_slot.integerSlotValue = product_data['price']
            objects.append(price_slot)
            
            # Create entity with slots
            response = client.kgentities.create_kgentities(
                space_id, 
                graph_id, 
                objects
            )
            
            if response.is_success:
                product_uris[product_data['name']] = product.URI
                logger.info(f"✅ Created product: {product_data['name']}")
            else:
                logger.error(f"❌ Failed to create product {product_data['name']}: {response.error_message}")
        
        logger.info(f"\n✅ Created {len(product_uris)} product entities")
        return product_uris
    
    def create_relation_instances(
        self,
        client,
        space_id: str,
        graph_id: str,
        org_uris: Dict[str, str],
        product_uris: Dict[str, str],
        relation_type_uris: Dict[str, str]
    ) -> Dict[str, List[str]]:
        """
        Create relation instances between organizations and products.
        
        Returns dict mapping relation type to list of relation URIs.
        """
        logger.info("\n=== Creating Relation Instances ===")
        
        relation_uris = {
            'makes_product': [],
            'competitor_of': [],
            'partner_with': [],
            'supplies': []
        }
        
        # MakesProductRelation instances (org → product)
        makes_product_relations = [
            ("TechCorp Industries", "Enterprise Software Suite"),
            ("TechCorp Industries", "Cloud Platform Service"),
            ("Global Finance Group", "Financial Analytics Tool"),
            ("Healthcare Solutions Inc", "Medical Imaging System"),
            ("Energy Innovations LLC", "Solar Panel Array"),
            ("Retail Dynamics Corp", "Retail POS System")
        ]
        
        for org_name, product_name in makes_product_relations:
            if org_name in org_uris and product_name in product_uris:
                relation = Edge_hasKGRelation()
                relation.URI = f"urn:relation:makes_product:{uuid.uuid4()}"
                relation.edgeSource = org_uris[org_name]
                relation.edgeDestination = product_uris[product_name]
                relation.kGRelationType = relation_type_uris['makes_product']
                
                response = client.kgrelations.create_relations(space_id, graph_id, [relation])
                if response.is_success:
                    relation_uris['makes_product'].extend(response.created_uris)
                    logger.info(f"✅ Created MakesProduct: {org_name} → {product_name}")
        
        # CompetitorOfRelation instances (org → org)
        competitor_relations = [
            ("TechCorp Industries", "Global Finance Group"),
            ("Healthcare Solutions Inc", "Education Systems Ltd"),
            ("Energy Innovations LLC", "Manufacturing Excellence"),
            ("Retail Dynamics Corp", "Transportation Networks")
        ]
        
        for org1_name, org2_name in competitor_relations:
            if org1_name in org_uris and org2_name in org_uris:
                relation = Edge_hasKGRelation()
                relation.URI = f"urn:relation:competitor:{uuid.uuid4()}"
                relation.edgeSource = org_uris[org1_name]
                relation.edgeDestination = org_uris[org2_name]
                relation.kGRelationType = relation_type_uris['competitor_of']
                
                response = client.kgrelations.create_relations(space_id, graph_id, [relation])
                if response.is_success:
                    relation_uris['competitor_of'].extend(response.created_uris)
                    logger.info(f"✅ Created CompetitorOf: {org1_name} → {org2_name}")
        
        # PartnerWithRelation instances (org → org)
        partner_relations = [
            ("TechCorp Industries", "Healthcare Solutions Inc"),
            ("Global Finance Group", "Retail Dynamics Corp"),
            ("Energy Innovations LLC", "Education Systems Ltd")
        ]
        
        for org1_name, org2_name in partner_relations:
            if org1_name in org_uris and org2_name in org_uris:
                relation = Edge_hasKGRelation()
                relation.URI = f"urn:relation:partner:{uuid.uuid4()}"
                relation.edgeSource = org_uris[org1_name]
                relation.edgeDestination = org_uris[org2_name]
                relation.kGRelationType = relation_type_uris['partner_with']
                
                response = client.kgrelations.create_relations(space_id, graph_id, [relation])
                if response.is_success:
                    relation_uris['partner_with'].extend(response.created_uris)
                    logger.info(f"✅ Created PartnerWith: {org1_name} → {org2_name}")
        
        # SuppliesRelation instances (org → org)
        supplies_relations = [
            ("Manufacturing Excellence", "Retail Dynamics Corp"),
            ("Energy Innovations LLC", "TechCorp Industries"),
            ("Healthcare Solutions Inc", "Education Systems Ltd")
        ]
        
        for org1_name, org2_name in supplies_relations:
            if org1_name in org_uris and org2_name in org_uris:
                relation = Edge_hasKGRelation()
                relation.URI = f"urn:relation:supplies:{uuid.uuid4()}"
                relation.edgeSource = org_uris[org1_name]
                relation.edgeDestination = org_uris[org2_name]
                relation.kGRelationType = relation_type_uris['supplies']
                
                response = client.kgrelations.create_relations(space_id, graph_id, [relation])
                if response.is_success:
                    relation_uris['supplies'].extend(response.created_uris)
                    logger.info(f"✅ Created Supplies: {org1_name} → {org2_name}")
        
        # Summary
        total_relations = sum(len(uris) for uris in relation_uris.values())
        logger.info(f"\n✅ Created {total_relations} total relations:")
        logger.info(f"   - MakesProduct: {len(relation_uris['makes_product'])}")
        logger.info(f"   - CompetitorOf: {len(relation_uris['competitor_of'])}")
        logger.info(f"   - PartnerWith: {len(relation_uris['partner_with'])}")
        logger.info(f"   - Supplies: {len(relation_uris['supplies'])}")
        
        return relation_uris


def create_all_relation_data(
    client,
    space_id: str,
    graph_id: str,
    org_uris: Dict[str, str]
) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, List[str]]]:
    """
    Create all relation test data: types, products, and relations.
    
    Args:
        client: VitalGraph client
        space_id: Space ID
        graph_id: Graph ID
        org_uris: Dict mapping organization names to URIs
        
    Returns:
        Tuple of (relation_type_uris, product_uris, relation_uris)
    """
    tester = CreateRelationsTester()
    
    # Create relation types
    relation_type_uris = tester.create_relation_kgtypes(client, space_id, graph_id)
    
    # Create product entities
    product_uris = tester.create_product_entities(
        client, 
        space_id, 
        graph_id,
        relation_type_uris['product_entity']
    )
    
    # Create relation instances
    relation_uris = tester.create_relation_instances(
        client,
        space_id,
        graph_id,
        org_uris,
        product_uris,
        relation_type_uris
    )
    
    return relation_type_uris, product_uris, relation_uris
