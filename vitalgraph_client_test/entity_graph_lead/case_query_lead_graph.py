"""
Query Lead Entity Graph Test Case

Tests querying and retrieving frames from a lead entity graph.
"""

import logging
from typing import Dict, Any
from vital_ai_vitalsigns.vitalsigns import VitalSigns

logger = logging.getLogger(__name__)


class QueryLeadGraphTester:
    """Test case for querying lead entity graph frames."""
    
    def __init__(self, client):
        self.client = client
    
    def run_tests(self, space_id: str, graph_id: str, entity_uri: str) -> Dict[str, Any]:
        """
        Run lead entity graph query tests.
        
        Args:
            space_id: Space ID
            graph_id: Graph ID
            entity_uri: URI of the entity to query
            
        Returns:
            Dict with test results
        """
        results = {
            "test_name": "Query Lead Entity Graph",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
            "frame_count": 0,
            "frame_uris": []
        }
        
        vs = VitalSigns()
        
        logger.info(f"\n{'='*100}")
        logger.info(f"  Query Lead Entity Graph")
        logger.info(f"{'='*100}")
        logger.info(f"Entity URI: {entity_uri}")
        
        # Test 1: List all frames for entity
        results["tests_run"] += 1
        
        try:
            logger.info(f"\n--- List Entity Frames ---\n")
            
            # Get all frames for the entity
            frames_response = self.client.kgentities.get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri
            )
            
            if hasattr(frames_response, 'frames') and frames_response.frames:
                frame_count = len(frames_response.frames)
                results["frame_count"] = frame_count
                results["frame_uris"] = [str(f.URI) for f in frames_response.frames if hasattr(f, 'URI')]
                
                logger.info(f"   Found {frame_count} frames for entity")
                
                # Show first few frame URIs
                for i, frame_uri in enumerate(results["frame_uris"][:5]):
                    logger.info(f"      Frame {i+1}: {frame_uri.split(':')[-1]}")
                
                if frame_count > 5:
                    logger.info(f"      ... and {frame_count - 5} more frames")
                
                logger.info(f"✅ PASS: List entity frames")
                results["tests_passed"] += 1
            else:
                logger.warning(f"   ⚠️  No frames found for entity")
                logger.info(f"✅ PASS: List entity frames (empty result)")
                results["tests_passed"] += 1
                
        except Exception as e:
            logger.error(f"❌ Error listing entity frames: {e}")
            import traceback
            logger.error(traceback.format_exc())
            results["tests_failed"] += 1
            results["errors"].append(f"Error listing entity frames: {str(e)}")
        
        # Test 2: Get specific frame (if frames exist)
        if results["frame_uris"]:
            results["tests_run"] += 1
            
            try:
                logger.info(f"\n--- Get Specific Frame ---\n")
                
                # Get the first frame
                test_frame_uri = results["frame_uris"][0]
                logger.info(f"   Getting frame: {test_frame_uri.split(':')[-1]}")
                
                frame_response = self.client.kgentities.get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity_uri,
                    frame_uris=[test_frame_uri]
                )
                
                if hasattr(frame_response, 'frame_graphs') and frame_response.frame_graphs:
                    if test_frame_uri in frame_response.frame_graphs:
                        frame_data = frame_response.frame_graphs[test_frame_uri]
                        
                        # Check if it's an error or actual frame data
                        if hasattr(frame_data, 'error'):
                            logger.error(f"   ❌ Frame returned error: {frame_data.error}")
                            results["tests_failed"] += 1
                            results["errors"].append(f"Frame returned error: {frame_data.error}")
                        else:
                            # Convert to dict and inspect
                            frame_dict = frame_data.model_dump(by_alias=True) if hasattr(frame_data, 'model_dump') else frame_data
                            frame_objects = vs.from_jsonld_list(frame_dict)
                            
                            logger.info(f"   ✅ Retrieved frame with {len(frame_objects)} objects")
                            
                            # Count object types in frame
                            object_types = {}
                            for obj in frame_objects:
                                obj_type = type(obj).__name__
                                object_types[obj_type] = object_types.get(obj_type, 0) + 1
                            
                            logger.info(f"   Frame contains: {object_types}")
                            logger.info(f"✅ PASS: Get specific frame")
                            results["tests_passed"] += 1
                    else:
                        logger.error(f"   ❌ Frame not found in response")
                        results["tests_failed"] += 1
                        results["errors"].append("Frame not found in response")
                else:
                    logger.error(f"   ❌ No frame graphs in response")
                    results["tests_failed"] += 1
                    results["errors"].append("No frame graphs in response")
                    
            except Exception as e:
                logger.error(f"❌ Error getting specific frame: {e}")
                import traceback
                logger.error(traceback.format_exc())
                results["tests_failed"] += 1
                results["errors"].append(f"Error getting specific frame: {str(e)}")
        
        return results
