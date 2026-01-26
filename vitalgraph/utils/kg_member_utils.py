from __future__ import annotations


class KGMemberUtils:
    """Utility class for checking KG grouping URI properties."""

    @staticmethod
    def has_entity_grouping_uri(graph_object: 'GraphObject', uri: str) -> bool:
        """Check if graph object has entity grouping URI equal to given URI."""
        if graph_object is None:
            return False
        
        # Only check entity grouping for valid graph object types
        from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge
        from vital_ai_vitalsigns.model.VITAL_GraphContainerObject import VITAL_GraphContainerObject
        from vital_ai_vitalsigns.model.VITAL_HyperEdge import VITAL_HyperEdge
        from vital_ai_vitalsigns.model.VITAL_HyperNode import VITAL_HyperNode
        from vital_ai_vitalsigns.model.VITAL_Node import VITAL_Node
        
        if not isinstance(graph_object, (VITAL_Edge, VITAL_GraphContainerObject, VITAL_HyperEdge, VITAL_HyperNode, VITAL_Node)):
            return False
        
        try:
            grouping_value = graph_object.kGGraphURI
            return str(grouping_value) == str(uri) if grouping_value is not None else False
        except:
            return False

    @staticmethod
    def has_frame_grouping_uri(graph_object: 'GraphObject', uri: str) -> bool:
        """Check if graph object has frame grouping URI equal to given URI."""
        if graph_object is None:
            return False
        
        # Only check frame grouping for frame-related objects
        from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
        from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
        from ai_haley_kg_domain.model.KGFrame import KGFrame
        from ai_haley_kg_domain.model.KGSlot import KGSlot
        
        if not isinstance(graph_object, (Edge_hasKGFrame, Edge_hasKGSlot, KGFrame, KGSlot)):
            return False
        
        try:
            grouping_value = graph_object.frameGraphURI
            return str(grouping_value) == str(uri) if grouping_value is not None else False
        except:
            return False
