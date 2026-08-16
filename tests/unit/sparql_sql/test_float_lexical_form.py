"""An xsd:float is printed at the width xsd:float has (issues/094).

PostgreSQL stores an `xsd:float` cast as `REAL` — binary32 — and prints the
shortest string that round-trips AT THAT WIDTH:

    SELECT CAST('+33.3300' AS REAL)::text   ->  33.33

The driver hands the value back as a Python `float`, which is binary64. Every
default rendering then prints the shortest string that round-trips at DOUBLE
width, and that is the exact decimal expansion of the binary32 value:

    str(<same value>)                       ->  33.33000183105469

Sixteen digits of binary noise, in a form no engine and no specification
produces, returned to anyone who calls `xsd:float`. The value was never wrong;
the width it was printed at was.

The second half of the defect was WHERE it happened. `sql_to_sparql_binding`
stringified the value BEFORE reading the datatype companion column, so the
datatype could not inform the rendering even in principle.
"""

from __future__ import annotations

import struct

import pytest

from vitalgraph.db.sparql_sql.sql_type_binding import (
    XSD_DOUBLE,
    XSD_FLOAT,
    _value_to_string,
    normalize_numeric,
    sql_to_sparql_binding,
)


def as_float32(x: float) -> float:
    """The binary64 value you get back after a binary32 round trip."""
    return struct.unpack("f", struct.pack("f", x))[0]


def round_trips(text: str, original: float) -> bool:
    return as_float32(float(text)) == as_float32(original)


class TestFloatLexicalForm:

    def test_the_reported_case(self):
        assert normalize_numeric(as_float32(33.33), XSD_FLOAT) == "33.33"

    @pytest.mark.parametrize("raw,expected", [
        (33.33, "33.33"),
        (-10200.0, "-10200"),
        (1.5, "1.5"),
        (0.0, "0"),
        (1.0, "1"),
        (-1.0, "-1"),
        (2.5, "2.5"),
        (-7.875, "-7.875"),
        (1.25, "1.25"),
        (13.0, "13"),
    ])
    def test_values_from_the_dawg_cast_fixture(self, raw, expected):
        assert normalize_numeric(as_float32(raw), XSD_FLOAT) == expected

    @pytest.mark.parametrize("raw", [
        33.33, -10200.0, 1.5, 0.0, 1.0, 2.5, -7.875, 1.25, 13.0,
        1e6, 1e20, 1e-5, 3.4028235e38, 1.1754944e-38,
    ])
    def test_every_output_round_trips_at_float32(self, raw):
        """The property, not the spelling.

        Any shortening that does not survive a binary32 round trip has changed
        the value — which would be a worse defect than the one being fixed.
        """
        out = normalize_numeric(as_float32(raw), XSD_FLOAT)
        assert round_trips(out, raw)

    def test_no_exponent_for_moderate_magnitudes(self):
        """`%g` alone turns -10200 into `-1.02e+04`; repr's threshold is higher."""
        assert "e" not in normalize_numeric(as_float32(-10200.0), XSD_FLOAT)

    @pytest.mark.parametrize("special", [float("inf"), float("-inf"), float("nan")])
    def test_specials_do_not_raise(self, special):
        normalize_numeric(special, XSD_FLOAT)


class TestNothingElseMoved:

    def test_double_keeps_its_canonical_scientific_form(self):
        """xsd:double is a different datatype with a different canonical form."""
        assert normalize_numeric(1.5, XSD_DOUBLE) == "1.5E0"
        assert normalize_numeric(0.0, XSD_DOUBLE) == "0.0E0"

    def test_a_float_with_no_datatype_is_untouched(self):
        """Only a declared xsd:float gets float32 treatment.

        Without the datatype we do not know the width, and guessing would
        silently shorten genuine doubles.
        """
        assert _value_to_string(33.33000183105469) == "33.33000183105469"

    @pytest.mark.parametrize("value,expected", [
        (True, "true"), (False, "false"), (3, "3"), ("text", "text"),
    ])
    def test_other_python_types(self, value, expected):
        assert _value_to_string(value) == expected


class TestTheDatatypeIsReadBeforeTheValueIsRendered:
    """The ordering bug underneath, pinned so it cannot come back.

    `sql_to_sparql_binding` used to call `_value_to_string(value)` first and
    look up `__datatype` afterwards. Any fix to the formatter alone would have
    had no effect on this path — and this is the path the conformance suite
    uses.
    """

    def test_binding_uses_the_datatype_companion(self):
        row = {"v0": as_float32(33.33), "v0__type": "L", "v0__datatype": XSD_FLOAT}
        b = sql_to_sparql_binding("v0", row["v0"], row)
        assert b.value == "33.33"
        assert b.datatype == XSD_FLOAT

    def test_binding_without_a_datatype_is_unchanged(self):
        row = {"v0": 33.33000183105469, "v0__type": "L"}
        assert sql_to_sparql_binding("v0", row["v0"], row).value == "33.33000183105469"
