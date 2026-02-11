#!/usr/bin/env python3
"""
Bulk Load Lead Dataset Test Case

This test case loads all lead entity graph files from the lead_test_data directory.
It's designed to test bulk loading operations and create a larger dataset for
subsequent query and retrieval tests.
"""

import time
from pathlib import Path
from typing import List
from rdflib import Graph as RDFGraph
from vital_ai_vitalsigns.vitalsigns import VitalSigns


class BulkLoadDatasetTester:
    """Test case for bulk loading lead entity graphs."""
    
    def __init__(self, client):
        """
        Initialize the bulk load tester.
        
        Args:
            client: VitalGraphClient instance
        """
        self.client = client
        self.tests_run = 0
        self.tests_passed = 0
        self.errors = []
    
    def _record_test(self, test_name: str, passed: bool, error: str = None):
        """Record test result."""
        self.tests_run += 1
        if passed:
            self.tests_passed += 1
            print(f"✅ PASS: {test_name}")
        else:
            self.errors.append(error or test_name)
            print(f"❌ FAIL: {test_name}")
            if error:
                print(f"   Error: {error}")
    
    async def run_tests(self, space_id: str, graph_id: str, lead_files: List[Path]) -> dict:
        """
        Run bulk load tests.
        
        Args:
            space_id: Space ID
            graph_id: Graph ID
            lead_files: List of Path objects for lead .nt files
            
        Returns:
            Dictionary with test results
        """
        print(f"\n{'=' * 80}")
        print(f"  Bulk Load Lead Dataset")
        print(f"{'=' * 80}")
        
        loaded_entities = []
        total_triples = 0
        failed_loads = []
        
        print(f"\n📦 Loading {len(lead_files)} lead entity graph files...")
        
        # Initialize VitalSigns
        vs = VitalSigns()
        
        start_time = time.time()
        
        for idx, lead_file in enumerate(lead_files, 1):
            try:
                # Load N-Triples file using RDFLib
                rdf_graph = RDFGraph()
                rdf_graph.parse(lead_file, format='nt')
                triple_count = len(rdf_graph)
                
                # Get RDFLib triple objects
                triples = list(rdf_graph)
                
                # Use VitalSigns to create GraphObjects from RDFLib triples
                graph_objects = vs.from_triples_list(triples)
                
                # Create entity via API - pass GraphObjects directly
                response = await self.client.kgentities.create_kgentities(
                    space_id=space_id,
                    graph_id=graph_id,
                    objects=graph_objects
                )
                
                # Extract entity URI from response - CreateEntityResponse has created_uris
                entity_uri = None
                if response.is_success and hasattr(response, 'created_uris') and response.created_uris:
                    entity_uri = response.created_uris[0]
                
                if entity_uri:
                    loaded_entities.append({
                        'uri': entity_uri,
                        'file': lead_file.name,
                        'triples': triple_count
                    })
                    total_triples += triple_count
                    
                    if idx % 10 == 0:
                        print(f"   Loaded {idx}/{len(lead_files)} files ({len(loaded_entities)} entities, {total_triples:,} triples)")
                else:
                    failed_loads.append(lead_file.name)
                    print(f"   ⚠️  Failed to extract entity URI from {lead_file.name}")
                    
            except Exception as e:
                failed_loads.append(lead_file.name)
                print(f"   ❌ Error loading {lead_file.name}: {e}")
        
        load_time = time.time() - start_time
        
        print(f"\n📊 Bulk Load Summary:")
        print(f"   Files processed: {len(lead_files)}")
        print(f"   Entities loaded: {len(loaded_entities)}")
        print(f"   Failed loads: {len(failed_loads)}")
        print(f"   Total triples: {total_triples:,}")
        print(f"   Load time: {load_time:.2f}s")
        print(f"   Average: {load_time/len(lead_files):.2f}s per file")
        
        # Test: Verify expected number of entities loaded
        expected_entities = len(lead_files) - len(failed_loads)
        self._record_test(
            "Bulk load entities",
            len(loaded_entities) == expected_entities,
            f"Expected {expected_entities} entities, got {len(loaded_entities)}"
        )
        
        # Test: Verify no failed loads (or acceptable failure rate)
        acceptable_failure_rate = 0.05  # 5%
        actual_failure_rate = len(failed_loads) / len(lead_files)
        self._record_test(
            "Acceptable failure rate",
            actual_failure_rate <= acceptable_failure_rate,
            f"Failure rate {actual_failure_rate:.1%} exceeds acceptable {acceptable_failure_rate:.1%}"
        )
        
        return {
            "test_name": "Bulk Load Lead Dataset",
            "tests_run": self.tests_run,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_run - self.tests_passed,
            "errors": self.errors,
            "loaded_entities": loaded_entities,
            "total_triples": total_triples,
            "failed_loads": failed_loads,
            "load_time": load_time
        }
