"""
Load Lead Entity Graph Test Case

Tests loading a lead entity graph from N-Triples file.
"""

import logging
from typing import Dict, Any
from pathlib import Path
from rdflib import Graph as RDFGraph
from vital_ai_vitalsigns.vitalsigns import VitalSigns

logger = logging.getLogger(__name__)


class LoadLeadGraphTester:
    """Test case for loading lead entity graphs from N-Triples files."""
    
    def __init__(self, client):
        self.client = client
    
    def run_tests(self, space_id: str, graph_id: str, nt_file_path: str) -> Dict[str, Any]:
        """
        Run lead entity graph loading tests.
        
        Args:
            space_id: Space ID
            graph_id: Graph ID
            nt_file_path: Path to N-Triples file containing entity graph
            
        Returns:
            Dict with test results including entity_uri
        """
        results = {
            "test_name": "Load Lead Entity Graph",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
            "entity_uri": None,
            "triple_count": 0,
            "lead_id": None
        }
        
        # Initialize VitalSigns
        vs = VitalSigns()
        
        logger.info(f"\n{'='*100}")
        logger.info(f"  Load Lead Entity Graph")
        logger.info(f"{'='*100}")
        logger.info(f"Loading from: {Path(nt_file_path).name}")
        
        # Test 1: Load N-Triples file
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- Load N-Triples File ---\n")
            
            # Extract lead ID from filename (e.g., lead_00QUg00000Xzjy8MAB.nt -> 00QUg00000Xzjy8MAB)
            filename = Path(nt_file_path).stem
            lead_id = filename.replace('lead_', '')
            results["lead_id"] = lead_id
            
            logger.info(f"   Lead ID: {lead_id}")
            
            # Load N-Triples file using RDFLib
            rdf_graph = RDFGraph()
            rdf_graph.parse(nt_file_path, format='nt')
            
            triple_count = len(rdf_graph)
            results["triple_count"] = triple_count
            
            logger.info(f"   Loaded {triple_count} triples from N-Triples file")
            logger.info(f"✅ PASS: Load N-Triples file")
            results["tests_passed"] += 1
            
        except Exception as e:
            logger.error(f"❌ Error loading N-Triples file: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results["tests_failed"] += 1
            results["errors"].append(f"Error loading N-Triples file: {str(e)}")
            return results
        
        # Test 2: Convert triples to graph objects and upload
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- Upload Entity Graph ---\n")
            
            # Get RDFLib triple objects
            triples = list(rdf_graph)
            
            logger.info(f"   Converting {len(triples)} triples to VitalSigns objects")
            
            # Use VitalSigns to create GraphObjects from RDFLib triples
            graph_objects = vs.from_triples_list(triples)
            
            logger.info(f"   Converted to {len(graph_objects)} VitalSigns objects")
            
            # Find the KGEntity from the graph objects
            from ai_haley_kg_domain.model.KGEntity import KGEntity
            entity_uri = None
            for obj in graph_objects:
                if isinstance(obj, KGEntity):
                    entity_uri = str(obj.URI)
                    results["entity_uri"] = entity_uri
                    logger.info(f"   Found entity URI: {entity_uri}")
                    break
            
            if not entity_uri:
                logger.error(f"   ❌ No KGEntity found in converted objects")
                results["tests_failed"] += 1
                results["errors"].append("No KGEntity found in converted objects")
                return results
            
            logger.info(f"   Uploading entity graph to {graph_id}")
            
            # Create entity with graph - pass GraphObjects directly
            response = self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=graph_objects
            )
            
            if response.is_success:
                logger.info(f"   ✅ Entity graph uploaded successfully")
                logger.info(f"   Created {response.count} objects")
                logger.info(f"✅ PASS: Convert and upload entity graph")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ Upload failed (error {response.error_code}): {response.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Upload failed: {response.error_message}")
                
        except Exception as e:
            logger.error(f"❌ Error converting/uploading entity graph: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results["tests_failed"] += 1
            results["errors"].append(f"Error converting/uploading entity graph: {str(e)}")
        
        return results
