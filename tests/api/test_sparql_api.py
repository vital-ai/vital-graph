"""API tests: SPARQL operations via VitalGraphClient.

Tests SPARQL query, insert, and delete through the REST API.
Based on test_scripts/vitalgraph_client_test/sparql_sql/case_triples_crud.py
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]


# ---------------------------------------------------------------------------
# SPARQL Query
# ---------------------------------------------------------------------------

class TestSparqlQuery:
    """SPARQL SELECT queries via REST API."""

    async def test_simple_select(self, vg_client, test_space):
        """Execute a trivial SELECT — returns empty or populated bindings."""
        from vitalgraph.model.sparql_model import SPARQLQueryRequest

        req = SPARQLQueryRequest(query="SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 1")
        result = await vg_client.sparql.execute_sparql_query(test_space, req)
        # Should succeed even if empty
        assert result.error is None or result.results is not None


# ---------------------------------------------------------------------------
# SPARQL INSERT + SELECT roundtrip
# ---------------------------------------------------------------------------

class TestSparqlInsertAndQuery:
    """SPARQL INSERT DATA + SELECT roundtrip via REST API."""

    async def test_insert_then_select(self, vg_client, test_space):
        """Insert a triple and query it back."""
        from vitalgraph.model.sparql_model import SPARQLInsertRequest, SPARQLQueryRequest

        subj = f"http://example.org/sparqltest/{uuid.uuid4().hex[:8]}"

        # Insert
        ins_req = SPARQLInsertRequest(
            update=f'INSERT DATA {{ <{subj}> <http://example.org/name> "SparqlApiTest" . }}'
        )
        ins_result = await vg_client.sparql.execute_sparql_insert(test_space, ins_req)
        assert ins_result.success, f"Insert failed: {ins_result.error}"

        # Query back
        q_req = SPARQLQueryRequest(
            query=f'SELECT ?name WHERE {{ <{subj}> <http://example.org/name> ?name . }}'
        )
        q_result = await vg_client.sparql.execute_sparql_query(test_space, q_req)
        assert q_result.error is None

        bindings = q_result.results.get("bindings", []) if q_result.results else []
        assert len(bindings) >= 1
        assert bindings[0]["name"]["value"] == "SparqlApiTest"

    async def test_delete_data(self, vg_client, test_space):
        """Insert then DELETE DATA and verify removal."""
        from vitalgraph.model.sparql_model import (
            SPARQLInsertRequest, SPARQLDeleteRequest, SPARQLQueryRequest,
        )

        subj = f"http://example.org/sparqltest/{uuid.uuid4().hex[:8]}"
        triple = f'<{subj}> <http://example.org/val> "ToDelete" .'

        # Insert
        ins_req = SPARQLInsertRequest(update=f"INSERT DATA {{ {triple} }}")
        await vg_client.sparql.execute_sparql_insert(test_space, ins_req)

        # Delete
        del_req = SPARQLDeleteRequest(update=f"DELETE DATA {{ {triple} }}")
        del_result = await vg_client.sparql.execute_sparql_delete(test_space, del_req)
        assert del_result.success

        # Verify gone
        q_req = SPARQLQueryRequest(
            query=f"SELECT ?o WHERE {{ <{subj}> <http://example.org/val> ?o }}"
        )
        q_result = await vg_client.sparql.execute_sparql_query(test_space, q_req)
        bindings = q_result.results.get("bindings", []) if q_result.results else []
        assert len(bindings) == 0


# ---------------------------------------------------------------------------
# SPARQL UPDATE (general-purpose DELETE/INSERT WHERE)
# ---------------------------------------------------------------------------

class TestSparqlUpdate:
    """SPARQL UPDATE operations via REST API (sparql_update_endpoint)."""

    async def test_update_modify_literal(self, vg_client, test_space):
        """INSERT DATA, then use DELETE/INSERT WHERE to change a literal value."""
        from vitalgraph.model.sparql_model import (
            SPARQLInsertRequest, SPARQLUpdateRequest, SPARQLQueryRequest,
        )

        subj = f"http://example.org/sparqltest/{uuid.uuid4().hex[:8]}"
        pred = "http://example.org/status"

        # Seed data
        ins_req = SPARQLInsertRequest(
            update=f'INSERT DATA {{ <{subj}> <{pred}> "draft" . }}'
        )
        ins_result = await vg_client.sparql.execute_sparql_insert(test_space, ins_req)
        assert ins_result.success, f"Seed insert failed: {ins_result.error}"

        # SPARQL UPDATE: change "draft" → "published"
        upd_req = SPARQLUpdateRequest(
            update=(
                f"DELETE {{ <{subj}> <{pred}> ?old }} "
                f"INSERT {{ <{subj}> <{pred}> \"published\" }} "
                f"WHERE {{ <{subj}> <{pred}> ?old }}"
            )
        )
        upd_result = await vg_client.sparql.execute_sparql_update(test_space, upd_req)
        assert upd_result.success, f"Update failed: {upd_result.error}"
        assert upd_result.update_time is not None
        assert upd_result.update_time >= 0

        # Verify new value
        q_req = SPARQLQueryRequest(
            query=f"SELECT ?val WHERE {{ <{subj}> <{pred}> ?val }}"
        )
        q_result = await vg_client.sparql.execute_sparql_query(test_space, q_req)
        bindings = q_result.results.get("bindings", []) if q_result.results else []
        assert len(bindings) == 1
        assert bindings[0]["val"]["value"] == "published"

    async def test_update_insert_where(self, vg_client, test_space):
        """Use INSERT WHERE to add a derived triple based on existing data."""
        from vitalgraph.model.sparql_model import (
            SPARQLInsertRequest, SPARQLUpdateRequest, SPARQLQueryRequest,
        )

        subj = f"http://example.org/sparqltest/{uuid.uuid4().hex[:8]}"
        name_pred = "http://example.org/name"
        flag_pred = "http://example.org/hasName"

        # Seed
        ins_req = SPARQLInsertRequest(
            update=f'INSERT DATA {{ <{subj}> <{name_pred}> "Alice" . }}'
        )
        await vg_client.sparql.execute_sparql_insert(test_space, ins_req)

        # INSERT WHERE — add a flag triple if name exists
        upd_req = SPARQLUpdateRequest(
            update=(
                f"INSERT {{ <{subj}> <{flag_pred}> \"true\" }} "
                f"WHERE {{ <{subj}> <{name_pred}> ?n }}"
            )
        )
        upd_result = await vg_client.sparql.execute_sparql_update(test_space, upd_req)
        assert upd_result.success, f"Update failed: {upd_result.error}"

        # Verify flag was added
        q_req = SPARQLQueryRequest(
            query=f"SELECT ?f WHERE {{ <{subj}> <{flag_pred}> ?f }}"
        )
        q_result = await vg_client.sparql.execute_sparql_query(test_space, q_req)
        bindings = q_result.results.get("bindings", []) if q_result.results else []
        assert len(bindings) == 1
        assert bindings[0]["f"]["value"] == "true"

    async def test_update_delete_where(self, vg_client, test_space):
        """Use DELETE WHERE to remove triples matching a pattern."""
        from vitalgraph.model.sparql_model import (
            SPARQLInsertRequest, SPARQLUpdateRequest, SPARQLQueryRequest,
        )

        subj = f"http://example.org/sparqltest/{uuid.uuid4().hex[:8]}"
        pred = "http://example.org/tag"

        # Seed multiple triples
        ins_req = SPARQLInsertRequest(
            update=(
                f'INSERT DATA {{ '
                f'<{subj}> <{pred}> "alpha" . '
                f'<{subj}> <{pred}> "beta" . '
                f'<{subj}> <{pred}> "gamma" . '
                f'}}'
            )
        )
        await vg_client.sparql.execute_sparql_insert(test_space, ins_req)

        # DELETE WHERE — remove all tags
        upd_req = SPARQLUpdateRequest(
            update=f"DELETE WHERE {{ <{subj}> <{pred}> ?tag }}"
        )
        upd_result = await vg_client.sparql.execute_sparql_update(test_space, upd_req)
        assert upd_result.success, f"Update failed: {upd_result.error}"

        # Verify all gone
        q_req = SPARQLQueryRequest(
            query=f"SELECT ?tag WHERE {{ <{subj}> <{pred}> ?tag }}"
        )
        q_result = await vg_client.sparql.execute_sparql_query(test_space, q_req)
        bindings = q_result.results.get("bindings", []) if q_result.results else []
        assert len(bindings) == 0

    async def test_update_no_match_is_noop(self, vg_client, test_space):
        """UPDATE with no matching WHERE clause succeeds as a no-op."""
        from vitalgraph.model.sparql_model import SPARQLUpdateRequest

        nonexistent = f"http://example.org/sparqltest/{uuid.uuid4().hex[:8]}"

        upd_req = SPARQLUpdateRequest(
            update=(
                f"DELETE {{ <{nonexistent}> ?p ?o }} "
                f"WHERE {{ <{nonexistent}> ?p ?o }}"
            )
        )
        upd_result = await vg_client.sparql.execute_sparql_update(test_space, upd_req)
        assert upd_result.success, f"No-op update should succeed: {upd_result.error}"


# ---------------------------------------------------------------------------
# SPARQL Query via GET
# ---------------------------------------------------------------------------

class TestSparqlQueryGet:
    """SPARQL SELECT queries via GET endpoint."""

    async def test_get_query_simple(self, vg_client, test_space):
        """Execute a simple SELECT via GET — returns results."""
        result = await vg_client.sparql.execute_sparql_query_get(
            test_space, "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 1"
        )
        assert result.error is None or result.results is not None

    async def test_get_query_matches_post(self, vg_client, test_space):
        """GET query returns same results as POST for identical query."""
        from vitalgraph.model.sparql_model import SPARQLInsertRequest, SPARQLQueryRequest

        # Insert a triple to ensure non-empty result
        tag = uuid.uuid4().hex[:8]
        subj = f"http://example.org/gettest/{tag}"
        ins = SPARQLInsertRequest(
            update=f'INSERT DATA {{ <{subj}> <http://example.org/p> "get_test_{tag}" . }}'
        )
        await vg_client.sparql.execute_sparql_insert(test_space, ins)

        query = f'SELECT ?o WHERE {{ <{subj}> <http://example.org/p> ?o }}'

        # POST
        post_result = await vg_client.sparql.execute_sparql_query(
            test_space, SPARQLQueryRequest(query=query)
        )
        # GET
        get_result = await vg_client.sparql.execute_sparql_query_get(test_space, query)

        post_bindings = post_result.results.get("bindings", []) if post_result.results else []
        get_bindings = get_result.results.get("bindings", []) if get_result.results else []

        assert len(get_bindings) == len(post_bindings)
        assert get_bindings[0]["o"]["value"] == f"get_test_{tag}"


# ---------------------------------------------------------------------------
# Form-based SPARQL insert / delete / update
# ---------------------------------------------------------------------------

class TestSparqlFormBased:
    """SPARQL operations via form-encoded POST (W3C Protocol compatibility)."""

    async def test_insert_form(self, vg_client, test_space):
        """Insert a triple via form-encoded endpoint and verify with query."""
        from vitalgraph.model.sparql_model import SPARQLQueryRequest

        tag = uuid.uuid4().hex[:8]
        subj = f"http://example.org/formtest/{tag}"
        update = f'INSERT DATA {{ <{subj}> <http://example.org/p> "form_insert_{tag}" . }}'

        result = await vg_client.sparql.execute_sparql_insert_form(test_space, update)
        assert result.success

        # Verify triple exists
        qr = await vg_client.sparql.execute_sparql_query(
            test_space, SPARQLQueryRequest(query=f'SELECT ?o WHERE {{ <{subj}> <http://example.org/p> ?o }}')
        )
        bindings = qr.results.get("bindings", []) if qr.results else []
        assert len(bindings) == 1
        assert bindings[0]["o"]["value"] == f"form_insert_{tag}"

    async def test_delete_form(self, vg_client, test_space):
        """Delete a triple via form-encoded endpoint and verify removal."""
        from vitalgraph.model.sparql_model import SPARQLQueryRequest

        tag = uuid.uuid4().hex[:8]
        subj = f"http://example.org/formtest/{tag}"

        # Insert first
        ins = f'INSERT DATA {{ <{subj}> <http://example.org/p> "form_delete_{tag}" . }}'
        await vg_client.sparql.execute_sparql_insert_form(test_space, ins)

        # Delete via form
        delete_sparql = f'DELETE DATA {{ <{subj}> <http://example.org/p> "form_delete_{tag}" . }}'
        result = await vg_client.sparql.execute_sparql_delete_form(test_space, delete_sparql)
        assert result.success

        # Verify removed
        qr = await vg_client.sparql.execute_sparql_query(
            test_space, SPARQLQueryRequest(query=f'SELECT ?o WHERE {{ <{subj}> <http://example.org/p> ?o }}')
        )
        bindings = qr.results.get("bindings", []) if qr.results else []
        assert len(bindings) == 0

    async def test_update_form(self, vg_client, test_space):
        """Execute a SPARQL UPDATE via form-encoded endpoint."""
        from vitalgraph.model.sparql_model import SPARQLQueryRequest

        tag = uuid.uuid4().hex[:8]
        subj = f"http://example.org/formtest/{tag}"

        # Insert initial value
        ins = f'INSERT DATA {{ <{subj}> <http://example.org/label> "old_{tag}" . }}'
        await vg_client.sparql.execute_sparql_insert_form(test_space, ins)

        # Update via form: delete old, insert new
        upd = (
            f'DELETE {{ <{subj}> <http://example.org/label> "old_{tag}" . }} '
            f'INSERT {{ <{subj}> <http://example.org/label> "new_{tag}" . }} '
            f'WHERE {{ <{subj}> <http://example.org/label> "old_{tag}" . }}'
        )
        result = await vg_client.sparql.execute_sparql_update_form(test_space, upd)
        assert result.success

        # Verify updated
        qr = await vg_client.sparql.execute_sparql_query(
            test_space, SPARQLQueryRequest(query=f'SELECT ?o WHERE {{ <{subj}> <http://example.org/label> ?o }}')
        )
        bindings = qr.results.get("bindings", []) if qr.results else []
        assert len(bindings) == 1
        assert bindings[0]["o"]["value"] == f"new_{tag}"
