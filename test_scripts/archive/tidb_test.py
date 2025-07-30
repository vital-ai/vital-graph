import os
import time
from pytidb import TiDBClient
from pytidb import Session
from pytidb.sql import select
from dotenv import load_dotenv
from pytidb.embeddings import EmbeddingFunction
from pytidb.schema import TableModel, Field, DistanceMetric
from sqlalchemy import text

load_dotenv()

db = TiDBClient.connect(
    host="127.0.0.1",
    port=4000,
    username="root",
    password="",
    database="vitalgraphdb",
)

text_embed = EmbeddingFunction("openai/text-embedding-3-small")

class Chunk(TableModel, table=True):
    __tablename__ = "chunks"
    __table_args__ = {"extend_existing": True}

    id: int = Field(primary_key=True)
    text: str = Field()

    text_vec: list[float] = text_embed.VectorField(
        source_field="text"
    )

    user_id: int = Field()

db.drop_table("chunks")

sql = """
CREATE TABLE chunks (
  id INT PRIMARY KEY AUTO_INCREMENT,
  text TEXT,
  text_vec VECTOR(1536),
  VECTOR INDEX idx_text_vec((VEC_COSINE_DISTANCE(text_vec))) USING HNSW,
  user_id INT
);
"""

with db.db_engine.connect() as conn:
    conn.execute(text(sql))

# TODO no way to config params HNSW, opened an issue
# params are efConstruction, etc.

table = db.create_table(schema=Chunk)

table.truncate()

table.insert(
    Chunk(text="The quick brown fox jumps over the lazy dog", user_id=1),
)

table.bulk_insert(
    [
        Chunk(text="A quick brown dog runs in the park", user_id=2),
        Chunk(text="The lazy fox sleeps under the tree", user_id=2),
        Chunk(text="A dog and a fox play in the park", user_id=3),
    ]
)

# table.rows()

vq = text_embed.get_query_embedding("A quick fox in the park")

print(vq)

sql_q = f"""
EXPLAIN SELECT * 
from chunks 
order by VEC_COSINE_DISTANCE(text_vec, '{vq}')
LIMIT 10
"""

print(sql_q)

with db.db_engine.connect() as conn:
    result = conn.execute(text(sql_q))
    print(result.fetchall())


start_time = time.time()

res = table.search(
    vq
    ).filter({"user_id": 2}).limit(2).distance_metric(DistanceMetric.COSINE).to_list()

end_time = time.time()

elapsed_ms = (end_time - start_time) * 1000

print(res)

print(f"Elapsed time: {elapsed_ms:.2f} ms")

# db.drop_table("chunks")
