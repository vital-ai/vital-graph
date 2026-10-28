"""The DDL that IS a uniqueness declaration (`issues/227`)."""

import pytest

from vitalgraph.entity_registry.entity_registry_schema import EntityRegistrySchema as S


def test_the_index_is_partial_on_the_pair_and_active_rows():
    sql = S.declared_index_sql("business", "EIN", 2)
    assert "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_ident_ein_business" in sql
    assert "(identifier_namespace, identifier_value, entity_type_id)" in sql
    assert "identifier_namespace = 'EIN'" in sql
    assert "entity_type_id = 2" in sql and "status = 'active'" in sql


def test_the_type_id_is_the_one_given_never_a_default():
    # SERIAL ids differ per database (dev: person=1, business=2); the caller
    # resolves it. A hardcoded id would index the wrong type, silently.
    assert "entity_type_id = 7" in S.declared_index_sql("business", "EIN", 7)


def test_names_fit_postgres_and_stay_distinct():
    long_a = S.declared_index_name("business", "X" * 80 + "A")
    long_b = S.declared_index_name("business", "X" * 80 + "B")
    assert len(long_a) <= 63 and len(long_b) <= 63 and long_a != long_b
    assert S.declared_index_name("business", "SF_LEAD_ID") == "uq_ident_sf_lead_id_business"
    assert S.declared_index_name("person", "EIN").startswith("uq_ident_")


def test_a_quote_in_a_namespace_cannot_break_out():
    assert "identifier_namespace = 'O''BRIEN'" in S.declared_index_sql("business", "O'BRIEN", 2)


def test_declarations_are_per_database_not_in_code():
    # Each install has its own identifier namespaces: the index in THAT
    # database is the declaration, named on the command line, never a list in
    # code that every install would ship.
    assert not hasattr(S, "DECLARED_UNIQUE_IDENTIFIERS")


def test_a_pair_is_named_type_colon_namespace():
    import argparse
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "apps/entity_registry/declare_unique_identifiers.py"
    spec = importlib.util.spec_from_file_location("declare_unique_identifiers", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.parse_pair("business:SF_ACCOUNT_ID") == ("business", "SF_ACCOUNT_ID")
    assert mod.parse_pair("person:urn:x") == ("person", "urn:x")
    for bad in ("business", ":NS", "business:"):
        with pytest.raises(argparse.ArgumentTypeError):
            mod.parse_pair(bad)
