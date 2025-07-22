"""
File Utilities for VitalGraph

Provides utilities for file type detection, handling compressed files, and general file operations.
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any
from enum import Enum


class FileType(Enum):
    """Supported file types for detection."""
    # RDF formats
    RDF_TURTLE = "turtle"
    RDF_XML = "xml"
    RDF_N3 = "n3"
    RDF_NT = "nt"
    RDF_JSON_LD = "json-ld"
    RDF_TRIG = "trig"
    RDF_NQUADS = "nquads"
    
    # General formats
    JSON = "json"
    XML = "xml"
    CSV = "csv"
    TSV = "tsv"
    TXT = "txt"
    
    # Compressed
    GZIP = "gzip"
    ZIP = "zip"
    TAR = "tar"
    
    # Unknown
    UNKNOWN = "unknown"


def get_file_extension(file_path: str, handle_compressed: bool = True) -> str:
    """
    Get the file extension, handling compressed files appropriately.
    
    Args:
        file_path: Path to the file
        handle_compressed: If True, for compressed files like .nt.gz, return .nt
                          If False, return .gz
    
    Returns:
        File extension (with leading dot)
    """
    path = Path(file_path)
    
    if handle_compressed and path.suffix.lower() == '.gz' and len(path.suffixes) >= 2:
        # For files like .nt.gz, .nq.gz, return the extension before .gz
        return path.suffixes[-2].lower()
    else:
        return path.suffix.lower()


def detect_rdf_format(file_path: str, content_sample: Optional[str] = None) -> Optional[FileType]:
    """
    Detect RDF format from file extension and content.
    
    Args:
        file_path: Path to the RDF file
        content_sample: Optional sample of file content for content-based detection
    
    Returns:
        Detected RDF FileType or None if not an RDF file
    """
    extension = get_file_extension(file_path, handle_compressed=True)
    
    # Map file extensions to RDF formats
    rdf_extension_map = {
        '.ttl': FileType.RDF_TURTLE,
        '.turtle': FileType.RDF_TURTLE,
        '.rdf': FileType.RDF_XML,
        '.xml': FileType.RDF_XML,
        '.n3': FileType.RDF_N3,
        '.nt': FileType.RDF_NT,
        '.jsonld': FileType.RDF_JSON_LD,
        '.json': FileType.RDF_JSON_LD,  # Could be regular JSON too
        '.trig': FileType.RDF_TRIG,
        '.nq': FileType.RDF_NQUADS,
        '.nquads': FileType.RDF_NQUADS
    }
    
    detected_format = rdf_extension_map.get(extension)
    
    # If we have content sample, try to refine detection
    if content_sample and detected_format is None:
        content_lower = content_sample.lower().strip()
        
        # Check for XML/RDF patterns
        if content_lower.startswith('<?xml') or '<rdf:' in content_lower:
            detected_format = FileType.RDF_XML
        # Check for JSON-LD patterns
        elif content_lower.startswith('{') and '@context' in content_lower:
            detected_format = FileType.RDF_JSON_LD
        # Check for Turtle patterns
        elif '@prefix' in content_lower or content_lower.startswith('@base'):
            detected_format = FileType.RDF_TURTLE
        # Check for N-Triples patterns (simple heuristic)
        elif '.' in content_lower and '<' in content_lower and '>' in content_lower:
            detected_format = FileType.RDF_NT
    
    return detected_format


def detect_file_type(file_path: str, content_sample: Optional[str] = None) -> FileType:
    """
    Detect general file type from extension and content.
    
    Args:
        file_path: Path to the file
        content_sample: Optional sample of file content for content-based detection
    
    Returns:
        Detected FileType
    """
    path = Path(file_path)
    
    # Check if it's a compressed file first
    if path.suffix.lower() in ['.gz', '.zip', '.tar']:
        if path.suffix.lower() == '.gz':
            # For gzipped files, also check the inner extension
            inner_extension = get_file_extension(file_path, handle_compressed=True)
            rdf_format = detect_rdf_format(file_path, content_sample)
            if rdf_format:
                return rdf_format
            return FileType.GZIP
        elif path.suffix.lower() == '.zip':
            return FileType.ZIP
        elif path.suffix.lower() == '.tar':
            return FileType.TAR
    
    # Check for RDF formats
    rdf_format = detect_rdf_format(file_path, content_sample)
    if rdf_format:
        return rdf_format
    
    # Check for other common formats
    extension = path.suffix.lower()
    general_extension_map = {
        '.json': FileType.JSON,
        '.xml': FileType.XML,
        '.csv': FileType.CSV,
        '.tsv': FileType.TSV,
        '.txt': FileType.TXT,
    }
    
    detected_type = general_extension_map.get(extension, FileType.UNKNOWN)
    
    # Content-based refinement for ambiguous cases
    if content_sample and detected_type == FileType.UNKNOWN:
        content_lower = content_sample.lower().strip()
        
        if content_lower.startswith('{') or content_lower.startswith('['):
            detected_type = FileType.JSON
        elif content_lower.startswith('<?xml') or content_lower.startswith('<'):
            detected_type = FileType.XML
    
    return detected_type


def is_compressed_file(file_path: str) -> bool:
    """
    Check if a file is compressed based on its extension.
    
    Args:
        file_path: Path to the file
    
    Returns:
        True if the file appears to be compressed
    """
    path = Path(file_path)
    compressed_extensions = {'.gz', '.zip', '.tar', '.bz2', '.xz', '.7z'}
    return path.suffix.lower() in compressed_extensions


def get_file_info(file_path: str) -> Dict[str, Any]:
    """
    Get comprehensive information about a file.
    
    Args:
        file_path: Path to the file
    
    Returns:
        Dictionary with file information
    """
    path = Path(file_path)
    
    if not path.exists():
        return {
            'exists': False,
            'path': str(path.absolute()),
            'error': 'File not found'
        }
    
    try:
        stat = path.stat()
        file_type = detect_file_type(file_path)
        
        # Try to read a small sample for content detection
        content_sample = None
        try:
            if stat.st_size > 0 and stat.st_size < 10 * 1024 * 1024:  # Only for files < 10MB
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content_sample = f.read(1024)  # Read first 1KB
        except (UnicodeDecodeError, PermissionError):
            pass  # Binary file or permission issue
        
        # Re-detect with content sample if available
        if content_sample:
            file_type = detect_file_type(file_path, content_sample)
        
        return {
            'exists': True,
            'path': str(path.absolute()),
            'name': path.name,
            'stem': path.stem,
            'suffix': path.suffix,
            'size_bytes': stat.st_size,
            'size_mb': round(stat.st_size / (1024 * 1024), 2),
            'modified_time': stat.st_mtime,
            'is_file': path.is_file(),
            'is_directory': path.is_dir(),
            'is_compressed': is_compressed_file(file_path),
            'detected_type': file_type.value,
            'extension': get_file_extension(file_path, handle_compressed=True),
            'full_extension': path.suffix.lower()
        }
    
    except Exception as e:
        return {
            'exists': True,
            'path': str(path.absolute()),
            'error': f'Error reading file info: {str(e)}'
        }
