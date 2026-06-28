#!/usr/bin/env python3
"""
Retrieve Entity Graphs and Frames Test Case

This test case retrieves individual entity graphs and their frames from the loaded dataset.
It tests entity graph retrieval, frame listing, and individual frame retrieval operations.
"""

import time


class RetrieveEntityGraphsTester:
    """Test case for retrieving entity graphs and frames."""
    
    def __init__(self, client):
        """
        Initialize the retrieve entity graphs tester.
        
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
    
    async def run_tests(self, space_id: str, graph_id: str, entity_uris: list, sample_size: int = 5) -> dict:
        """
        Run retrieve entity graphs and frames tests.
        
        Args:
            space_id: Space ID
            graph_id: Graph ID
            entity_uris: List of entity URIs to test
            sample_size: Number of entities to sample for detailed testing
            
        Returns:
            Dictionary with test results
        """
        print(f"\n{'=' * 80}")
        print(f"  Retrieve Entity Graphs and Frames")
        print(f"{'=' * 80}")
        
        if not entity_uris:
            self._record_test("Entity URIs available", False, "No entity URIs provided")
            return {
                "test_name": "Retrieve Entity Graphs and Frames",
                "tests_run": self.tests_run,
                "tests_passed": self.tests_passed,
                "tests_failed": self.tests_run - self.tests_passed,
                "errors": self.errors
            }
        
        # Sample entities for testing
        sample_entities = entity_uris[:sample_size]
        print(f"\n📊 Testing with {len(sample_entities)} sample entities (out of {len(entity_uris)} total)")
        
        retrieved_entities = 0
        total_frames = 0
        retrieved_frames = 0
        
        for idx, entity_uri in enumerate(sample_entities, 1):
            print(f"\n--- Entity {idx}/{len(sample_entities)}: {entity_uri} ---\n")
            
            # ================================================================
            # Test: Get entity graph
            # ================================================================
            try:
                start_time = time.time()
                response = await self.client.kgentities.get_kgentity(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=entity_uri,
                    include_entity_graph=True
                )
                get_time = time.time() - start_time
                
                print(f"⏱️  GET entity: {get_time:.3f}s")
                
                # Verify entity was retrieved - direct access via EntityGraph
                if response.is_success and response.objects:
                    entity_graph = response.objects
                    retrieved_entities += 1
                    print(f"   ✅ Entity retrieved successfully ({entity_graph.count} objects)")
                else:
                    print(f"   ❌ Entity not found in response")
                
            except Exception as e:
                print(f"   ❌ Error retrieving entity: {e}")
                continue
            
            # ================================================================
            # Test: List frames for entity
            # ================================================================
            try:
                start_time = time.time()
                frames_response = await self.client.kgentities.get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity_uri,
                    parent_frame_uri=None  # Top-level frames
                )
                list_frames_time = time.time() - start_time
                
                print(f"⏱️  LIST frames: {list_frames_time:.3f}s")
                
                # Extract frames from response - FrameResponse has objects attribute
                frames = []
                if frames_response.is_success and frames_response.objects:
                    from ai_haley_kg_domain.model.KGFrame import KGFrame
                    for obj in frames_response.objects:
                        if isinstance(obj, KGFrame):
                            frames.append(obj)
                
                frame_count = len(frames)
                total_frames += frame_count
                print(f"   Found {frame_count} top-level frames for entity")
                
                # ============================================================
                # For each top-level frame, list and retrieve child frames
                # ============================================================
                if frames:
                    # Sample first 3 top-level frames
                    sample_top_frames = frames[:3]
                    print(f"   Processing {len(sample_top_frames)} sample top-level frame(s)...")
                    
                    for top_frame_idx, top_frame in enumerate(sample_top_frames, 1):
                        top_frame_uri = str(top_frame.URI) if hasattr(top_frame, 'URI') else None
                        if not top_frame_uri:
                            continue
                        
                        top_frame_name = top_frame_uri.split(':')[-2] if ':' in top_frame_uri else top_frame_uri
                        print(f"\n      Top-level frame {top_frame_idx}: {top_frame_name}")
                        
                        try:
                            # List child frames of this parent
                            child_frames_response = await self.client.kgentities.get_kgentity_frames(
                                space_id=space_id,
                                graph_id=graph_id,
                                entity_uri=entity_uri,
                                parent_frame_uri=top_frame_uri  # Get children of this parent
                            )
                            
                            # Extract child frames - FrameResponse has objects attribute
                            child_frames = []
                            if child_frames_response.is_success and child_frames_response.objects:
                                from ai_haley_kg_domain.model.KGFrame import KGFrame
                                for obj in child_frames_response.objects:
                                    if isinstance(obj, KGFrame):
                                        child_frames.append(obj)
                            
                            print(f"         Found {len(child_frames)} child frames")
                            
                            # Retrieve and log each child frame (using working pattern)
                            for child_idx, child_frame in enumerate(child_frames[:3], 1):  # Sample first 3 children
                                child_frame_uri = str(child_frame.URI) if hasattr(child_frame, 'URI') else None
                                if not child_frame_uri:
                                    continue
                                
                                child_frame_name = child_frame_uri.split(':')[-1] if ':' in child_frame_uri else child_frame_uri
                                
                                try:
                                    start_time = time.time()
                                    # Use get_kgentity_frames with frame_uris parameter (working pattern)
                                    child_frame_response = await self.client.kgentities.get_kgentity_frames(
                                        space_id=space_id,
                                        graph_id=graph_id,
                                        entity_uri=entity_uri,
                                        frame_uris=[child_frame_uri]
                                    )
                                    get_frame_time = time.time() - start_time
                                    
                                    # Single frame request returns FrameGraphResponse with frame_graph attribute
                                    if child_frame_response.is_success and hasattr(child_frame_response, 'frame_graph') and child_frame_response.frame_graph:
                                        frame_graph = child_frame_response.frame_graph
                                        retrieved_frames += 1
                                        print(f"         Child frame {child_idx} ({child_frame_name}): ✅ Retrieved ({frame_graph.count} objects, {get_frame_time:.3f}s)")
                                    else:
                                        print(f"         Child frame {child_idx} ({child_frame_name}): ❌ Not retrieved")
                                
                                except Exception as e:
                                    print(f"         Child frame {child_idx}: ❌ Error: {e}")
                        
                        except Exception as e:
                            print(f"      Error listing child frames: {e}")
                
            except Exception as e:
                print(f"   ❌ Error listing frames: {e}")
        
        # ====================================================================
        # Summary and Tests
        # ====================================================================
        print(f"\n📊 Retrieval Summary:")
        print(f"   Entities tested: {len(sample_entities)}")
        print(f"   Entities retrieved: {retrieved_entities}")
        print(f"   Total frames found: {total_frames}")
        print(f"   Frames retrieved: {retrieved_frames}")
        
        self._record_test(
            "Retrieve sample entities",
            retrieved_entities == len(sample_entities),
            f"Expected {len(sample_entities)} entities, retrieved {retrieved_entities}"
        )
        
        self._record_test(
            "Entities have frames",
            total_frames > 0,
            f"Expected frames for entities, found {total_frames}"
        )
        
        if total_frames > 0:
            self._record_test(
                "Retrieve sample frames",
                retrieved_frames > 0,
                f"Expected to retrieve frames, retrieved {retrieved_frames}"
            )
        
        return {
            "test_name": "Retrieve Entity Graphs and Frames",
            "tests_run": self.tests_run,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_run - self.tests_passed,
            "errors": self.errors,
            "retrieved_entities": retrieved_entities,
            "total_frames": total_frames,
            "retrieved_frames": retrieved_frames
        }
