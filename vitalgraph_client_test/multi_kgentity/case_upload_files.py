#!/usr/bin/env python3
"""
Upload Files Test Case

Test case for uploading PDF files and creating file nodes.
Files are uploaded to the VitalGraph file storage and their URIs are tracked
for use in entity frame references.
"""

import logging
import asyncio
from typing import Dict, Any, List
from pathlib import Path
from vitalgraph.client.binary.async_streaming import AsyncFilePathGenerator

logger = logging.getLogger(__name__)


class UploadFilesTester:
    """Test case for uploading files and creating file nodes."""
    
    def __init__(self, client):
        self.client = client
        
    async def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """
        Run file upload tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            
        Returns:
            Test results dictionary with file_uris
        """
        logger.info("=" * 80)
        logger.info("  Uploading Files")
        logger.info("=" * 80)
        
        results = []
        errors = []
        file_uris = {}
        
        # Define files to upload with their purposes
        files_to_upload = self._get_files_to_upload()
        
        # Upload each file
        for file_key, file_info in files_to_upload.items():
            upload_result = await self._test_upload_file(
                space_id, 
                graph_id, 
                file_key,
                file_info['path'],
                file_info['purpose']
            )
            results.append(upload_result)
            
            if upload_result['passed']:
                file_uris[file_key] = upload_result['file_uri']
            else:
                errors.append(upload_result.get('error', f'Upload failed for {file_key}'))
        
        passed_tests = sum(1 for r in results if r['passed'])
        logger.info(f"\n✅ File upload tests completed: {passed_tests}/{len(results)} passed")
        
        return {
            'test_name': 'Upload Files',
            'tests_run': len(results),
            'tests_passed': passed_tests,
            'tests_failed': len(results) - passed_tests,
            'errors': errors,
            'results': results,
            'file_uris': file_uris  # Return file URIs for use in other tests
        }
    
    def _get_files_to_upload(self) -> Dict[str, Dict[str, str]]:
        """Get the list of files to upload with their purposes."""
        # Base path to test files
        test_files_dir = Path(__file__).parent.parent.parent / "test_files"
        
        # Map file keys to actual PDF files and their purposes
        files = {
            # Contract documents (3 files)
            "contract_1": {
                "path": str(test_files_dir / "2502.16143v1.pdf"),
                "purpose": "contract"
            },
            "contract_2": {
                "path": str(test_files_dir / "Ristoski_RDF2Vec.pdf"),
                "purpose": "contract"
            },
            "contract_3": {
                "path": str(test_files_dir / "S16-2027.pdf"),
                "purpose": "contract"
            },
            
            # Financial reports (2 files)
            "financial_1": {
                "path": str(test_files_dir / "srlearn-python-library.pdf"),
                "purpose": "financial"
            },
            "financial_2": {
                "path": str(test_files_dir / "tutorial.pdf"),
                "purpose": "financial"
            },
            
            # Marketing materials (2 files)
            "marketing_1": {
                "path": str(test_files_dir / "TimurChabuk_1.pdf"),
                "purpose": "marketing"
            },
            "marketing_2": {
                "path": str(test_files_dir / "w_keva178.pdf"),
                "purpose": "marketing"
            },
            
            # Technical specifications (2 files)
            "technical_1": {
                "path": str(test_files_dir / "Tabling as a Library with Delimited Control.pdf"),
                "purpose": "technical"
            },
            "technical_2": {
                "path": str(test_files_dir / "ruleml09spindle.pdf"),
                "purpose": "technical"
            },
            
            # Legal documents (1 file)
            "legal_1": {
                "path": str(test_files_dir / "yuan.pdf"),
                "purpose": "legal"
            }
        }
        
        return files
    
    async def _test_upload_file(self, space_id: str, graph_id: str, file_key: str, 
                         file_path: str, purpose: str) -> Dict[str, Any]:
        """Test uploading a single file."""
        logger.info(f"\n  Uploading {file_key} ({purpose})...")
        
        try:
            # Check if file exists
            if not Path(file_path).exists():
                return {
                    'name': f'Upload {file_key}',
                    'passed': False,
                    'error': f'File not found: {file_path}'
                }
            
            # Get file size
            file_size = Path(file_path).stat().st_size
            file_name = Path(file_path).name
            
            # Create file node first (metadata)
            from vital_ai_domain.model.FileNode import FileNode
            import uuid
            
            file_node = FileNode()
            file_uri = f"haley:file_{uuid.uuid4().hex[:12]}"
            file_node.URI = file_uri
            file_node.name = file_name
            
            # Create file node metadata
            create_response = await self.client.files.create_file(
                space_id=space_id,
                objects=[file_node],
                graph_id=graph_id
            )
            
            if not create_response.is_success:
                return {
                    'name': f'Upload {file_key}',
                    'passed': False,
                    'error': f'Failed to create file node: {create_response.error_message}'
                }
            
            # Upload file content using streaming with async generator
            generator = AsyncFilePathGenerator(
                file_path=file_path,
                chunk_size=65536,  # 64KB chunks for better performance
                content_type="application/pdf"
            )
            
            # Use async streaming upload
            response = await self.client.files.upload_file_stream_async(
                space_id=space_id,
                graph_id=graph_id,
                file_uri=file_uri,
                source=generator,
                filename=file_name,
                chunk_size=65536
            )
            
            if response.is_success:
                logger.info(f"    ✅ Uploaded: {file_name}")
                logger.info(f"       URI: {file_uri}")
                logger.info(f"       Size: {file_size:,} bytes")
                
                return {
                    'name': f'Upload {file_key}',
                    'passed': True,
                    'details': f'Successfully uploaded {file_name}',
                    'file_uri': file_uri,
                    'file_name': file_name,
                    'file_size': file_size,
                    'purpose': purpose
                }
            else:
                error_msg = response.error_message if hasattr(response, 'error_message') else 'Unknown error'
                return {
                    'name': f'Upload {file_key}',
                    'passed': False,
                    'error': f'Upload failed: {error_msg}'
                }
                
        except Exception as e:
            logger.error(f"    ❌ Error: {e}")
            return {
                'name': f'Upload {file_key}',
                'passed': False,
                'error': str(e)
            }
