"""
Tests for geo_slot_handler — parsing geo slot values and the auto-populate pipeline.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from vitalgraph.vectorization.geo_slot_handler import (
    parse_geo_slot_value,
    GEO_SLOT_CLASS_URI,
    GEO_SLOT_VALUE_PRED,
)


class TestParseGeoSlotValue:
    """Test parse_geo_slot_value with various input formats."""

    def test_comma_separated(self):
        assert parse_geo_slot_value("40.73,-73.93") == (40.73, -73.93)

    def test_comma_separated_spaces(self):
        assert parse_geo_slot_value("  40.73 , -73.93  ") == (40.73, -73.93)

    def test_space_separated(self):
        assert parse_geo_slot_value("51.5 -0.12") == (51.5, -0.12)

    def test_json_lat_lon(self):
        assert parse_geo_slot_value('{"lat": 40.73, "lon": -73.93}') == (40.73, -73.93)

    def test_json_latitude_longitude(self):
        assert parse_geo_slot_value('{"latitude": 51.5, "longitude": -0.12}') == (51.5, -0.12)

    def test_json_lat_lng(self):
        assert parse_geo_slot_value('{"lat": 35.6, "lng": 139.7}') == (35.6, 139.7)

    def test_xsd_typed_literal(self):
        assert parse_geo_slot_value('"40.73,-73.93"^^<http://www.w3.org/2001/XMLSchema#string>') == (40.73, -73.93)

    def test_empty_string(self):
        assert parse_geo_slot_value("") is None

    def test_none_input(self):
        assert parse_geo_slot_value(None) is None

    def test_invalid_text(self):
        assert parse_geo_slot_value("not a coordinate") is None

    def test_out_of_range_lat(self):
        assert parse_geo_slot_value("91.0,-73.93") is None

    def test_out_of_range_lon(self):
        assert parse_geo_slot_value("40.73,181.0") is None

    def test_negative_out_of_range_lat(self):
        assert parse_geo_slot_value("-91.0,0.0") is None

    def test_boundary_values(self):
        assert parse_geo_slot_value("90.0,180.0") == (90.0, 180.0)
        assert parse_geo_slot_value("-90.0,-180.0") == (-90.0, -180.0)

    def test_zero_zero(self):
        assert parse_geo_slot_value("0.0,0.0") == (0.0, 0.0)

    def test_json_out_of_range(self):
        assert parse_geo_slot_value('{"lat": 100, "lon": 0}') is None

    def test_single_number(self):
        assert parse_geo_slot_value("40.73") is None

    def test_three_numbers(self):
        # Three comma-separated — only first two are used (takes first comma split)
        result = parse_geo_slot_value("40.73,-73.93,100")
        # "-73.93,100" is not a valid float
        assert result is None


class TestConstants:
    """Verify constants are correct URIs."""

    def test_geo_slot_class_uri(self):
        assert GEO_SLOT_CLASS_URI == "http://vital.ai/ontology/haley-ai-kg#KGGeoLocationSlot"

    def test_geo_slot_value_pred(self):
        assert GEO_SLOT_VALUE_PRED == "http://vital.ai/ontology/haley-ai-kg#hasGeoLocationSlotValue"


class TestDefaultPredicates:
    """Verify the expanded default predicate sets include vital-aimp namespace."""

    def test_lat_predicates_include_aimp(self):
        from vitalgraph.vectorization.geo_config_manager import DEFAULT_LAT_PREDICATES
        assert "http://vital.ai/ontology/vital-aimp#hasLatitude" in DEFAULT_LAT_PREDICATES
        assert "http://vital.ai/ontology/haley-ai-kg#hasLatitude" in DEFAULT_LAT_PREDICATES
        assert "http://www.w3.org/2003/01/geo/wgs84_pos#lat" in DEFAULT_LAT_PREDICATES

    def test_lon_predicates_include_aimp(self):
        from vitalgraph.vectorization.geo_config_manager import DEFAULT_LON_PREDICATES
        assert "http://vital.ai/ontology/vital-aimp#hasLongitude" in DEFAULT_LON_PREDICATES
        assert "http://vital.ai/ontology/haley-ai-kg#hasLongitude" in DEFAULT_LON_PREDICATES
        assert "http://www.w3.org/2003/01/geo/wgs84_pos#long" in DEFAULT_LON_PREDICATES


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
