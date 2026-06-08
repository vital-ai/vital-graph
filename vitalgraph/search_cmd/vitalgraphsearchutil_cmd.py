#!/usr/bin/env python3
"""
VitalGraph Search Utility CLI

Manage vector indexes, mappings, population, geo data, and all search modalities
(vector similarity, full-text, fuzzy, geo radius) from a dedicated CLI.

Supports both interactive REPL and non-interactive -c modes.
Connects directly to PostgreSQL via VitalGraphConfig + VitalGraphImpl.
"""

import argparse
import asyncio
import json
import logging
import signal
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.shortcuts import CompleteStyle
from tabulate import tabulate

from vitalgraph.config.config_loader import VitalGraphConfig
from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.vectorization.mapping_manager import MappingManager
from vitalgraph.vectorization.vector_populator import populate_index, PopulationStats
from vitalgraph.vectorization.geo_populator import populate_geo, GeoPopulationStats
from vitalgraph.vectorization.geo_config_manager import GeoConfigManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Run an async coroutine from sync context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def _print_table(rows: List[Dict[str, Any]], headers: List[str]) -> None:
    """Print tabulated data."""
    if not rows:
        print("(no results)")
        return
    table_data = []
    for r in rows:
        table_data.append([str(r.get(h, '')) for h in headers])
    print(tabulate(table_data, headers=headers, tablefmt='simple'))
    print(f"\n({len(rows)} row(s))")


def _parse_flag(args: List[str], flag: str) -> Optional[str]:
    """Extract --flag value from args list, mutating args in place."""
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            val = args[i + 1]
            del args[i:i + 2]
            return val
        if a.startswith(f"{flag}="):
            val = a.split("=", 1)[1]
            del args[i]
            return val
    return None


def _parse_bool_flag(args: List[str], flag: str) -> bool:
    """Extract boolean flag (--yes, --force) from args."""
    for i, a in enumerate(args):
        if a == flag:
            del args[i]
            return True
    return False


# ---------------------------------------------------------------------------
# REPL Class
# ---------------------------------------------------------------------------

class VitalGraphSearchUtilREPL:
    """VitalGraph Search Utility REPL."""

    def __init__(self, log_level: str = "WARNING"):
        self.connected = False
        self.config: Optional[VitalGraphConfig] = None
        self.impl: Optional[VitalGraphImpl] = None
        self.conn = None  # asyncpg connection
        self.current_space: Optional[str] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None

        logging.basicConfig(
            level=getattr(logging, log_level.upper(), logging.WARNING),
            format="%(levelname)s %(name)s: %(message)s",
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _run(self, coro):
        """Run async via persistent loop."""
        if self.loop is None:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
        return self.loop.run_until_complete(coro)

    def cmd_connect(self, args: List[str]) -> bool:
        """Connect to VitalGraphDB via configuration."""
        if self.connected:
            print("Already connected. Use 'disconnect' first.")
            return True
        try:
            print("Loading configuration...")
            self.config = VitalGraphConfig()
            self.impl = VitalGraphImpl(config=self.config)
            print("Connecting to database...")
            result = self._run(self.impl.connect_database())
            if not result:
                print("❌ Connection failed.")
                return True
            # Acquire a raw asyncpg connection for direct SQL
            self.conn = self._run(self._acquire_connection())
            self.connected = True
            print("✅ Connected.")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    async def _acquire_connection(self):
        """Acquire an asyncpg connection from the space backend pool."""
        sb = getattr(self.impl, 'space_backend', None)
        if sb and hasattr(sb, 'db_impl') and sb.db_impl:
            pool = getattr(sb.db_impl, '_pool', None) or getattr(sb.db_impl, 'pool', None)
            if pool:
                return await pool.acquire()
        db_impl = self.impl.get_db_impl()
        if db_impl:
            pool = getattr(db_impl, '_pool', None) or getattr(db_impl, 'pool', None)
            if pool:
                return await pool.acquire()
        raise RuntimeError("Cannot acquire asyncpg connection from backend")

    def cmd_disconnect(self, args: List[str]) -> bool:
        """Disconnect from database."""
        if not self.connected:
            print("Not connected.")
            return True
        try:
            if self.conn:
                sb = getattr(self.impl, 'space_backend', None)
                db_impl = self.impl.get_db_impl() if self.impl else None
                pool = None
                if sb and hasattr(sb, 'db_impl') and sb.db_impl:
                    pool = getattr(sb.db_impl, '_pool', None) or getattr(sb.db_impl, 'pool', None)
                elif db_impl:
                    pool = getattr(db_impl, '_pool', None) or getattr(db_impl, 'pool', None)
                if pool:
                    self._run(pool.release(self.conn))
                self.conn = None
        except Exception:
            pass
        self.connected = False
        self.current_space = None
        print("Disconnected.")
        return True

    def _require_connected(self) -> bool:
        if not self.connected or self.conn is None:
            print("❌ Not connected. Use 'connect' first.")
            return False
        return True

    def _require_space(self) -> Optional[str]:
        if not self.current_space:
            print("❌ No space selected. Use 'use <space>'.")
            return None
        return self.current_space

    # ------------------------------------------------------------------
    # Context
    # ------------------------------------------------------------------

    def cmd_use(self, args: List[str]) -> bool:
        """Set current space: use <space_id>"""
        if not args:
            print("Usage: use <space_id>")
            return True
        self.current_space = args[0]
        print(f"Space set to: {self.current_space}")
        return True

    def cmd_unuse(self, args: List[str]) -> bool:
        """Clear current space."""
        self.current_space = None
        print("Space cleared.")
        return True

    # ------------------------------------------------------------------
    # Index management (2.1–2.4)
    # ------------------------------------------------------------------

    def cmd_index_list(self, args: List[str]) -> bool:
        """List vector indexes: index list [-s SPACE]"""
        if not self._require_connected():
            return True
        space = _parse_flag(args, '-s') or _parse_flag(args, '--space') or self._require_space()
        if not space:
            return True
        try:
            rows = self._run(self.conn.fetch(
                f"SELECT index_name, dimensions, provider, model_name, distance_metric, description "
                f"FROM {space}_vector_index ORDER BY index_name"
            ))
            data = [dict(r) for r in rows]
            _print_table(data, ['index_name', 'dimensions', 'provider', 'model_name', 'distance_metric'])
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_index_create(self, args: List[str]) -> bool:
        """Create vector index: index create -s SPACE --name N --dims D --provider P [--model M]"""
        if not self._require_connected():
            return True
        space = _parse_flag(args, '-s') or _parse_flag(args, '--space') or self._require_space()
        if not space:
            return True
        name = _parse_flag(args, '--name')
        dims_str = _parse_flag(args, '--dims') or _parse_flag(args, '--dimensions')
        provider = _parse_flag(args, '--provider') or 'vitalsigns'
        model = _parse_flag(args, '--model')
        description = _parse_flag(args, '--description') or ''
        metric = _parse_flag(args, '--metric') or 'cosine'

        if not name or not dims_str:
            print("Usage: index create -s SPACE --name N --dims D [--provider P] [--model M]")
            return True
        try:
            dims = int(dims_str)
        except ValueError:
            print("❌ --dims must be an integer")
            return True

        try:
            # Insert into vector_index registry
            self._run(self.conn.execute(
                f"INSERT INTO {space}_vector_index "
                f"(index_name, dimensions, distance_metric, provider, model_name, description) "
                f"VALUES ($1, $2, $3, $4, $5, $6)",
                name, dims, metric, provider, model, description,
            ))
            # Create the vector data table
            from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
            schema = SparqlSQLSchema()
            for stmt in schema.create_vector_data_table_sql(space, name, dims, metric):
                self._run(self.conn.execute(stmt))
            print(f"✅ Created vector index '{name}' ({dims}d, {provider}, {metric})")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_index_delete(self, args: List[str]) -> bool:
        """Delete vector index: index delete -s SPACE --name N [--yes]"""
        if not self._require_connected():
            return True
        space = _parse_flag(args, '-s') or _parse_flag(args, '--space') or self._require_space()
        if not space:
            return True
        name = _parse_flag(args, '--name')
        confirm = _parse_bool_flag(args, '--yes')
        if not name:
            print("Usage: index delete -s SPACE --name N [--yes]")
            return True
        if not confirm:
            answer = input(f"Delete vector index '{name}' and all its data? [y/N] ")
            if answer.lower() != 'y':
                print("Cancelled.")
                return True
        try:
            vec_table = f"{space}_vec_{name}"
            self._run(self.conn.execute(f"DROP TABLE IF EXISTS {vec_table} CASCADE"))
            self._run(self.conn.execute(
                f"DELETE FROM {space}_vector_index WHERE index_name = $1", name
            ))
            print(f"✅ Deleted vector index '{name}'")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_index_info(self, args: List[str]) -> bool:
        """Show index info: index info -s SPACE --name N"""
        if not self._require_connected():
            return True
        space = _parse_flag(args, '-s') or _parse_flag(args, '--space') or self._require_space()
        if not space:
            return True
        name = _parse_flag(args, '--name')
        if not name:
            print("Usage: index info -s SPACE --name N")
            return True
        try:
            row = self._run(self.conn.fetchrow(
                f"SELECT * FROM {space}_vector_index WHERE index_name = $1", name
            ))
            if not row:
                print(f"Index '{name}' not found.")
                return True
            print(f"  Index:      {row['index_name']}")
            print(f"  Dimensions: {row['dimensions']}")
            print(f"  Provider:   {row['provider']}")
            print(f"  Model:      {row['model_name'] or '(default)'}")
            print(f"  Metric:     {row['distance_metric']}")
            print(f"  Created:    {row['created_time']}")
            # Row count
            vec_table = f"{space}_vec_{name}"
            try:
                count = self._run(self.conn.fetchval(f"SELECT COUNT(*) FROM {vec_table}"))
                print(f"  Vectors:    {count}")
            except Exception:
                print(f"  Vectors:    (table not found)")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    # ------------------------------------------------------------------
    # Mapping management (2.5–2.7)
    # ------------------------------------------------------------------

    def cmd_mapping_list(self, args: List[str]) -> bool:
        """List mappings: mapping list -s SPACE [--index N]"""
        if not self._require_connected():
            return True
        space = _parse_flag(args, '-s') or _parse_flag(args, '--space') or self._require_space()
        if not space:
            return True
        index_name = _parse_flag(args, '--index')
        try:
            mgr = MappingManager(self.conn, space)
            mappings = self._run(mgr.list_mappings(index_name=index_name))
            data = [m.to_dict() for m in mappings]
            _print_table(data, ['mapping_id', 'index_name', 'mapping_type', 'source_type', 'enabled'])
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_mapping_create(self, args: List[str]) -> bool:
        """Create mapping: mapping create -s SPACE --index N --type T [--source-type S]"""
        if not self._require_connected():
            return True
        space = _parse_flag(args, '-s') or _parse_flag(args, '--space') or self._require_space()
        if not space:
            return True
        index_name = _parse_flag(args, '--index')
        mapping_type = _parse_flag(args, '--type')
        source_type = _parse_flag(args, '--source-type') or 'default'
        type_uri = _parse_flag(args, '--type-uri')

        if not index_name or not mapping_type:
            print("Usage: mapping create -s SPACE --index N --type T [--source-type S] [--type-uri U]")
            return True
        try:
            mgr = MappingManager(self.conn, space)
            mid = self._run(mgr.create_mapping(
                index_name=index_name,
                mapping_type=mapping_type,
                source_type=source_type,
                type_uri=type_uri,
            ))
            print(f"✅ Created mapping {mid} ({mapping_type} → {index_name})")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_mapping_delete(self, args: List[str]) -> bool:
        """Delete mapping: mapping delete -s SPACE --mapping-id M"""
        if not self._require_connected():
            return True
        space = _parse_flag(args, '-s') or _parse_flag(args, '--space') or self._require_space()
        if not space:
            return True
        mid_str = _parse_flag(args, '--mapping-id')
        if not mid_str:
            print("Usage: mapping delete -s SPACE --mapping-id M")
            return True
        try:
            mid = int(mid_str)
            mgr = MappingManager(self.conn, space)
            deleted = self._run(mgr.delete_mapping(mid))
            if deleted:
                print(f"✅ Deleted mapping {mid}")
            else:
                print(f"Mapping {mid} not found.")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    # ------------------------------------------------------------------
    # Population (2.8–2.10)
    # ------------------------------------------------------------------

    def cmd_populate(self, args: List[str]) -> bool:
        """Populate vector index: populate -s SPACE --index N [--graph-uri G] [--batch-size B]"""
        if not self._require_connected():
            return True
        space = _parse_flag(args, '-s') or _parse_flag(args, '--space') or self._require_space()
        if not space:
            return True
        index_name = _parse_flag(args, '--index')
        graph_uri = _parse_flag(args, '--graph-uri') or _parse_flag(args, '--graph')
        batch_str = _parse_flag(args, '--batch-size') or '100'

        if not index_name:
            print("Usage: populate -s SPACE --index N [--graph-uri G] [--batch-size B]")
            return True
        try:
            batch_size = int(batch_str)
        except ValueError:
            print("❌ --batch-size must be an integer")
            return True

        try:
            # Resolve graph URI to context_uuid
            context_uuid = None
            if graph_uri:
                context_uuid = self._run(self.conn.fetchval(
                    f"SELECT term_uuid FROM {space}_term WHERE term_text = $1 AND term_type = 'U'",
                    graph_uri,
                ))
                if not context_uuid:
                    print(f"❌ Graph URI not found: {graph_uri}")
                    return True
            else:
                # Use all contexts — get the first one as default
                context_uuid = self._run(self.conn.fetchval(
                    f"SELECT DISTINCT context_uuid FROM {space}_rdf_quad LIMIT 1"
                ))
                if not context_uuid:
                    print("❌ No quad data found in space.")
                    return True

            print(f"Populating index '{index_name}' (batch_size={batch_size})...")
            stats: PopulationStats = self._run(populate_index(
                self.conn, space, index_name, context_uuid,
                mapping_type='kgentity',
                batch_size=batch_size,
            ))
            print(f"✅ Done in {stats.elapsed_seconds:.1f}s")
            print(f"   Processed: {stats.subjects_processed}")
            print(f"   Stored:    {stats.embeddings_stored}")
            print(f"   Skipped:   {stats.subjects_skipped}")
            if stats.errors:
                print(f"   Errors:    {len(stats.errors)}")
                for err in stats.errors[:5]:
                    print(f"     - {err}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_populate_geo(self, args: List[str]) -> bool:
        """Populate geo: populate-geo -s SPACE [--graph-uri G]"""
        if not self._require_connected():
            return True
        space = _parse_flag(args, '-s') or _parse_flag(args, '--space') or self._require_space()
        if not space:
            return True
        graph_uri = _parse_flag(args, '--graph-uri') or _parse_flag(args, '--graph')

        try:
            context_uuid = None
            if graph_uri:
                context_uuid = self._run(self.conn.fetchval(
                    f"SELECT term_uuid FROM {space}_term WHERE term_text = $1 AND term_type = 'U'",
                    graph_uri,
                ))
                if not context_uuid:
                    print(f"❌ Graph URI not found: {graph_uri}")
                    return True
            else:
                context_uuid = self._run(self.conn.fetchval(
                    f"SELECT DISTINCT context_uuid FROM {space}_rdf_quad LIMIT 1"
                ))
                if not context_uuid:
                    print("❌ No quad data found.")
                    return True

            print("Populating geo side-table...")
            stats: GeoPopulationStats = self._run(populate_geo(
                self.conn, space, context_uuid,
            ))
            print(f"✅ Done in {stats.elapsed_seconds:.1f}s")
            print(f"   Scanned:    {stats.subjects_scanned}")
            print(f"   Upserted:   {stats.points_upserted}")
            print(f"   Incomplete: {stats.incomplete_pairs}")
            if stats.errors:
                print(f"   Errors:     {len(stats.errors)}")
                for err in stats.errors[:5]:
                    print(f"     - {err}")
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_stats(self, args: List[str]) -> bool:
        """Show vector/geo stats: stats -s SPACE"""
        if not self._require_connected():
            return True
        space = _parse_flag(args, '-s') or _parse_flag(args, '--space') or self._require_space()
        if not space:
            return True
        try:
            # Vector indexes
            indexes = self._run(self.conn.fetch(
                f"SELECT index_name, dimensions, provider FROM {space}_vector_index ORDER BY index_name"
            ))
            print(f"\n{'='*60}")
            print(f"  Space: {space}")
            print(f"{'='*60}")
            print(f"\nVector Indexes ({len(indexes)}):")
            for idx in indexes:
                vec_table = f"{space}_vec_{idx['index_name']}"
                try:
                    count = self._run(self.conn.fetchval(f"SELECT COUNT(*) FROM {vec_table}"))
                except Exception:
                    count = '?'
                print(f"  {idx['index_name']}: {count} vectors ({idx['dimensions']}d, {idx['provider']})")

            # Geo stats
            try:
                geo_count = self._run(self.conn.fetchval(f"SELECT COUNT(*) FROM {space}_geo"))
                print(f"\nGeo Points: {geo_count}")
            except Exception:
                print(f"\nGeo: (table not available)")

            # Geo config
            try:
                geo_cfg = self._run(self.conn.fetchrow(
                    f"SELECT enabled, auto_sync FROM {space}_geo_config LIMIT 1"
                ))
                if geo_cfg:
                    print(f"  Enabled:   {geo_cfg['enabled']}")
                    print(f"  Auto-sync: {geo_cfg['auto_sync']}")
            except Exception:
                pass

            print()
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    # ------------------------------------------------------------------
    # Search (2.11–2.15)
    # ------------------------------------------------------------------

    def cmd_search_vector(self, args: List[str]) -> bool:
        """Vector search: search vector -s SPACE --index N --query "text" [--limit L]"""
        if not self._require_connected():
            return True
        space = _parse_flag(args, '-s') or _parse_flag(args, '--space') or self._require_space()
        if not space:
            return True
        index_name = _parse_flag(args, '--index')
        query_text = _parse_flag(args, '--query') or _parse_flag(args, '-q')
        limit_str = _parse_flag(args, '--limit') or '10'

        if not index_name or not query_text:
            print("Usage: search vector -s SPACE --index N --query \"text\" [--limit L]")
            return True
        try:
            limit = int(limit_str)
        except ValueError:
            limit = 10

        try:
            # Vectorize the query text
            from vitalgraph.vectorization.registry import get_provider
            row = self._run(self.conn.fetchrow(
                f"SELECT provider, provider_config, dimensions FROM {space}_vector_index "
                f"WHERE index_name = $1", index_name,
            ))
            if not row:
                print(f"❌ Index '{index_name}' not found.")
                return True

            provider = get_provider(
                str(row['provider']), row['provider_config'] or {},
                cache_key=f"{space}:{index_name}",
            )
            embedding = self._run(provider.vectorize_text(query_text))
            vec_literal = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"

            # Search
            vec_table = f"{space}_vec_{index_name}"
            results = self._run(self.conn.fetch(f"""
                SELECT subject_uuid,
                       1 - (embedding <=> $1::vector) AS score,
                       LEFT(search_text, 80) AS text_preview
                FROM {vec_table}
                ORDER BY embedding <=> $1::vector
                LIMIT $2
            """, vec_literal, limit))

            data = [{'subject_uuid': str(r['subject_uuid']), 'score': f"{r['score']:.4f}",
                     'text_preview': r['text_preview'] or ''} for r in results]
            _print_table(data, ['subject_uuid', 'score', 'text_preview'])
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_search_text(self, args: List[str]) -> bool:
        """Full-text search: search text -s SPACE --query "text" [--index N] [--limit L]"""
        if not self._require_connected():
            return True
        space = _parse_flag(args, '-s') or _parse_flag(args, '--space') or self._require_space()
        if not space:
            return True
        query_text = _parse_flag(args, '--query') or _parse_flag(args, '-q')
        index_name = _parse_flag(args, '--index')
        limit_str = _parse_flag(args, '--limit') or '20'

        if not query_text:
            print("Usage: search text -s SPACE --query \"text\" [--index N] [--limit L]")
            return True
        try:
            limit = int(limit_str)
        except ValueError:
            limit = 20

        try:
            # If index specified, search that vec table's tsvector column
            if index_name:
                vec_table = f"{space}_vec_{index_name}"
            else:
                # Pick first available index
                first = self._run(self.conn.fetchval(
                    f"SELECT index_name FROM {space}_vector_index ORDER BY index_name LIMIT 1"
                ))
                if not first:
                    print("❌ No vector indexes found in space.")
                    return True
                vec_table = f"{space}_vec_{first}"
                index_name = first

            tsquery = " & ".join(query_text.split())
            results = self._run(self.conn.fetch(f"""
                SELECT subject_uuid,
                       ts_rank(tsv, to_tsquery('english', $1)) AS rank,
                       LEFT(search_text, 80) AS text_preview
                FROM {vec_table}
                WHERE tsv @@ to_tsquery('english', $1)
                ORDER BY rank DESC
                LIMIT $2
            """, tsquery, limit))

            data = [{'subject_uuid': str(r['subject_uuid']), 'rank': f"{r['rank']:.4f}",
                     'text_preview': r['text_preview'] or ''} for r in results]
            _print_table(data, ['subject_uuid', 'rank', 'text_preview'])
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_search_fuzzy(self, args: List[str]) -> bool:
        """Fuzzy/trigram search: search fuzzy -s SPACE --query "text" [--threshold T] [--limit L]"""
        if not self._require_connected():
            return True
        space = _parse_flag(args, '-s') or _parse_flag(args, '--space') or self._require_space()
        if not space:
            return True
        query_text = _parse_flag(args, '--query') or _parse_flag(args, '-q')
        threshold_str = _parse_flag(args, '--threshold') or '0.3'
        limit_str = _parse_flag(args, '--limit') or '20'

        if not query_text:
            print("Usage: search fuzzy -s SPACE --query \"text\" [--threshold T] [--limit L]")
            return True
        try:
            threshold = float(threshold_str)
            limit = int(limit_str)
        except ValueError:
            threshold, limit = 0.3, 20

        try:
            # Use pg_trgm similarity on term_text
            term_table = f"{space}_term"
            results = self._run(self.conn.fetch(f"""
                SELECT term_text,
                       similarity(term_text, $1) AS sim,
                       term_uuid
                FROM {term_table}
                WHERE term_type = 'L'
                  AND similarity(term_text, $1) > $2
                ORDER BY sim DESC
                LIMIT $3
            """, query_text, threshold, limit))

            data = [{'term_uuid': str(r['term_uuid']), 'similarity': f"{r['sim']:.3f}",
                     'term_text': r['term_text'][:80]} for r in results]
            _print_table(data, ['term_uuid', 'similarity', 'term_text'])
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_search_geo(self, args: List[str]) -> bool:
        """Geo radius search: search geo -s SPACE --lat LAT --lon LON --radius-km R [--limit L]"""
        if not self._require_connected():
            return True
        space = _parse_flag(args, '-s') or _parse_flag(args, '--space') or self._require_space()
        if not space:
            return True
        lat_str = _parse_flag(args, '--lat')
        lon_str = _parse_flag(args, '--lon')
        radius_str = _parse_flag(args, '--radius-km') or _parse_flag(args, '--radius')
        limit_str = _parse_flag(args, '--limit') or '20'

        if not lat_str or not lon_str or not radius_str:
            print("Usage: search geo -s SPACE --lat LAT --lon LON --radius-km R [--limit L]")
            return True
        try:
            lat = float(lat_str)
            lon = float(lon_str)
            radius_m = float(radius_str) * 1000  # km → meters
            limit = int(limit_str)
        except ValueError:
            print("❌ Invalid numeric argument.")
            return True

        try:
            geo_table = f"{space}_geo"
            results = self._run(self.conn.fetch(f"""
                SELECT subject_uuid,
                       latitude, longitude,
                       ST_Distance(location, ST_MakePoint($2, $1)::geography) AS distance_m
                FROM {geo_table}
                WHERE ST_DWithin(location, ST_MakePoint($2, $1)::geography, $3)
                ORDER BY distance_m
                LIMIT $4
            """, lat, lon, radius_m, limit))

            data = [{'subject_uuid': str(r['subject_uuid']),
                     'lat': f"{r['latitude']:.5f}",
                     'lon': f"{r['longitude']:.5f}",
                     'distance_km': f"{r['distance_m']/1000:.2f}"} for r in results]
            _print_table(data, ['subject_uuid', 'lat', 'lon', 'distance_km'])
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    def cmd_search_combined(self, args: List[str]) -> bool:
        """Combined search: search combined -s SPACE --query "text" [--index N] [--lat --lon --radius-km] [--limit L]"""
        if not self._require_connected():
            return True
        space = _parse_flag(args, '-s') or _parse_flag(args, '--space') or self._require_space()
        if not space:
            return True
        query_text = _parse_flag(args, '--query') or _parse_flag(args, '-q')
        index_name = _parse_flag(args, '--index')
        lat_str = _parse_flag(args, '--lat')
        lon_str = _parse_flag(args, '--lon')
        radius_str = _parse_flag(args, '--radius-km') or _parse_flag(args, '--radius')
        limit_str = _parse_flag(args, '--limit') or '10'

        if not query_text:
            print("Usage: search combined -s SPACE --query \"text\" [--index N] [--lat L --lon L --radius-km R]")
            return True
        try:
            limit = int(limit_str)
        except ValueError:
            limit = 10

        has_geo = bool(lat_str and lon_str and radius_str)
        try:
            # Step 1: vector search to get candidate UUIDs with scores
            from vitalgraph.vectorization.registry import get_provider
            if not index_name:
                index_name = self._run(self.conn.fetchval(
                    f"SELECT index_name FROM {space}_vector_index ORDER BY index_name LIMIT 1"
                ))
            if not index_name:
                print("❌ No vector index found.")
                return True

            row = self._run(self.conn.fetchrow(
                f"SELECT provider, provider_config FROM {space}_vector_index WHERE index_name = $1",
                index_name,
            ))
            if not row:
                print(f"❌ Index '{index_name}' not found.")
                return True

            provider = get_provider(
                str(row['provider']), row['provider_config'] or {},
                cache_key=f"{space}:{index_name}",
            )
            embedding = self._run(provider.vectorize_text(query_text))
            vec_literal = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
            vec_table = f"{space}_vec_{index_name}"

            # Expand search pool for geo filtering
            pool_limit = limit * 5 if has_geo else limit
            vec_results = self._run(self.conn.fetch(f"""
                SELECT subject_uuid,
                       1 - (embedding <=> $1::vector) AS score,
                       LEFT(search_text, 60) AS text_preview
                FROM {vec_table}
                ORDER BY embedding <=> $1::vector
                LIMIT $2
            """, vec_literal, pool_limit))

            if not has_geo:
                data = [{'subject_uuid': str(r['subject_uuid']),
                         'score': f"{r['score']:.4f}",
                         'text_preview': r['text_preview'] or ''} for r in vec_results[:limit]]
                _print_table(data, ['subject_uuid', 'score', 'text_preview'])
                return True

            # Step 2: geo filter
            lat = float(lat_str)
            lon = float(lon_str)
            radius_m = float(radius_str) * 1000

            candidate_uuids = [r['subject_uuid'] for r in vec_results]
            if not candidate_uuids:
                print("(no vector results)")
                return True

            geo_table = f"{space}_geo"
            geo_results = self._run(self.conn.fetch(f"""
                SELECT subject_uuid,
                       ST_Distance(location, ST_MakePoint($2, $1)::geography) AS distance_m
                FROM {geo_table}
                WHERE subject_uuid = ANY($3)
                  AND ST_DWithin(location, ST_MakePoint($2, $1)::geography, $4)
            """, lat, lon, candidate_uuids, radius_m))

            geo_map = {r['subject_uuid']: r['distance_m'] for r in geo_results}

            # Merge: only keep subjects that pass geo filter
            combined = []
            for r in vec_results:
                if r['subject_uuid'] in geo_map:
                    combined.append({
                        'subject_uuid': str(r['subject_uuid']),
                        'vec_score': f"{r['score']:.4f}",
                        'distance_km': f"{geo_map[r['subject_uuid']]/1000:.2f}",
                        'text_preview': (r['text_preview'] or '')[:50],
                    })
            combined = combined[:limit]
            _print_table(combined, ['subject_uuid', 'vec_score', 'distance_km', 'text_preview'])
        except Exception as e:
            print(f"❌ Error: {e}")
        return True

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    def parse_command(self, line: str) -> tuple:
        """Parse command line into (command, args)."""
        parts = line.strip().split()
        if not parts:
            return '', []

        # Two-word commands
        if len(parts) >= 2 and parts[0].lower() in ('index', 'mapping', 'search'):
            return f"{parts[0].lower()} {parts[1].lower()}", parts[2:]
        return parts[0].lower(), parts[1:]

    def execute_command(self, command_line: str) -> bool:
        """Execute a REPL command. Returns False to exit."""
        if not command_line.strip():
            return True
        command, args = self.parse_command(command_line)

        dispatch = {
            'connect':          self.cmd_connect,
            'disconnect':       self.cmd_disconnect,
            'use':              self.cmd_use,
            'unuse':            self.cmd_unuse,
            # Index management
            'index list':       self.cmd_index_list,
            'index create':     self.cmd_index_create,
            'index delete':     self.cmd_index_delete,
            'index info':       self.cmd_index_info,
            # Mapping management
            'mapping list':     self.cmd_mapping_list,
            'mapping create':   self.cmd_mapping_create,
            'mapping delete':   self.cmd_mapping_delete,
            # Population
            'populate':         self.cmd_populate,
            'populate-geo':     self.cmd_populate_geo,
            'stats':            self.cmd_stats,
            # Search
            'search vector':    self.cmd_search_vector,
            'search text':      self.cmd_search_text,
            'search fuzzy':     self.cmd_search_fuzzy,
            'search geo':       self.cmd_search_geo,
            'search combined':  self.cmd_search_combined,
            # Meta
            'help':             self.cmd_help,
            '?':                self.cmd_help,
            'exit':             self.cmd_exit,
            'quit':             self.cmd_exit,
        }

        handler = dispatch.get(command)
        if handler:
            return handler(args)
        print(f"Unknown command: {command}")
        print("Type 'help' for available commands.")
        return True

    def cmd_help(self, args: List[str]) -> bool:
        """Show help."""
        space = self.current_space or '(none)'
        status = "🟢 Connected" if self.connected else "🔴 Disconnected"
        print(f"""
VitalGraph Search Utility  [{status}]  space={space}

Connection:
  connect                   Connect to DB via config
  disconnect                Close connection
  use <space>               Set current space
  unuse                     Clear space

Index Management:
  index list [-s SPACE]
  index create -s SPACE --name N --dims D [--provider P] [--model M]
  index delete -s SPACE --name N [--yes]
  index info -s SPACE --name N

Mapping Management:
  mapping list -s SPACE [--index N]
  mapping create -s SPACE --index N --type T [--source-type S]
  mapping delete -s SPACE --mapping-id M

Population:
  populate -s SPACE --index N [--graph-uri G] [--batch-size B]
  populate-geo -s SPACE [--graph-uri G]
  stats -s SPACE

Search:
  search vector -s SPACE --index N --query "text" [--limit L]
  search text -s SPACE --query "text" [--index N] [--limit L]
  search fuzzy -s SPACE --query "text" [--threshold T] [--limit L]
  search geo -s SPACE --lat LAT --lon LON --radius-km R [--limit L]
  search combined -s SPACE --query "text" [--index N] [--lat --lon --radius-km] [--limit L]

  help / ?    This message
  exit / quit Exit
""")
        return True

    def cmd_exit(self, args: List[str]) -> bool:
        """Exit."""
        if self.connected:
            self.cmd_disconnect([])
        if self.loop and not self.loop.is_closed():
            self.loop.close()
        print("Goodbye!")
        return False

    # ------------------------------------------------------------------
    # REPL loop
    # ------------------------------------------------------------------

    def _build_completer(self) -> WordCompleter:
        words = [
            'connect', 'disconnect', 'use', 'unuse',
            'index', 'mapping', 'search',
            'list', 'create', 'delete', 'info',
            'vector', 'text', 'fuzzy', 'geo', 'combined',
            'populate', 'populate-geo', 'stats',
            'help', 'exit', 'quit',
            '-s', '--space', '--name', '--dims', '--provider', '--model',
            '--index', '--type', '--source-type', '--mapping-id',
            '--graph-uri', '--graph', '--batch-size',
            '--query', '-q', '--limit', '--threshold',
            '--lat', '--lon', '--radius-km', '--yes',
            '--type-uri', '--metric', '--description',
        ]
        return WordCompleter(words, ignore_case=True)

    def run_repl(self):
        """Run the interactive REPL."""
        print("VitalGraph Search Utility")
        print("Type 'help' for commands, 'exit' to quit.")
        print()

        history_file = Path.home() / ".vitalgraphsearchutil_history"
        history = FileHistory(str(history_file))
        completer = self._build_completer()

        def _signal_handler(sig, frame):
            if self.connected:
                self.cmd_disconnect([])
            if self.loop and not self.loop.is_closed():
                self.loop.close()
            print("\nGoodbye!")
            sys.exit(0)

        signal.signal(signal.SIGINT, _signal_handler)

        try:
            while True:
                try:
                    indicator = "🟢" if self.connected else "🔴"
                    space_part = f":{self.current_space}" if self.current_space else ""
                    prompt_text = f"searchutil{space_part}{indicator}> "

                    command_line = prompt(
                        prompt_text,
                        history=history,
                        completer=completer,
                        complete_style=CompleteStyle.READLINE_LIKE,
                    )
                    if not self.execute_command(command_line):
                        break
                except EOFError:
                    print()
                    if self.connected:
                        self.cmd_disconnect([])
                    print("Goodbye!")
                    break
                except KeyboardInterrupt:
                    continue
        except Exception as e:
            print(f"REPL error: {e}")
            sys.exit(1)


# ---------------------------------------------------------------------------
# Argparse & main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VitalGraph Search Utility — vector, geo, and text search CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  vitalgraphsearchutil                           # Start REPL
  vitalgraphsearchutil -c "connect" -c "use myspace" -c "index list"
  vitalgraphsearchutil -c "connect" -c "use myspace" -c "search vector --index entity_default --query 'machine learning' --limit 5"
        """
    )
    parser.add_argument(
        "-c", "--command",
        type=str,
        action="append",
        help="Execute command non-interactively (repeatable)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="WARNING",
        help="Log level (DEBUG, INFO, WARNING, ERROR)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="VitalGraph Search Utility 1.0.0",
    )
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    try:
        repl_instance = VitalGraphSearchUtilREPL(log_level=args.log_level)

        if args.command:
            for cmd in args.command:
                result = repl_instance.execute_command(cmd)
                if not result:
                    break
            if repl_instance.connected:
                repl_instance.cmd_disconnect([])
            if repl_instance.loop and not repl_instance.loop.is_closed():
                repl_instance.loop.close()
        else:
            repl_instance.run_repl()
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
