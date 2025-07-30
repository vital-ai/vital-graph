import os
import time
import asyncio
import json

from dotenv import load_dotenv

from openai import AsyncOpenAI

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, Integer, Text, text as sql_text, select
from pgvector.sqlalchemy import Vector

# ─── Configuration ────────────────────────────────────────────────────────────
load_dotenv()

PG_HOST     = "127.0.0.1"
PG_PORT     = 5432
PG_USER     = "postgres"
PG_PASSWORD = ""
PG_DATABASE = "vitalgraphdb"

ASYNC_DB_URL = (
    f"postgresql+asyncpg://"
    f"{PG_USER}:{PG_PASSWORD}@"
    f"{PG_HOST}:{PG_PORT}/"
    f"{PG_DATABASE}"
)

openai_key = os.getenv("OPENAI_API_KEY")
EMBED_MODEL   = "text-embedding-3-small"

openai_client = AsyncOpenAI(api_key=openai_key)


# VitalGraphSQLStore base & async engine/session
Base = declarative_base()
engine = create_async_engine(ASYNC_DB_URL, echo=True)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession
)

# ─── ORM Model ────────────────────────────────────────────────────────────────
class Chunk(Base):
    __tablename__ = "chunks"
    id       = Column(Integer, primary_key=True)
    text     = Column(Text, nullable=False)
    text_vec = Column(Vector(1536), nullable=False)
    user_id  = Column(Integer, nullable=False)

# ─── Embedding Helper ─────────────────────────────────────────────────────────
async def get_embedding(text: str) -> list[float]:
    """Fetch a 1536-dim embedding using the new OpenAI v1 client."""
    resp = await openai_client.embeddings.create(model=EMBED_MODEL, input=text)
    return resp.data[0].embedding

# ─── Schema Initialization ────────────────────────────────────────────────────
async def init_schema():
    async with engine.begin() as conn:
        # Enable pgvector extension
        await conn.execute(sql_text("CREATE EXTENSION IF NOT EXISTS vector;"))
        # Drop & recreate table
        await conn.execute(sql_text("DROP TABLE IF EXISTS chunks;"))
        await conn.execute(sql_text("""
            CREATE TABLE chunks (
                id SERIAL PRIMARY KEY,
                text TEXT NOT NULL,
                text_vec VECTOR(1536) NOT NULL,
                user_id INT NOT NULL
            );
        """))
        # Create HNSW index on vector column
        await conn.execute(sql_text("""
            CREATE INDEX idx_text_vec
              ON chunks
              USING hnsw (text_vec vector_cosine_ops)
              WITH (m = 16, ef_construction = 64);
        """))

# ─── Data Insertion ───────────────────────────────────────────────────────────
async def insert_data():
    async with AsyncSessionLocal() as session:
        # Single insert
        txt = "The quick brown fox jumps over the lazy dog"
        vec = await get_embedding(txt)
        session.add(Chunk(text=txt, text_vec=vec, user_id=1))

        # Bulk insert
        entries = [
            ("A quick brown dog runs in the park", 2),
            ("The lazy fox sleeps under the tree",   2),
            ("A dog and a fox play in the park",     3),
        ]
        objects = []
        for t, uid in entries:
            v = await get_embedding(t)
            objects.append(Chunk(text=t, text_vec=v, user_id=uid))
        session.add_all(objects)

        await session.commit()

# ─── Queries ──────────────────────────────────────────────────────────────────
async def run_queries():
    q = "A quick fox in the park"
    qvec = await get_embedding(q)
    print("Query embedding (first 5 dims):", qvec[:5], "...")

    # 1. Raw SQL EXPLAIN with CAST to vector
    qvec_str = json.dumps(qvec)
    explain_sql = """
        EXPLAIN SELECT *
        FROM chunks
        ORDER BY text_vec <=> CAST(:vec AS vector)
        LIMIT 10;
    """
    async with engine.connect() as conn:
        plan = await conn.execute(
            sql_text(explain_sql),
            {"vec": qvec_str}
        )
        for row in plan:
            print(row[0])

    # 2. ORM-based search + filter + limit
    start = time.time()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(
                Chunk,
                Chunk.text_vec.cosine_distance(qvec).label("score")

            )
            .filter(Chunk.user_id == 2)
            .order_by("score")
            .limit(2)
        )
        hits = result.all()
    elapsed = (time.time() - start) * 1000


    # print("Search results:", hits)
    print(f"Elapsed time: {elapsed:.2f} ms")
    print(f"{'ID':<3}  {'Score':>6}  {'User':<4}  Text")
    print("-" * 60)
    for chunk, score in hits:
        print(f"{chunk.id:<3}  {score:6.4f}      {chunk.user_id:<4}  {chunk.text!r}")

# ─── Main Entrypoint ───────────────────────────────────────────────────────────
async def main():
    await init_schema()
    await insert_data()
    await run_queries()
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())