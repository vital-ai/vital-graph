"""
Abstract base class for VitalGraph operations.

Provides a framework for tracking long-running operations like imports,
exports, and other graph operations with status tracking and error handling.
"""

import time
import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime


class OperationStatus(Enum):
    """Status of a graph operation."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class OperationResult:
    """Result of a graph operation."""
    status: OperationStatus
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[Exception] = None
    warnings: List[str] = field(default_factory=list)
    
    def is_success(self) -> bool:
        """Check if the operation was successful."""
        return self.status == OperationStatus.SUCCESS
    
    def is_error(self) -> bool:
        """Check if the operation failed."""
        return self.status == OperationStatus.ERROR


class GraphOp(ABC):
    """Abstract base class for graph operations.
    
    Provides a framework for tracking operations with status, timing,
    progress reporting, and error handling.
    """
    
    def __init__(self, operation_id: Optional[str] = None):
        """Initialize the operation.
        
        Args:
            operation_id: Optional unique identifier for this operation
        """
        self.operation_id = operation_id or self._generate_operation_id()
        self.status = OperationStatus.PENDING
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.result: Optional[OperationResult] = None
        self.progress_message = ""
        self.logger = logging.getLogger(f"{self.__class__.__module__}.{self.__class__.__name__}")
        
    def _generate_operation_id(self) -> str:
        """Generate a unique operation ID."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{self.__class__.__name__.lower()}_{timestamp}"
    
    @abstractmethod
    def execute(self) -> OperationResult:
        """Execute the operation.
        
        Returns:
            OperationResult with the outcome of the operation
        """
        pass
    
    @abstractmethod
    def get_operation_name(self) -> str:
        """Get a human-readable name for this operation."""
        pass
    
    def run(self) -> OperationResult:
        """Run the operation with status tracking and error handling.
        
        Returns:
            OperationResult with the outcome of the operation
        """
        self.logger.info(f"Starting {self.get_operation_name()} (ID: {self.operation_id})")
        
        self.status = OperationStatus.RUNNING
        self.start_time = time.time()
        
        try:
            self.result = self.execute()
            self.status = self.result.status
            
            if self.result.is_success():
                self.logger.info(f"Successfully completed {self.get_operation_name()}")
            else:
                self.logger.error(f"Failed {self.get_operation_name()}: {self.result.message}")
                
        except Exception as e:
            self.logger.exception(f"Exception during {self.get_operation_name()}")
            self.result = OperationResult(
                status=OperationStatus.ERROR,
                message=f"Unexpected error: {str(e)}",
                error=e
            )
            self.status = OperationStatus.ERROR
            
        finally:
            self.end_time = time.time()
            
        return self.result
    
    def get_duration(self) -> Optional[float]:
        """Get the duration of the operation in seconds.
        
        Returns:
            Duration in seconds, or None if not completed
        """
        if self.start_time is None:
            return None
        end_time = self.end_time or time.time()
        return end_time - self.start_time
    
    def get_status_info(self) -> Dict[str, Any]:
        """Get comprehensive status information about the operation.
        
        Returns:
            Dictionary with operation status details
        """
        info = {
            'operation_id': self.operation_id,
            'operation_name': self.get_operation_name(),
            'status': self.status.value,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration_seconds': self.get_duration(),
            'progress_message': self.progress_message
        }
        
        if self.result:
            info.update({
                'result_message': self.result.message,
                'result_details': self.result.details,
                'warnings': self.result.warnings,
                'has_error': self.result.is_error()
            })
            
        return info
    
    def update_progress(self, message: str):
        """Update the progress message for this operation.
        
        Args:
            message: Progress message to display
        """
        self.progress_message = message
        self.logger.info(f"Progress: {message}")
    
    def cancel(self):
        """Cancel the operation if possible.
        
        Note: Subclasses should override this if they support cancellation.
        """
        if self.status == OperationStatus.RUNNING:
            self.status = OperationStatus.CANCELLED
            self.logger.info(f"Cancelled {self.get_operation_name()}")
