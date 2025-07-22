"""
Graph Import Operation for VitalGraph.

Handles importing RDF files into the graph database with validation,
progress tracking, and error handling.
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any

from .graph_op import GraphOp, OperationResult, OperationStatus
from ..rdf.rdf_utils import validate_rdf_file, RDFValidationResult
from ..utils.file_utils import get_file_info, detect_rdf_format


class GraphImportOp(GraphOp):
    """Graph import operation with RDF validation support.
    
    Initially handles file validation (parsing) as the first step.
    Later will be extended to handle data insertion into the database.
    """
    
    def __init__(self, 
                 file_path: str,
                 space_id: Optional[str] = None,
                 validate_before_import: bool = True,
                 batch_size: int = 50000,
                 operation_id: Optional[str] = None):
        """Initialize the graph import operation.
        
        Args:
            file_path: Path to the RDF file to import
            space_id: Target space ID for the import
            validate_before_import: Whether to validate the file before importing
            batch_size: Number of triples to process in each batch
            operation_id: Optional unique identifier for this operation
        """
        super().__init__(operation_id)
        
        self.file_path = file_path
        self.space_id = space_id
        self.validate_before_import = validate_before_import
        self.batch_size = batch_size
        
        # Operation state
        self.file_info: Optional[Dict[str, Any]] = None
        self.validation_result: Optional[RDFValidationResult] = None
        self.import_stats: Dict[str, Any] = {}
        
    def get_operation_name(self) -> str:
        """Get a human-readable name for this operation."""
        return f"Graph Import: {Path(self.file_path).name}"
    
    def execute(self) -> OperationResult:
        """Execute the graph import operation.
        
        Returns:
            OperationResult with the outcome of the import
        """
        try:
            # Step 1: Check file existence and get basic info
            self.update_progress("Checking file...")
            if not self._check_file_exists():
                return OperationResult(
                    status=OperationStatus.ERROR,
                    message=f"File not found: {self.file_path}"
                )
            
            # Step 2: Get file information
            self.update_progress("Analyzing file...")
            self.file_info = get_file_info(self.file_path)
            
            if 'error' in self.file_info:
                return OperationResult(
                    status=OperationStatus.ERROR,
                    message=f"Error reading file: {self.file_info['error']}"
                )
            
            # Step 3: Validate RDF format detection
            detected_format = detect_rdf_format(self.file_path)
            if not detected_format:
                return OperationResult(
                    status=OperationStatus.ERROR,
                    message=f"Unable to detect RDF format for file: {self.file_path}",
                    details={'file_info': self.file_info}
                )
            
            self.logger.info(f"Detected RDF format: {detected_format.value}")
            
            # Step 4: Validate file if requested
            if self.validate_before_import:
                self.update_progress("Validating RDF file...")
                validation_result = self._validate_rdf_file()
                
                if not validation_result.is_success():
                    return validation_result
            
            # Step 5: TODO - Actual import (not implemented yet)
            self.update_progress("Import validation completed successfully")
            
            # For now, we only do validation
            warnings = []
            if self.validation_result and self.validation_result.warnings:
                warnings.extend(self.validation_result.warnings)
            
            warnings.append("Note: Actual data import not yet implemented - validation only")
            
            return OperationResult(
                status=OperationStatus.SUCCESS,
                message=f"Import validation completed successfully for {Path(self.file_path).name}",
                details={
                    'file_info': self.file_info,
                    'validation_result': self._validation_result_to_dict() if self.validation_result else None,
                    'import_stats': self.import_stats
                },
                warnings=warnings
            )
            
        except Exception as e:
            self.logger.exception("Error during graph import operation")
            return OperationResult(
                status=OperationStatus.ERROR,
                message=f"Import failed: {str(e)}",
                error=e,
                details={
                    'file_info': self.file_info,
                    'validation_result': self._validation_result_to_dict() if self.validation_result else None
                }
            )
    
    def _check_file_exists(self) -> bool:
        """Check if the file exists and is readable.
        
        Returns:
            True if file exists and is readable
        """
        try:
            path = Path(self.file_path)
            return path.exists() and path.is_file()
        except Exception as e:
            self.logger.error(f"Error checking file existence: {e}")
            return False
    
    def _validate_rdf_file(self) -> OperationResult:
        """Validate the RDF file using the streaming parser.
        
        Returns:
            OperationResult indicating validation success or failure
        """
        try:
            self.logger.info(f"Starting RDF validation for: {self.file_path}")
            
            # Use the enhanced RDF validation utility
            self.validation_result = validate_rdf_file(self.file_path)
            
            if not self.validation_result.is_valid:
                return OperationResult(
                    status=OperationStatus.ERROR,
                    message=f"RDF validation failed: {self.validation_result.error_message}",
                    details={
                        'validation_result': self._validation_result_to_dict(),
                        'file_info': self.file_info
                    },
                    warnings=self.validation_result.warnings
                )
            
            # Log validation success details
            self.logger.info(f"RDF validation successful:")
            self.logger.info(f"  - Format: {self.validation_result.format_detected.value if self.validation_result.format_detected else 'Unknown'}")
            self.logger.info(f"  - Triples: {self.validation_result.triple_count:,}")
            self.logger.info(f"  - File size: {self.validation_result.file_size_bytes / (1024*1024):.2f} MB")
            self.logger.info(f"  - Parse time: {self.validation_result.parsing_time_ms:.2f} ms")
            
            if self.validation_result.warnings:
                for warning in self.validation_result.warnings:
                    self.logger.warning(f"  - Warning: {warning}")
            
            return OperationResult(
                status=OperationStatus.SUCCESS,
                message="RDF validation completed successfully",
                details={'validation_result': self._validation_result_to_dict()},
                warnings=self.validation_result.warnings
            )
            
        except Exception as e:
            self.logger.exception("Error during RDF validation")
            return OperationResult(
                status=OperationStatus.ERROR,
                message=f"RDF validation error: {str(e)}",
                error=e
            )
    
    def _validation_result_to_dict(self) -> Dict[str, Any]:
        """Convert RDFValidationResult to dictionary for serialization.
        
        Returns:
            Dictionary representation of validation result
        """
        if not self.validation_result:
            return {}
        
        return {
            'is_valid': self.validation_result.is_valid,
            'format_detected': self.validation_result.format_detected.value if self.validation_result.format_detected else None,
            'triple_count': self.validation_result.triple_count,
            'file_size_bytes': self.validation_result.file_size_bytes,
            'file_size_mb': round(self.validation_result.file_size_bytes / (1024*1024), 2),
            'parsing_time_ms': self.validation_result.parsing_time_ms,
            'error_message': self.validation_result.error_message,
            'warnings': self.validation_result.warnings,
            'namespaces_count': len(self.validation_result.namespaces) if self.validation_result.namespaces else 0
        }
    
    def get_import_summary(self) -> Dict[str, Any]:
        """Get a summary of the import operation.
        
        Returns:
            Dictionary with import summary information
        """
        summary = {
            'operation_id': self.operation_id,
            'file_path': self.file_path,
            'file_name': Path(self.file_path).name,
            'space_id': self.space_id,
            'status': self.status.value,
            'duration_seconds': self.get_duration(),
            'validate_before_import': self.validate_before_import,
            'batch_size': self.batch_size
        }
        
        if self.file_info:
            summary.update({
                'file_size_mb': self.file_info.get('size_mb', 0),
                'detected_file_type': self.file_info.get('detected_type', 'unknown'),
                'is_compressed': self.file_info.get('is_compressed', False)
            })
        
        if self.validation_result:
            summary.update({
                'validation_successful': self.validation_result.is_valid,
                'triple_count': self.validation_result.triple_count,
                'rdf_format': self.validation_result.format_detected.value if self.validation_result.format_detected else None,
                'parsing_time_ms': self.validation_result.parsing_time_ms,
                'warnings_count': len(self.validation_result.warnings) if self.validation_result.warnings else 0
            })
        
        return summary
