"""
Data inspection script for Phase 0 of the SPARQL-to-SQL pipeline.

Connects to the existing PostgreSQL database, discovers spaces, and reports
on the shape and content of the RDF data. The output informs SPARQL test
case design and expected results.

Usage:
    python test_scripts/jena_sidecar/inspect_data.py
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import psycopg
import psycopg.rows


def _get_sync_connection():
    """Open a synchronous psycopg connection using PG* env vars."""
    import os
    return psycopg.connect(
        host=os.environ.get('PGHOST', 'localhost'),
        port=int(os.environ.get('PGPORT', '5432')),
        dbname=os.environ.get('PGDATABASE', 'sparql_sql_graph'),
        user=os.environ.get('PGUSER', 'postgres'),
        password=os.environ.get('PGPASSWORD', ''),
        row_factory=psycopg.rows.dict_row,
    )


def discover_spaces(conn):
    """Find all RDF space table sets by looking for term tables."""
    cur = conn.cursor()
    # Tables follow pattern: {space_id}_term and {space_id}_rdf_quad
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name LIKE '%%_term'
          AND table_name NOT LIKE '%%_rdf_quad'
        ORDER BY table_name
    """)
    rows = cur.fetchall()
    spaces = []
    for row in rows:
        term_table = row['table_name']
        # Pattern: {space_id}_term
        space_id = term_table.rsplit('_term', 1)[0]
        quad_table = f"{space_id}_rdf_quad"

        # Verify quad table exists
        cur.execute("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
        """, (quad_table,))
        if not cur.fetchone():
            continue

        # Check quad count to skip empty spaces
        cur.execute(f"SELECT COUNT(*) AS cnt FROM {quad_table}")
        quad_count = cur.fetchone()['cnt']

        spaces.append({
            'space_id': space_id,
            'term_table': term_table,
            'quad_table': quad_table,
            'namespace_table': f"{space_id}_namespace",
            'datatype_table': f"{space_id}_datatype",
            'graph_table': f"{space_id}_graph",
            'quad_count': quad_count,
        })

    # Sort by quad count descending so most populated spaces come first
    spaces.sort(key=lambda s: s['quad_count'], reverse=True)
    return spaces


def inspect_term_table(conn, table):
    """Report on the term table contents."""
    cur = conn.cursor()

    # Total count
    cur.execute(f"SELECT COUNT(*) AS cnt FROM {table}")
    total = cur.fetchone()['cnt']
    print(f"  Total terms: {total:,}")

    # Breakdown by type
    cur.execute(f"""
        SELECT term_type, COUNT(*) AS cnt
        FROM {table}
        GROUP BY term_type
        ORDER BY cnt DESC
    """)
    for row in cur.fetchall():
        label = {'U': 'URI', 'L': 'Literal', 'B': 'BNode', 'G': 'Graph'}.get(row['term_type'], row['term_type'])
        print(f"    {label} ({row['term_type']}): {row['cnt']:,}")

    # Sample URIs
    cur.execute(f"SELECT term_text FROM {table} WHERE term_type = 'U' LIMIT 10")
    uris = [r['term_text'] for r in cur.fetchall()]
    if uris:
        print(f"  Sample URIs:")
        for u in uris:
            print(f"    {u}")

    # Sample Literals
    cur.execute(f"SELECT term_text, lang, datatype_id FROM {table} WHERE term_type = 'L' LIMIT 10")
    lits = cur.fetchall()
    if lits:
        print(f"  Sample Literals:")
        for r in lits:
            extra = ""
            if r.get('lang'):
                extra = f" @{r['lang']}"
            if r.get('datatype_id'):
                extra += f" (datatype_id={r['datatype_id']})"
            print(f"    \"{r['term_text']}\"{extra}")

    return total


def inspect_quad_table(conn, term_table, quad_table):
    """Report on the quad table contents."""
    cur = conn.cursor()

    # Total count
    cur.execute(f"SELECT COUNT(*) AS cnt FROM {quad_table}")
    total = cur.fetchone()['cnt']
    print(f"  Total quads: {total:,}")

    # Sample quads with resolved terms
    cur.execute(f"""
        SELECT
            s.term_text AS subject,
            p.term_text AS predicate,
            o.term_text AS object,
            c.term_text AS context
        FROM {quad_table} q
        JOIN {term_table} s ON q.subject_uuid = s.term_uuid
        JOIN {term_table} p ON q.predicate_uuid = p.term_uuid
        JOIN {term_table} o ON q.object_uuid = o.term_uuid
        JOIN {term_table} c ON q.context_uuid = c.term_uuid
        LIMIT 10
    """)
    rows = cur.fetchall()
    if rows:
        print(f"  Sample quads (resolved):")
        for r in rows:
            s = _shorten(r['subject'])
            p = _shorten(r['predicate'])
            o = _shorten(r['object'])
            c = _shorten(r['context'])
            print(f"    {s}  {p}  {o}  [{c}]")

    return total


def inspect_predicates(conn, term_table, quad_table):
    """List all distinct predicate URIs."""
    cur = conn.cursor()
    cur.execute(f"""
        SELECT DISTINCT p.term_text AS predicate, COUNT(*) AS cnt
        FROM {quad_table} q
        JOIN {term_table} p ON q.predicate_uuid = p.term_uuid
        GROUP BY p.term_text
        ORDER BY cnt DESC
    """)
    rows = cur.fetchall()
    print(f"  Distinct predicates: {len(rows)}")
    for r in rows:
        print(f"    {_shorten(r['predicate'])}  ({r['cnt']:,} quads)")
    return rows


def inspect_types(conn, term_table, quad_table):
    """List all distinct rdf:type values."""
    cur = conn.cursor()
    RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
    cur.execute(f"""
        SELECT o.term_text AS type_uri, COUNT(*) AS cnt
        FROM {quad_table} q
        JOIN {term_table} p ON q.predicate_uuid = p.term_uuid
        JOIN {term_table} o ON q.object_uuid = o.term_uuid
        WHERE p.term_text = %s
        GROUP BY o.term_text
        ORDER BY cnt DESC
    """, (RDF_TYPE,))
    rows = cur.fetchall()
    print(f"  Distinct rdf:type values: {len(rows)}")
    for r in rows:
        print(f"    {_shorten(r['type_uri'])}  ({r['cnt']:,} instances)")
    return rows


def inspect_named_graphs(conn, term_table, quad_table):
    """List all distinct named graphs (context URIs)."""
    cur = conn.cursor()
    cur.execute(f"""
        SELECT DISTINCT c.term_text AS graph_uri, COUNT(*) AS cnt
        FROM {quad_table} q
        JOIN {term_table} c ON q.context_uuid = c.term_uuid
        GROUP BY c.term_text
        ORDER BY cnt DESC
    """)
    rows = cur.fetchall()
    print(f"  Named graphs: {len(rows)}")
    for r in rows[:20]:  # Limit to 20
        print(f"    {_shorten(r['graph_uri'])}  ({r['cnt']:,} quads)")
    if len(rows) > 20:
        print(f"    ... and {len(rows) - 20} more")
    return rows


def inspect_literal_stats(conn, term_table):
    """Report on language tags and datatypes."""
    cur = conn.cursor()

    # Language tags
    cur.execute(f"""
        SELECT lang, COUNT(*) AS cnt
        FROM {term_table}
        WHERE term_type = 'L' AND lang IS NOT NULL AND lang != ''
        GROUP BY lang
        ORDER BY cnt DESC
    """)
    rows = cur.fetchall()
    if rows:
        print(f"  Language tags:")
        for r in rows:
            print(f"    @{r['lang']}: {r['cnt']:,}")
    else:
        print(f"  Language tags: none")

    # Datatype distribution
    cur.execute(f"""
        SELECT datatype_id, COUNT(*) AS cnt
        FROM {term_table}
        WHERE term_type = 'L' AND datatype_id IS NOT NULL
        GROUP BY datatype_id
        ORDER BY cnt DESC
    """)
    rows = cur.fetchall()
    if rows:
        print(f"  Datatype IDs (in literals):")
        for r in rows:
            print(f"    datatype_id={r['datatype_id']}: {r['cnt']:,}")
    else:
        print(f"  Datatype IDs: none")


def inspect_namespaces(conn, namespace_table):
    """List all registered namespaces."""
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT prefix, namespace_uri FROM {namespace_table} ORDER BY prefix")
        rows = cur.fetchall()
        if rows:
            print(f"  Registered namespaces: {len(rows)}")
            for r in rows:
                print(f"    {r['prefix']}: -> {r['namespace_uri']}")
        else:
            print(f"  Registered namespaces: none")
    except Exception as e:
        print(f"  Namespaces: table not found or error: {e}")
        conn.rollback()


def inspect_datatypes(conn, datatype_table):
    """List all registered datatypes."""
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT datatype_id, datatype_uri, datatype_name FROM {datatype_table} ORDER BY datatype_id")
        rows = cur.fetchall()
        if rows:
            print(f"  Registered datatypes: {len(rows)}")
            for r in rows:
                name = r.get('datatype_name') or ''
                print(f"    id={r['datatype_id']}: {r['datatype_uri']}  {name}")
        else:
            print(f"  Registered datatypes: none")
    except Exception as e:
        print(f"  Datatypes: table not found or error: {e}")
        conn.rollback()


def _shorten(uri, max_len=80):
    """Shorten a URI for display."""
    if not uri:
        return str(uri)
    if len(uri) <= max_len:
        return uri
    return uri[:max_len - 3] + "..."


def main():
    print("=" * 70)
    print("SPARQL-to-SQL Data Inspection")
    print("=" * 70)

    with _get_sync_connection() as conn:
        # Test connection
        cur = conn.cursor()
        cur.execute("SELECT version()")
        version = cur.fetchone()
        print(f"\nPostgreSQL: {list(version.values())[0]}")

        # Discover spaces
        print("\n--- Discovering Spaces ---")
        spaces = discover_spaces(conn)
        if not spaces:
            print("  No RDF spaces found!")
            return

        print(f"\n  Found {len(spaces)} spaces:")
        for s in spaces:
            print(f"    {s['space_id']:50s}  {s['quad_count']:>8,} quads")

        # Only inspect non-empty spaces (top 5)
        non_empty = [s for s in spaces if s['quad_count'] > 0]
        if not non_empty:
            print("\n  All spaces are empty!")
            return

        inspect_spaces = non_empty[:5]
        print(f"\n  Inspecting top {len(inspect_spaces)} non-empty space(s)...")

        for space in inspect_spaces:
            print(f"\n{'=' * 70}")
            print(f"Space: {space['space_id']}  ({space['quad_count']:,} quads)")
            print(f"  Tables: {space['term_table']}, {space['quad_table']}")
            print(f"{'=' * 70}")

            print(f"\n--- Term Table ({space['term_table']}) ---")
            inspect_term_table(conn, space['term_table'])

            print(f"\n--- Quad Table ({space['quad_table']}) ---")
            inspect_quad_table(conn, space['term_table'], space['quad_table'])

            print(f"\n--- Predicates ---")
            inspect_predicates(conn, space['term_table'], space['quad_table'])

            print(f"\n--- rdf:type Values ---")
            inspect_types(conn, space['term_table'], space['quad_table'])

            print(f"\n--- Named Graphs ---")
            inspect_named_graphs(conn, space['term_table'], space['quad_table'])

            print(f"\n--- Literal Statistics ---")
            inspect_literal_stats(conn, space['term_table'])

            print(f"\n--- Namespaces ({space['namespace_table']}) ---")
            inspect_namespaces(conn, space['namespace_table'])

            print(f"\n--- Datatypes ({space['datatype_table']}) ---")
            inspect_datatypes(conn, space['datatype_table'])

    print(f"\n{'=' * 70}")
    print("Inspection complete.")


if __name__ == "__main__":
    main()
