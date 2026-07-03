"""VitalGraph Client — Ontology Endpoint

Provides methods to query ontology classes and their properties.
"""

from __future__ import annotations

import logging

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError
from ...model.ontology_model import OntologyProperty, OntologyPropertiesResponse, OntologyClassesResponse

logger = logging.getLogger(__name__)

class OntologyClientEndpoint(BaseEndpoint):
    """Client endpoint for ontology introspection."""

    async def list_classes(self) -> OntologyClassesResponse:
        """List all known ontology class URIs.

        Returns:
            OntologyClassesResponse with list of class URIs.
        """
        self._check_connection()

        url = f"{self._get_server_url().rstrip('/')}/api/ontology/classes"
        response = await self._make_authenticated_request("GET", url)
        return OntologyClassesResponse.model_validate(response.json())

    async def get_properties(self, class_uri: str) -> OntologyPropertiesResponse:
        """Get properties for a given ontology class URI.

        Args:
            class_uri: VitalSigns class URI to introspect.

        Returns:
            OntologyPropertiesResponse with property list and count.
        """
        self._check_connection()

        url = f"{self._get_server_url().rstrip('/')}/api/ontology/properties"
        params = {"class_uri": class_uri}
        response = await self._make_authenticated_request("GET", url, params=params)
        return OntologyPropertiesResponse.model_validate(response.json())
