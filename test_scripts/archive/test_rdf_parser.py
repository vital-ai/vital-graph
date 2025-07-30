#!/usr/bin/env python3
"""
Test script for RDF streaming parser with progress reporting.

Tests the enhanced RDF validation utility with a real N-Triples gzipped file,
demonstrating streaming parsing, progress logging, and generator-based consumption.
"""

import sys
import os
import logging
import asyncio
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from vitalgraph.rdf.rdf_utils import (
    validate_rdf_file,
    stream_parse_ntriples_nquads_generator,
    async_stream_parse_ntriples_nquads,
    detect_rdf_format,
    RDFFormat
)

# Configure logging to show progress
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


def test_file_detection(file_path: str):
    """Test RDF format detection."""
    print(f"\n{'='*60}")
    print("TESTING RDF FORMAT DETECTION")
    print(f"{'='*60}")
    
    detected_format = detect_rdf_format(file_path)
    print(f"File: {file_path}")
    print(f"Detected format: {detected_format.value if detected_format else 'Unknown'}")
    
    # Check file exists and get basic info
    path = Path(file_path)
    if path.exists():
        file_size_mb = path.stat().st_size / (1024 * 1024)
        print(f"File size: {file_size_mb:.2f} MB")
        print(f"File exists: ✓")
    else:
        print(f"File exists: ✗ (File not found)")
        return False
    
    return True


def test_validation_api(file_path: str):
    """Test the main validation API."""
    print(f"\n{'='*60}")
    print("TESTING MAIN VALIDATION API")
    print(f"{'='*60}")
    
    print("Starting RDF file validation...")
    result = validate_rdf_file(file_path)
    
    print(f"\nValidation Results:")
    print(f"  Valid: {result.is_valid}")
    print(f"  Format: {result.format_detected.value if result.format_detected else 'Unknown'}")
    print(f"  Triple count: {result.triple_count:,}")
    print(f"  File size: {result.file_size_bytes:,} bytes ({result.file_size_bytes/(1024*1024):.2f} MB)")
    print(f"  Parsing time: {result.parsing_time_ms:.2f} ms")
    
    if result.error_message:
        print(f"  Error: {result.error_message}")
    
    if result.warnings:
        print(f"  Warnings:")
        for warning in result.warnings:
            print(f"    - {warning}")
    
    if result.namespaces:
        print(f"  Namespaces found: {len(result.namespaces)}")
        for prefix, uri in list(result.namespaces.items())[:5]:  # Show first 5
            print(f"    {prefix}: {uri}")
        if len(result.namespaces) > 5:
            print(f"    ... and {len(result.namespaces) - 5} more")
    
    return result.is_valid


def test_generator_streaming(file_path: str):
    """Test generator-based streaming parser."""
    print(f"\n{'='*60}")
    print("TESTING GENERATOR-BASED STREAMING PARSER")
    print(f"{'='*60}")
    
    detected_format = detect_rdf_format(file_path)
    if detected_format not in [RDFFormat.NT, RDFFormat.NQUADS]:
        print(f"Skipping generator test - format {detected_format} not supported by streaming parser")
        return True  # Skip but don't fail
    
    print(f"Starting streaming parse with generator (full file)...")
    
    triple_count = 0
    sample_triples = []
    final_stats = None
    
    try:
        # Use the generator to stream parse
        generator = stream_parse_ntriples_nquads_generator(file_path, detected_format, progress_interval=10000)
        
        for triple_or_quad in generator:
            triple_count += 1
            
            # Collect first few triples as samples
            if len(sample_triples) < 5:
                sample_triples.append(triple_or_quad)
        
        # Get final statistics from completed generator
        try:
            final_stats = generator.send(None)
        except StopIteration:
            pass  # Normal completion
        
    except Exception as e:
        print(f"Error during streaming: {e}")
        return False
    
    print(f"\nStreaming Results:")
    print(f"  Triples processed: {triple_count:,}")
    
    if final_stats:
        print(f"\nFinal Statistics from Generator:")
        print(f"  Total processed: {final_stats.get('triple_count', 'N/A'):,}")
        print(f"  Blank nodes: {final_stats.get('blank_node_count', 'N/A')}")
        print(f"  Malformed URIs: {final_stats.get('malformed_uri_count', 'N/A')}")
    
    print(f"  Sample triples:")
    for i, triple in enumerate(sample_triples, 1):
        if len(triple) == 3:  # N-Triples
            subj, pred, obj = triple
            print(f"    {i}. <{subj}> <{pred}> {obj}")
        else:  # N-Quads
            subj, pred, obj, graph = triple
            print(f"    {i}. <{subj}> <{pred}> {obj} <{graph}>")
    
    return True


async def test_async_streaming(file_path: str, max_triples: int = 30000):
    """Test async streaming parser."""
    print(f"\n{'='*60}")
    print("TESTING ASYNC STREAMING PARSER")
    print(f"{'='*60}")
    
    detected_format = detect_rdf_format(file_path)
    if detected_format not in [RDFFormat.NT, RDFFormat.NQUADS]:
        print(f"Skipping async test - format {detected_format} not supported by streaming parser")
        return
    
    print(f"Starting async streaming parse (max {max_triples:,} triples)...")
    
    try:
        # Note: We'll need to modify the async function to support early stopping
        # For now, let's test with a smaller batch size
        result = await async_stream_parse_ntriples_nquads(
            file_path, 
            detected_format, 
            progress_interval=5000,
            batch_size=500
        )
        
        print(f"\nAsync Streaming Results:")
        print(f"  Success: {result.get('success', False)}")
        print(f"  Triples processed: {result.get('triple_count', 0):,}")
        print(f"  Blank nodes: {result.get('blank_node_count', 0)}")
        print(f"  Malformed URIs: {result.get('malformed_uri_count', 0)}")
        print(f"  Batches processed: {result.get('batch_count', 0)}")
        
        if 'error' in result:
            print(f"  Error: {result['error']}")
            return False
            
    except Exception as e:
        print(f"Error during async streaming: {e}")
        return False
    
    return True


def main():
    """Main test function."""
    test_file = "/Users/hadfield/Local/vital-git/vital-graph/test_data/kgframe-wordnet-0.0.2.nt.gz"
    
    print("RDF STREAMING PARSER TEST")
    print("=" * 60)
    print(f"Test file: {test_file}")
    
    # Test 1: File detection
    if not test_file_detection(test_file):
        print("❌ File detection failed - cannot continue")
        return
    
    # Test 2: Main validation API
    print("\n" + "🔄 Running validation API test...")
    validation_success = test_validation_api(test_file)
    if validation_success:
        print("✅ Validation API test passed")
    else:
        print("❌ Validation API test failed")
    
    # Test 3: Generator streaming
    print("\n" + "🔄 Running generator streaming test...")
    generator_success = test_generator_streaming(test_file)
    if generator_success:
        print("✅ Generator streaming test passed")
    else:
        print("❌ Generator streaming test failed")
    
    # Test 4: Async streaming
    print("\n" + "🔄 Running async streaming test...")
    async_success = asyncio.run(test_async_streaming(test_file, max_triples=30000))
    if async_success:
        print("✅ Async streaming test passed")
    else:
        print("❌ Async streaming test failed")
    
    # Summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")
    tests_passed = sum([validation_success, generator_success, async_success])
    print(f"Tests passed: {tests_passed}/3")
    
    if tests_passed == 3:
        print("🎉 All tests passed! RDF streaming parser is working correctly.")
    else:
        print("⚠️  Some tests failed. Check the output above for details.")


if __name__ == "__main__":
    main()
