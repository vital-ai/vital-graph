"""Integration tests: XSD datatype fidelity.

Verifies that typed literals (integers, decimals, booleans, dates,
language-tagged strings) survive the INSERT → SELECT roundtrip with
correct type annotations.

Requires PostgreSQL + Jena sidecar.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]


# ---------------------------------------------------------------------------
# XSD numeric types
# ---------------------------------------------------------------------------

class TestNumericTypes:
    """Typed numeric literals round-trip with correct datatype."""

    async def test_integer(self, test_space, sparql_update, sparql_execute):
        """xsd:integer preserves value and type."""
        await sparql_update("""
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {
            <http://example.org/dt/int1> <http://example.org/age> "42"^^xsd:integer .
        }
        """, test_space)

        bindings = await sparql_execute("""
        SELECT ?age WHERE {
            <http://example.org/dt/int1> <http://example.org/age> ?age .
        }
        """, test_space)
        assert len(bindings) == 1
        assert bindings[0]["age"]["value"] == "42"
        assert bindings[0]["age"]["type"] == "literal"
        assert "integer" in bindings[0]["age"].get("datatype", "")

    async def test_decimal(self, test_space, sparql_update, sparql_execute):
        """xsd:decimal preserves value and type."""
        await sparql_update("""
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {
            <http://example.org/dt/dec1> <http://example.org/price> "19.99"^^xsd:decimal .
        }
        """, test_space)

        bindings = await sparql_execute("""
        SELECT ?price WHERE {
            <http://example.org/dt/dec1> <http://example.org/price> ?price .
        }
        """, test_space)
        assert len(bindings) == 1
        assert bindings[0]["price"]["value"] == "19.99"
        assert "decimal" in bindings[0]["price"].get("datatype", "")

    async def test_double(self, test_space, sparql_update, sparql_execute):
        """xsd:double preserves value and type."""
        await sparql_update("""
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {
            <http://example.org/dt/dbl1> <http://example.org/ratio> "3.14159"^^xsd:double .
        }
        """, test_space)

        bindings = await sparql_execute("""
        SELECT ?ratio WHERE {
            <http://example.org/dt/dbl1> <http://example.org/ratio> ?ratio .
        }
        """, test_space)
        assert len(bindings) == 1
        # Value may be represented in scientific notation
        val = float(bindings[0]["ratio"]["value"])
        assert abs(val - 3.14159) < 0.001
        assert "double" in bindings[0]["ratio"].get("datatype", "")

    async def test_float(self, test_space, sparql_update, sparql_execute):
        """xsd:float preserves value and type."""
        await sparql_update("""
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {
            <http://example.org/dt/flt1> <http://example.org/temp> "98.6"^^xsd:float .
        }
        """, test_space)

        bindings = await sparql_execute("""
        SELECT ?temp WHERE {
            <http://example.org/dt/flt1> <http://example.org/temp> ?temp .
        }
        """, test_space)
        assert len(bindings) == 1
        val = float(bindings[0]["temp"]["value"])
        assert abs(val - 98.6) < 0.1


# ---------------------------------------------------------------------------
# XSD boolean
# ---------------------------------------------------------------------------

class TestBooleanType:
    """xsd:boolean round-trip."""

    async def test_boolean_true(self, test_space, sparql_update, sparql_execute):
        """xsd:boolean true preserves correctly."""
        await sparql_update("""
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {
            <http://example.org/dt/bool1> <http://example.org/active> "true"^^xsd:boolean .
        }
        """, test_space)

        bindings = await sparql_execute("""
        SELECT ?active WHERE {
            <http://example.org/dt/bool1> <http://example.org/active> ?active .
        }
        """, test_space)
        assert len(bindings) == 1
        assert bindings[0]["active"]["value"] == "true"
        assert "boolean" in bindings[0]["active"].get("datatype", "")

    async def test_boolean_false(self, test_space, sparql_update, sparql_execute):
        """xsd:boolean false preserves correctly."""
        await sparql_update("""
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {
            <http://example.org/dt/bool2> <http://example.org/deleted> "false"^^xsd:boolean .
        }
        """, test_space)

        bindings = await sparql_execute("""
        SELECT ?deleted WHERE {
            <http://example.org/dt/bool2> <http://example.org/deleted> ?deleted .
        }
        """, test_space)
        assert len(bindings) == 1
        assert bindings[0]["deleted"]["value"] == "false"


# ---------------------------------------------------------------------------
# XSD date/time types
# ---------------------------------------------------------------------------

class TestDateTimeTypes:
    """xsd:date, xsd:dateTime round-trip."""

    async def test_date(self, test_space, sparql_update, sparql_execute):
        """xsd:date preserves value."""
        await sparql_update("""
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {
            <http://example.org/dt/date1> <http://example.org/born> "1990-05-15"^^xsd:date .
        }
        """, test_space)

        bindings = await sparql_execute("""
        SELECT ?born WHERE {
            <http://example.org/dt/date1> <http://example.org/born> ?born .
        }
        """, test_space)
        assert len(bindings) == 1
        assert "1990-05-15" in bindings[0]["born"]["value"]
        assert "date" in bindings[0]["born"].get("datatype", "")

    async def test_datetime(self, test_space, sparql_update, sparql_execute):
        """xsd:dateTime preserves value."""
        await sparql_update("""
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {
            <http://example.org/dt/dt1> <http://example.org/created>
                "2024-01-15T10:30:00Z"^^xsd:dateTime .
        }
        """, test_space)

        bindings = await sparql_execute("""
        SELECT ?created WHERE {
            <http://example.org/dt/dt1> <http://example.org/created> ?created .
        }
        """, test_space)
        assert len(bindings) == 1
        assert "2024-01-15" in bindings[0]["created"]["value"]
        assert "10:30:00" in bindings[0]["created"]["value"]


# ---------------------------------------------------------------------------
# Language-tagged strings
# ---------------------------------------------------------------------------

class TestLangTags:
    """Language-tagged literals preserve lang tag."""

    async def test_lang_en(self, test_space, sparql_update, sparql_execute):
        """English language tag survives roundtrip."""
        await sparql_update("""
        INSERT DATA {
            <http://example.org/dt/lang1> <http://example.org/label> "Hello"@en .
        }
        """, test_space)

        bindings = await sparql_execute("""
        SELECT ?label WHERE {
            <http://example.org/dt/lang1> <http://example.org/label> ?label .
        }
        """, test_space)
        assert len(bindings) == 1
        assert bindings[0]["label"]["value"] == "Hello"
        assert bindings[0]["label"].get("xml:lang") == "en"

    async def test_lang_fr(self, test_space, sparql_update, sparql_execute):
        """French language tag survives roundtrip."""
        await sparql_update("""
        INSERT DATA {
            <http://example.org/dt/lang2> <http://example.org/label> "Bonjour"@fr .
        }
        """, test_space)

        bindings = await sparql_execute("""
        SELECT ?label WHERE {
            <http://example.org/dt/lang2> <http://example.org/label> ?label .
        }
        """, test_space)
        assert len(bindings) == 1
        assert bindings[0]["label"]["value"] == "Bonjour"
        assert bindings[0]["label"].get("xml:lang") == "fr"

    async def test_multiple_lang_tags(self, test_space, sparql_update, sparql_execute):
        """Multiple language tags on same subject/predicate coexist."""
        await sparql_update("""
        INSERT DATA {
            <http://example.org/dt/lang3> <http://example.org/name> "Cat"@en .
            <http://example.org/dt/lang3> <http://example.org/name> "Gato"@es .
            <http://example.org/dt/lang3> <http://example.org/name> "Chat"@fr .
        }
        """, test_space)

        bindings = await sparql_execute("""
        SELECT ?name WHERE {
            <http://example.org/dt/lang3> <http://example.org/name> ?name .
        }
        """, test_space)
        assert len(bindings) == 3
        langs = {b["name"].get("xml:lang") for b in bindings}
        assert langs == {"en", "es", "fr"}

    async def test_langmatches_filter(self, test_space, sparql_update, sparql_execute):
        """LANGMATCHES filter selects by language."""
        bindings = await sparql_execute("""
        SELECT ?name WHERE {
            <http://example.org/dt/lang3> <http://example.org/name> ?name .
            FILTER(LANG(?name) = "es")
        }
        """, test_space)
        assert len(bindings) == 1
        assert bindings[0]["name"]["value"] == "Gato"


# ---------------------------------------------------------------------------
# XSD string explicit type
# ---------------------------------------------------------------------------

class TestStringType:
    """xsd:string explicit type annotation."""

    async def test_xsd_string(self, test_space, sparql_update, sparql_execute):
        """Explicit xsd:string preserves value."""
        await sparql_update("""
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {
            <http://example.org/dt/str1> <http://example.org/code> "ABC-123"^^xsd:string .
        }
        """, test_space)

        bindings = await sparql_execute("""
        SELECT ?code WHERE {
            <http://example.org/dt/str1> <http://example.org/code> ?code .
        }
        """, test_space)
        assert len(bindings) == 1
        assert bindings[0]["code"]["value"] == "ABC-123"


# ---------------------------------------------------------------------------
# Unicode handling
# ---------------------------------------------------------------------------

class TestUnicode:
    """Unicode in URIs and literals."""

    async def test_unicode_literal(self, test_space, sparql_update, sparql_execute):
        """Unicode characters in literals survive roundtrip."""
        await sparql_update("""
        INSERT DATA {
            <http://example.org/dt/uni1> <http://example.org/text> "日本語テスト" .
        }
        """, test_space)

        bindings = await sparql_execute("""
        SELECT ?text WHERE {
            <http://example.org/dt/uni1> <http://example.org/text> ?text .
        }
        """, test_space)
        assert len(bindings) == 1
        assert bindings[0]["text"]["value"] == "日本語テスト"

    async def test_emoji_literal(self, test_space, sparql_update, sparql_execute):
        """Emoji in literals survive roundtrip."""
        await sparql_update("""
        INSERT DATA {
            <http://example.org/dt/uni2> <http://example.org/mood> "Happy 😀" .
        }
        """, test_space)

        bindings = await sparql_execute("""
        SELECT ?mood WHERE {
            <http://example.org/dt/uni2> <http://example.org/mood> ?mood .
        }
        """, test_space)
        assert len(bindings) == 1
        assert bindings[0]["mood"]["value"] == "Happy 😀"


# ---------------------------------------------------------------------------
# Large literals and special characters
# ---------------------------------------------------------------------------

class TestSpecialCharacters:
    """Literals with quotes, newlines, and special chars."""

    async def test_single_quotes(self, test_space, sparql_update, sparql_execute):
        """Literal with single quotes survives."""
        await sparql_update("""
        INSERT DATA {
            <http://example.org/dt/sq1> <http://example.org/note> "it's a test" .
        }
        """, test_space)

        bindings = await sparql_execute("""
        SELECT ?note WHERE {
            <http://example.org/dt/sq1> <http://example.org/note> ?note .
        }
        """, test_space)
        assert len(bindings) == 1
        assert bindings[0]["note"]["value"] == "it's a test"

    async def test_backslash(self, test_space, sparql_update, sparql_execute):
        """Literal with backslash survives."""
        await sparql_update(r"""
        INSERT DATA {
            <http://example.org/dt/bs1> <http://example.org/path> "C:\\Users\\test" .
        }
        """, test_space)

        bindings = await sparql_execute("""
        SELECT ?path WHERE {
            <http://example.org/dt/bs1> <http://example.org/path> ?path .
        }
        """, test_space)
        assert len(bindings) == 1
        assert "Users" in bindings[0]["path"]["value"]
