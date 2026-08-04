"""API tests: SPARQL operations via VitalGraphClient.

Tests SPARQL query, insert, and delete through the REST API.
Based on test_scripts/vitalgraph_client_test/sparql_sql/case_triples_crud.py
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

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


# ---------------------------------------------------------------------------
# Query form dispatch (issues/024, issues/025)
# ---------------------------------------------------------------------------

class TestQueryFormDispatch:
    """The query form must come from the parser, not a string prefix.

    A SPARQL query does not begin with its form keyword — the grammar is
    ``Prologue ( Select | Construct | Describe | Ask )`` — so any query with a
    PREFIX/BASE prologue or a leading comment used to be misrouted to SELECT.
    """

    @pytest_asyncio.fixture(loop_scope="session")
    async def seeded(self, vg_client, test_space):
        """Insert one known triple and return its subject URI and tag."""
        from vitalgraph.model.sparql_model import SPARQLInsertRequest

        tag = uuid.uuid4().hex[:8]
        subj = f"http://example.org/asktest/{tag}"
        ins = SPARQLInsertRequest(
            update=f'INSERT DATA {{ <{subj}> <http://example.org/name> "ask_{tag}" . }}'
        )
        result = await vg_client.sparql.execute_sparql_insert(test_space, ins)
        assert result.success, f"Seed insert failed: {result.error}"
        return subj, tag

    async def _ask(self, vg_client, test_space, query):
        from vitalgraph.model.sparql_model import SPARQLQueryRequest

        return await vg_client.sparql.execute_sparql_query(
            test_space, SPARQLQueryRequest(query=query)
        )

    async def test_ask_bare_true(self, vg_client, test_space, seeded):
        """Bare ASK that matches — the one form that always worked."""
        subj, _ = seeded
        r = await self._ask(
            vg_client, test_space,
            f'ASK {{ <{subj}> <http://example.org/name> ?o }}',
        )
        assert r.boolean is True

    async def test_ask_bare_false(self, vg_client, test_space, seeded):
        """Bare ASK that does not match must be False, not None."""
        subj, _ = seeded
        r = await self._ask(
            vg_client, test_space,
            f'ASK {{ <{subj}> <http://example.org/name> "definitely_not_here" }}',
        )
        assert r.boolean is False

    async def test_ask_with_prefix_prologue_true(self, vg_client, test_space, seeded):
        """PREFIX prologue must not misroute the ASK to SELECT."""
        subj, tag = seeded
        r = await self._ask(
            vg_client, test_space,
            f'PREFIX ex: <http://example.org/>\n'
            f'ASK {{ <{subj}> ex:name ?o }}',
        )
        assert r.boolean is True
        assert r.results is None, "ASK must not return SELECT-shaped bindings"

    async def test_ask_with_prefix_prologue_false(self, vg_client, test_space, seeded):
        """A prologued ASK matching nothing must be False, never None."""
        subj, _ = seeded
        r = await self._ask(
            vg_client, test_space,
            f'PREFIX ex: <http://example.org/>\n'
            f'ASK {{ <{subj}> ex:name "definitely_not_here" }}',
        )
        assert r.boolean is False

    async def test_ask_with_leading_comment(self, vg_client, test_space, seeded):
        """A comment before the form keyword must not misroute the query."""
        subj, _ = seeded
        r = await self._ask(
            vg_client, test_space,
            f'# leading comment\n'
            f'ASK {{ <{subj}> <http://example.org/name> ?o }}',
        )
        assert r.boolean is True

    async def test_ask_with_base_prologue(self, vg_client, test_space, seeded):
        """A BASE declaration before the form keyword must not misroute it."""
        subj, _ = seeded
        r = await self._ask(
            vg_client, test_space,
            f'BASE <http://example.org/>\n'
            f'ASK {{ <{subj}> <http://example.org/name> ?o }}',
        )
        assert r.boolean is True

    async def test_select_with_prefix_prologue(self, vg_client, test_space, seeded):
        """SELECT still routes correctly with a prologue."""
        subj, tag = seeded
        r = await self._ask(
            vg_client, test_space,
            f'PREFIX ex: <http://example.org/>\n'
            f'SELECT ?o WHERE {{ <{subj}> ex:name ?o }}',
        )
        bindings = r.results.get("bindings", []) if r.results else []
        assert len(bindings) == 1
        assert bindings[0]["o"]["value"] == f"ask_{tag}"
        assert r.boolean is None, "SELECT must not carry a boolean"

    @pytest.mark.parametrize("form", ["CONSTRUCT", "DESCRIBE"])
    @pytest.mark.parametrize("prologue", ["", "PREFIX ex: <http://example.org/>\n"])
    async def test_construct_describe_return_triples(
        self, vg_client, test_space, seeded, form, prologue
    ):
        """CONSTRUCT/DESCRIBE return RDF triples (issues/025).

        These were error-assertions until the forms were implemented: the
        backend used to return WHERE-pattern bindings, and putting those in
        ``triples`` would have claimed they were RDF triples. Now the template
        is instantiated and the describe targets resolved, so the field carries
        what it says.

        Both prologue variants are parametrised because the form is dispatched
        on the parsed ``query_type``, not on a string prefix (issues/024) — a
        PREFIX line must not change the routing.
        """
        subj, _ = seeded
        if form == "CONSTRUCT":
            query = (
                f'{prologue}CONSTRUCT {{ <{subj}> <http://example.org/n> ?o }} '
                f'WHERE {{ <{subj}> <http://example.org/name> ?o }}'
            )
        else:
            query = f'{prologue}DESCRIBE <{subj}>'

        r = await self._ask(vg_client, test_space, query)
        assert r.error is None, f"{form} failed: {r.error}"
        assert r.triples is not None, f"{form} returned no triples field"
        assert r.results is None, "triples must not also arrive as bindings"
        assert r.boolean is None

        assert r.triples, f"{form} returned an empty graph for seeded data"
        for t in r.triples:
            assert set(t) == {"subject", "predicate", "object"}
            # nested SPARQL JSON terms, not flat strings
            assert t["subject"]["type"] in ("uri", "bnode")
            assert t["predicate"]["type"] == "uri"

        if form == "CONSTRUCT":
            # the template's predicate, not the WHERE pattern's — the
            # distinction the old bindings-shaped response could not express
            assert {t["predicate"]["value"] for t in r.triples} == {
                "http://example.org/n"}
        else:
            assert all(t["subject"]["value"] == subj for t in r.triples)


class TestGuardQueryShapes:
    """Lock the ASK shapes the endpoint guards depend on (issues/024).

    ``kgdocuments_endpoint._check_delete_protection`` and
    ``kgframes_endpoint._validate_parent_object`` were hand-rolled as
    ``SELECT … LIMIT 1`` while the adapter returned no boolean. They now use
    ASK. Neither guard had test coverage, so these assert the query shapes
    directly — a silent regression here means a protection check that stops
    protecting.
    """

    _PRED = "http://vital.ai/ontology/haley-ai-kg#hasKGDocumentSegmentTypeURI"
    _MANAGED = [
        "urn:segtype:markdown_section",
        "urn:segtype:paragraph",
        "urn:segtype:segmentation_parent",
        "urn:segtype:text_chunk",
    ]

    async def _q(self, vg_client, space, query):
        from vitalgraph.model.sparql_model import SPARQLQueryRequest

        return await vg_client.sparql.execute_sparql_query(
            space, SPARQLQueryRequest(query=query)
        )

    async def test_delete_protection_ask_with_values(self, vg_client, test_space):
        """ASK + VALUES must distinguish managed segments from user documents."""
        from vitalgraph.model.sparql_model import SPARQLInsertRequest

        g = f"http://example.org/g/{uuid.uuid4().hex[:8]}"
        managed = f"urn:doc:managed_{uuid.uuid4().hex[:8]}"
        plain = f"urn:doc:plain_{uuid.uuid4().hex[:8]}"

        await vg_client.sparql.execute_sparql_insert(test_space, SPARQLInsertRequest(
            update=f'INSERT DATA {{ GRAPH <{g}> {{ '
                   f'<{managed}> <{self._PRED}> <urn:segtype:text_chunk> . '
                   f'<{plain}> <{self._PRED}> <urn:segtype:user_defined> . }} }}'))

        values = " ".join(f"<{t}>" for t in sorted(self._MANAGED))
        tmpl = ('ASK {{ GRAPH <%s> {{ VALUES ?managed {{ %s }} '
                '<{uri}> <%s> ?managed . }} }}' % (g, values, self._PRED))

        r = await self._q(vg_client, test_space, tmpl.format(uri=managed))
        assert r.boolean is True, f"managed segment not detected: {r}"

        r = await self._q(vg_client, test_space, tmpl.format(uri=plain))
        assert r.boolean is False, f"user document wrongly protected: {r}"

        r = await self._q(vg_client, test_space, tmpl.format(uri="urn:doc:nonexistent"))
        assert r.boolean is False

    async def test_parent_object_type_ask(self, vg_client, test_space):
        """ASK on rdf:type must not conflate KGEntity with KGFrame."""
        from vitalgraph.model.sparql_model import SPARQLInsertRequest

        haley = "http://vital.ai/ontology/haley-ai-kg#"
        g = f"http://example.org/g/{uuid.uuid4().hex[:8]}"
        ent = f"urn:e:{uuid.uuid4().hex[:8]}"

        await vg_client.sparql.execute_sparql_insert(test_space, SPARQLInsertRequest(
            update=f'INSERT DATA {{ GRAPH <{g}> {{ <{ent}> a <{haley}KGEntity> . }} }}'))

        r = await self._q(
            vg_client, test_space,
            f'ASK {{ GRAPH <{g}> {{ <{ent}> a <{haley}KGEntity> . }} }}')
        assert r.boolean is True

        r = await self._q(
            vg_client, test_space,
            f'ASK {{ GRAPH <{g}> {{ <{ent}> a <{haley}KGFrame> . }} }}')
        assert r.boolean is False, "entity wrongly identified as frame"
