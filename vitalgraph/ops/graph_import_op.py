"""
Graph Import Operation for VitalGraph.

Handles importing RDF files into the graph database with validation,
progress tracking, and error handling.
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any
from enum import Enum

from .graph_op import GraphOp, OperationResult, OperationStatus
from ..rdf.rdf_utils import validate_rdf_file, RDFValidationResult
from ..utils.file_utils import get_file_info, detect_rdf_format


class ImportMethod(str, Enum):
    """Import method enumeration."""
    PARTITION = "partition"  # Zero-copy partition attachment (Option A)
    TRADITIONAL = "traditional"  # INSERT SELECT with index optimization (Option B)
    AUTO = "auto"  # Automatically choose based on table structure


class GraphImportOp(GraphOp):
    """Graph import operation with RDF validation support.
    
    Initially handles file validation (parsing) as the first step.
    Later will be extended to handle data insertion into the database.
    """
    
    def __init__(self, 
                 file_path: str,
                 space_id: Optional[str] = None,
                 graph_uri: Optional[str] = None,
                 validate_before_import: bool = True,
                 batch_size: int = 50000,
                 import_method: ImportMethod = ImportMethod.AUTO,
                 operation_id: Optional[str] = None,
                 space_impl = None):
        """Initialize the graph import operation.
        
        Args:
            file_path: Path to the RDF file to import
            space_id: Target space ID for the import
            graph_uri: Target graph URI for the import
            validate_before_import: Whether to validate the file before importing
            batch_size: Number of triples to process in each batch
            import_method: Import method (PARTITION, TRADITIONAL, or AUTO)
            operation_id: Optional unique identifier for this operation
            space_impl: PostgreSQL space implementation for database operations
        """
        super().__init__(operation_id)
        
        self.file_path = file_path
        self.space_id = space_id
        self.graph_uri = graph_uri or f"http://vital.ai/graph/import_{operation_id}"
        self.validate_before_import = validate_before_import
        self.batch_size = batch_size
        self.import_method = import_method
        self.space_impl = space_impl
        
        # Operation state
        self.file_info: Optional[Dict[str, Any]] = None
        self.validation_result: Optional[RDFValidationResult] = None
        self.import_stats: Dict[str, Any] = {}
        
    def get_operation_name(self) -> str:
        """Get a human-readable name for this operation."""
        return f"Graph Import: {Path(self.file_path).name}"
    
    async def execute(self) -> OperationResult:
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
            
            # Step 5: Perform actual database import
            if self.space_impl and self.space_id:
                self.update_progress("Performing database import...")
                import_result = await self._perform_database_import()
                
                if not import_result.is_success():
                    return import_result
                
                # Combine warnings from validation and import
                warnings = []
                if self.validation_result and self.validation_result.warnings:
                    warnings.extend(self.validation_result.warnings)
                if import_result.warnings:
                    warnings.extend(import_result.warnings)
                
                return OperationResult(
                    status=OperationStatus.SUCCESS,
                    message=f"Import completed successfully for {Path(self.file_path).name}",
                    details={
                        'file_info': self.file_info,
                        'validation_result': self._validation_result_to_dict() if self.validation_result else None,
                        'import_stats': self.import_stats
                    },
                    warnings=warnings
                )
            else:
                # No database connection - validation only
                self.update_progress("Import validation completed successfully")
                
                warnings = []
                if self.validation_result and self.validation_result.warnings:
                    warnings.extend(self.validation_result.warnings)
                
                warnings.append("Note: Database import skipped - no space implementation provided")
                
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
    
    async def _perform_database_import(self) -> OperationResult:
        """Perform the actual database import using PostgreSQLSpaceDBImport.
        
        Returns:
            OperationResult indicating import success or failure
        """
        try:
            # Import here to avoid circular dependencies
            from ..db.postgresql.space.postgresql_space_db_import import PostgreSQLSpaceDBImport
            
            # Determine import method
            actual_method = await self._determine_import_method()
            
            self.logger.info(f"Starting database import for space: {self.space_id}")
            self.logger.info(f"Import method: {actual_method.value}")
            
            # Create database import handler
            db_import = PostgreSQLSpaceDBImport(self.space_impl)
            
            # Progress callback for import monitoring with detailed logging
            def progress_callback(processed_triples, rate=None):
                # Log progress every 10,000 triples or if rate is significant
                if processed_triples % 10000 == 0 or (rate and rate > 0):
                    if rate:
                        self.update_progress(f"Processed {processed_triples:,} triples ({rate:,.0f} triples/sec)")
                    else:
                        self.update_progress(f"Processed {processed_triples:,} triples")
            
            if actual_method == ImportMethod.PARTITION:
                # Option A: Zero-copy partition import
                result = await self._perform_partition_import(db_import, progress_callback)
            else:
                # Option B: Traditional import with data transfer
                result = await self._perform_traditional_import(db_import, progress_callback)
            
            # Update import method in stats
            if 'import_stats' in result.details:
                result.details['import_stats']['import_method'] = actual_method.value
            
            return result
            
        except Exception as e:
            self.logger.exception("Error during database import")
            return OperationResult(
                status=OperationStatus.ERROR,
                message=f"Database import failed: {str(e)}",
                error=e,
                details={'import_stats': self.import_stats}
            )
    
    async def _determine_import_method(self) -> ImportMethod:
        """Determine the actual import method to use based on configuration and table structure."""
        if self.import_method == ImportMethod.PARTITION:
            return ImportMethod.PARTITION
        elif self.import_method == ImportMethod.TRADITIONAL:
            return ImportMethod.TRADITIONAL
        else:  # AUTO
            # Check if main tables are partitioned
            try:
                async with self.space_impl.get_db_connection() as conn:
                    with conn.cursor() as cursor:
                        table_names = self.space_impl._get_table_names(self.space_id)
                        term_table = table_names['term']
                        
                        # Check if term table is partitioned
                        cursor.execute(f"""
                            SELECT partrelid FROM pg_partitioned_table 
                            WHERE partrelid = '{term_table}'::regclass
                        """)
                        is_partitioned = cursor.fetchone() is not None
                        
                        if is_partitioned:
                            self.logger.info("AUTO mode: Detected partitioned tables, using PARTITION method")
                            return ImportMethod.PARTITION
                        else:
                            self.logger.info("AUTO mode: Detected non-partitioned tables, using TRADITIONAL method")
                            return ImportMethod.TRADITIONAL
            except Exception as e:
                self.logger.warning(f"Could not determine table structure, defaulting to TRADITIONAL: {e}")
                return ImportMethod.TRADITIONAL
    
    async def _perform_partition_import(self, db_import, progress_callback) -> OperationResult:
        """Perform zero-copy partition import (Option A)."""
        self.logger.info("Executing zero-copy partition import")
        
        # Phase 1: Setup partition import session
        self.update_progress("Phase 1: Setting up partition import session...")
        import_session = await db_import.setup_partition_import_session(
            self.space_id, self.graph_uri, batch_size=self.batch_size
        )
        
        # Phase 2-3: Load data into partition session
        self.update_progress("Phase 2-3: Loading data into partition session...")
        load_stats = await db_import.load_ntriples_into_partition_session(
            import_session, 
            self.file_path, 
            self.graph_uri,
            batch_size=self.batch_size,
            progress_callback=progress_callback
        )
        
        # Phase 4: Zero-copy partition attachment
        self.update_progress("Phase 4: Zero-copy partition attachment...")
        attachment_stats = await db_import.attach_partitions_zero_copy(import_session)
        
        # Update import stats
        self.import_stats.update({
            'import_session': import_session,
            'load_stats': load_stats,
            'attachment_stats': attachment_stats,
            'total_triples_imported': load_stats.get('total_triples', 0),
            'total_terms_created': load_stats.get('new_terms_inserted', 0),
            'import_method': 'zero_copy_partition'
        })
        
        self.logger.info(f"Partition import completed successfully:")
        self.logger.info(f"  - Triples imported: {self.import_stats['total_triples_imported']:,}")
        self.logger.info(f"  - Terms created: {self.import_stats['total_terms_created']:,}")
        self.logger.info(f"  - Dataset: {import_session['dataset_value']}")
        
        return OperationResult(
            status=OperationStatus.SUCCESS,
            message="Zero-copy partition import completed successfully",
            details={'import_stats': self.import_stats}
        )
    
    async def _perform_traditional_import(self, db_import, progress_callback) -> OperationResult:
        """Perform traditional import with data transfer (Option B)."""
        self.logger.info("Executing traditional import with data transfer")
        
        # Phase 1: Setup partition import session (but we'll use INSERT instead of attachment)
        self.update_progress("Phase 1: Setting up import session...")
        import_session = await db_import.setup_partition_import_session(
            self.space_id, self.graph_uri, batch_size=self.batch_size
        )
        
        # Phase 2-3: Load data into partition session
        self.update_progress("Phase 2-3: Loading data into import session...")
        load_stats = await db_import.load_ntriples_into_partition_session(
            import_session, 
            self.file_path, 
            self.graph_uri,
            batch_size=self.batch_size,
            progress_callback=progress_callback
        )
        
        # Phase 4: Transfer to main tables using traditional INSERT method
        self.update_progress("Phase 4: Transferring to main tables with index optimization...")
        transfer_stats = await db_import.transfer_partition_data_to_main_tables(
            import_session,
            self.space_id,
            self.graph_uri
        )
        
        # Phase 5: Cleanup
        self.update_progress("Phase 5: Cleaning up temporary tables...")
        await db_import._cleanup_partition_import_session(import_session)
        
        # Update import stats
        self.import_stats.update({
            'import_session': import_session,
            'load_stats': load_stats,
            'transfer_stats': transfer_stats,
            'total_triples_imported': transfer_stats.get('quads_transferred', 0),
            'total_terms_created': transfer_stats.get('terms_transferred', 0),
            'import_method': 'traditional_with_optimization'
        })
        
        self.logger.info(f"Traditional import completed successfully:")
        self.logger.info(f"  - Triples imported: {self.import_stats['total_triples_imported']:,}")
        self.logger.info(f"  - Terms created: {self.import_stats['total_terms_created']:,}")
        
        return OperationResult(
            status=OperationStatus.SUCCESS,
            message="Traditional import completed successfully",
            details={'import_stats': self.import_stats}
        )
