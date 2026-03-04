"""
VitalGraph Client Utilities

Shared utilities and helper functions for VitalGraph client endpoints.
"""

from typing import Dict, Any, Optional


class VitalGraphClientError(Exception):
    """Base exception for VitalGraph client errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def validate_required_params(**params):
    """
    Validate that required parameters are provided.
    
    Args:
        **params: Parameter name-value pairs to validate
        
    Raises:
        VitalGraphClientError: If any required parameter is missing or None
    """
    for param_name, param_value in params.items():
        if param_value is None or param_value == "":
            raise VitalGraphClientError(f"Required parameter '{param_name}' is missing or empty")


def build_query_params(**params) -> Dict[str, Any]:
    """
    Build query parameters dictionary, filtering out None values.
    
    Args:
        **params: Parameter name-value pairs
        
    Returns:
        Dictionary with non-None parameters
    """
    return {k: v for k, v in params.items() if v is not None}