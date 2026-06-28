"""
Tests for vector index REINDEX maintenance in MaintenanceJob.

Tests the candidate evaluation logic (scoring, thresholds, cooldown)
without requiring a live database connection.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from datetime import datetime, timedelta, timezone

from vitalgraph.process.maintenance_job import (
    MaintenanceJob,
    VECTOR_REINDEX_DEAD_RATIO,
    VECTOR_REINDEX_MIN_DEAD,
    VECTOR_REINDEX_COOLDOWN_HOURS,
)


class TestEvaluateVectorCandidate:
    """Test MaintenanceJob._evaluate_vector_candidate static method."""

    SPACE_IDS = ["test_space", "other_space"]
    NOW = datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)

    def _make_row(self, relname, n_live, n_dead, last_vacuum=None):
        return {
            "relname": relname,
            "n_live_tup": n_live,
            "n_dead_tup": n_dead,
            "last_vacuum": last_vacuum,
            "last_autovacuum": None,
        }

    def test_eligible_high_dead_ratio(self):
        """Table with >20% dead ratio and >1000 dead tuples should be eligible."""
        row = self._make_row("test_space_vec_default", 5000, 2000)
        result = MaintenanceJob._evaluate_vector_candidate(row, self.SPACE_IDS, self.NOW, False)
        assert result is not None
        assert result["space_id"] == "test_space"
        assert result["index_name"] == "default"
        assert result["score"] > 0

    def test_skip_low_dead_count(self):
        """Table with <1000 dead tuples should be skipped."""
        row = self._make_row("test_space_vec_default", 1000, 500)
        result = MaintenanceJob._evaluate_vector_candidate(row, self.SPACE_IDS, self.NOW, False)
        assert result is None

    def test_skip_low_ratio(self):
        """Table with dead ratio < 20% should be skipped."""
        row = self._make_row("test_space_vec_default", 100000, 5000)
        result = MaintenanceJob._evaluate_vector_candidate(row, self.SPACE_IDS, self.NOW, False)
        assert result is None  # 5% ratio

    def test_skip_recent_vacuum(self):
        """Table vacuumed within cooldown period should be skipped."""
        recent = self.NOW - timedelta(hours=12)
        row = self._make_row("test_space_vec_default", 5000, 2000, last_vacuum=recent)
        result = MaintenanceJob._evaluate_vector_candidate(row, self.SPACE_IDS, self.NOW, False)
        assert result is None

    def test_eligible_old_vacuum(self):
        """Table vacuumed beyond cooldown period should be eligible."""
        old = self.NOW - timedelta(hours=48)
        row = self._make_row("test_space_vec_default", 5000, 2000, last_vacuum=old)
        result = MaintenanceJob._evaluate_vector_candidate(row, self.SPACE_IDS, self.NOW, False)
        assert result is not None

    def test_force_bypasses_thresholds(self):
        """Force=True should ignore dead count, ratio, and cooldown."""
        recent = self.NOW - timedelta(hours=1)
        row = self._make_row("test_space_vec_default", 100000, 100, last_vacuum=recent)
        result = MaintenanceJob._evaluate_vector_candidate(row, self.SPACE_IDS, self.NOW, True)
        assert result is not None

    def test_unknown_table_name(self):
        """Table not matching any space prefix should return None."""
        row = self._make_row("unknown_space_vec_default", 5000, 2000)
        result = MaintenanceJob._evaluate_vector_candidate(row, self.SPACE_IDS, self.NOW, False)
        assert result is None

    def test_non_vector_table(self):
        """Table not matching _vec_ pattern should return None."""
        row = self._make_row("test_space_rdf_quad", 5000, 2000)
        result = MaintenanceJob._evaluate_vector_candidate(row, self.SPACE_IDS, self.NOW, False)
        assert result is None

    def test_score_increases_with_dead_ratio(self):
        """Higher dead ratio should produce higher score."""
        row_low = self._make_row("test_space_vec_idx1", 5000, 1500)
        row_high = self._make_row("test_space_vec_idx1", 5000, 4000)
        r_low = MaintenanceJob._evaluate_vector_candidate(row_low, self.SPACE_IDS, self.NOW, True)
        r_high = MaintenanceJob._evaluate_vector_candidate(row_high, self.SPACE_IDS, self.NOW, True)
        assert r_low is not None and r_high is not None
        assert r_high["score"] > r_low["score"]

    def test_multiple_spaces_correct_match(self):
        """Should correctly identify space_id from table name."""
        row = self._make_row("other_space_vec_embeddings", 5000, 2000)
        result = MaintenanceJob._evaluate_vector_candidate(row, self.SPACE_IDS, self.NOW, False)
        assert result is not None
        assert result["space_id"] == "other_space"
        assert result["index_name"] == "embeddings"

    def test_index_name_with_underscores(self):
        """Index names with underscores should be correctly extracted."""
        row = self._make_row("test_space_vec_my_custom_index", 5000, 2000)
        result = MaintenanceJob._evaluate_vector_candidate(row, self.SPACE_IDS, self.NOW, False)
        assert result is not None
        assert result["index_name"] == "my_custom_index"

    def test_hnsw_index_name_format(self):
        """Verify the HNSW index name that would be used for REINDEX."""
        row = self._make_row("test_space_vec_default", 5000, 2000)
        result = MaintenanceJob._evaluate_vector_candidate(row, self.SPACE_IDS, self.NOW, False)
        assert result is not None
        expected_hnsw = f"idx_{result['space_id']}_vec_{result['index_name']}_hnsw"
        assert expected_hnsw == "idx_test_space_vec_default_hnsw"


class TestThresholdConstants:
    """Verify threshold constants are reasonable."""

    def test_dead_ratio_threshold(self):
        assert 0 < VECTOR_REINDEX_DEAD_RATIO <= 0.5

    def test_min_dead_threshold(self):
        assert VECTOR_REINDEX_MIN_DEAD >= 100

    def test_cooldown_hours(self):
        assert VECTOR_REINDEX_COOLDOWN_HOURS >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
