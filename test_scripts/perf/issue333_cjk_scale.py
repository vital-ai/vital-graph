#!/usr/bin/env python3
"""Cost of the `cjk` FTS pseudo-language at production message-index scale.

`issues/333` Tests §4. There is no production Chinese corpus, so this builds a
SYNTHETIC zh-Hant one, deterministically seeded: messages of 6-30 words drawn
Zipf-weighted from a vocabulary of common Traditional words, with full-width
punctuation between clauses and the odd Latin token. Real text has a different
pair distribution, so read the numbers as an order of magnitude, not a
forecast; the recall questions are composed from the same vocabulary.

Everything is in TEMP tables on one session: nothing persists, no space is
touched. Measures, per language list (`['english']` vs `['english', 'cjk']`):

  * the batched tsv refresh (5,000 rows per statement, as `refresh_fts_tsv`)
  * GIN build time and size
  * per-row trigger cost on INSERT
  * per question: match count, and ranked top-25 latency (min/med/max of 5)

    python test_scripts/perf/issue333_cjk_scale.py [--rows 320000]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from devtools.target import add_pg_arguments, describe_target  # noqa: E402
from vitalgraph.db.sparql_sql.fts_languages import (  # noqa: E402
    tsquery_expr, tsvector_expr,
)

ONE = "我 你 他 她 的 了 在 是 有 也 很 就 都 嗎 呢 吧 和 去 來 說 看 想 要 會 能 好 夢 海 貓 狗 家 錢 書 車 雨 風 花 茶".split()
TWO = """今天 明天 昨天 晚上 早上 時候 朋友 家人 媽媽 爸爸 工作 公司 學校 老師
學生 電話 手機 時間 地方 東西 問題 事情 喜歡 知道 覺得 記得 夢到 樓梯 海邊 房間
廚房 咖啡 晚餐 午餐 早餐 電影 音樂 旅行 飛機 火車 醫院 醫生 生日 禮物 天氣 下雨
開心 難過 擔心 害怕 休息 睡覺 起床 回家 出門 上班 下班 週末 假期 照片 故事 小說
書店 公園 貓咪 花園 城市 台北 高雄 日本 美國 中文 英文 考試 功課 會議 計畫 想法
感覺 心情 身體 運動 跑步 游泳 唱歌 跳舞 購物 衣服 鞋子 顏色 紅色 藍色 那個 這個
什麼 怎麼 一起 已經 還是 可是 因為 所以 如果 雖然 但是 然後 其實 真的 一直 有時
每天 常常 終於 突然 剛才 以前 以後 最近 夢想 樓上 樓下 海浪 沙灘 太陽 月亮 星星
名字 生病 感冒 發燒 吃藥 餐廳 夜市 捷運 公車 機場 行李 護照 銀行 薪水 老闆 同事
客戶 專案 報告 郵件 訊息 回覆 討論 決定 選擇 改變 開始 結束 準備 練習 學習 研究
""".split()
LATIN = ["OK", "lol", "Starbucks", "LINE", "iPhone", "email"]
PUNCT = "，。！？、"

QUESTIONS = [
    "記得我夢到樓梯那個夢嗎",
    "我上次說的海邊旅行",
    "媽媽生日禮物是什麼",
    "我跟朋友去台北的時候",
    "那部電影叫什麼名字",
    "我最近心情不好",
    "公司會議的計畫",
    "我的貓咪生病了",
    '"夢到樓梯"',
    "夢",
]


def corpus(n: int, seed: int = 333):
    rng = random.Random(seed)
    vocab = TWO + ONE
    weights = [1.0 / (i + 1) ** 0.9 for i in range(len(vocab))]
    rng.shuffle(vocab)
    for _ in range(n):
        words = rng.choices(vocab, weights, k=rng.randint(6, 30))
        out = []
        for w in words:
            out.append(w)
            r = rng.random()
            if r < 0.12:
                out.append(rng.choice(PUNCT))
            elif r < 0.14:
                out.append(f" {rng.choice(LATIN)} ")
        yield "".join(out)


def mmm(xs):
    return f"{min(xs):8.1f} {statistics.median(xs):8.1f} {max(xs):8.1f}"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=int, default=320_000)
    ap.add_argument("--batch", type=int, default=5000)
    add_pg_arguments(ap)
    a = ap.parse_args()
    print(f"target: {describe_target(a)}   rows={a.rows:,}", flush=True)

    import asyncpg
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                 user=a.user, password=a.password or None)
    try:
        await conn.execute("SET statement_timeout = 0")
        await conn.execute("CREATE TEMP TABLE src (id int PRIMARY KEY, search_text text)")
        t0 = time.monotonic()
        await conn.copy_records_to_table(
            "src", records=((i, t) for i, t in enumerate(corpus(a.rows))))
        print(f"corpus loaded in {time.monotonic() - t0:.1f}s; "
              f"avg {await conn.fetchval('SELECT avg(length(search_text))::int FROM src')} chars")

        for langs in (["english"], ["english", "cjk"]):
            tag = "+".join(langs)
            tbl = "fts_" + "_".join(langs)
            await conn.execute(f"CREATE TEMP TABLE {tbl} AS SELECT id, search_text, "
                               f"NULL::tsvector AS tsv FROM src")
            await conn.execute(f"ALTER TABLE {tbl} ADD PRIMARY KEY (id)")
            expr = tsvector_expr(langs, "COALESCE(t.search_text, '')")
            per_batch, last = [], -1
            t0 = time.monotonic()
            while True:
                b0 = time.monotonic()
                n = await conn.fetchval(
                    f"WITH b AS (SELECT id FROM {tbl} WHERE id > $1 ORDER BY id LIMIT {a.batch}), "
                    f"u AS (UPDATE {tbl} t SET tsv = {expr} FROM b WHERE t.id = b.id RETURNING t.id) "
                    f"SELECT max(id) FROM u", last)
                if n is None:
                    break
                per_batch.append((time.monotonic() - b0) * 1000)
                last = n
            refresh = time.monotonic() - t0
            t0 = time.monotonic()
            await conn.execute(f"CREATE INDEX ON {tbl} USING gin (tsv)")
            gin_s = time.monotonic() - t0
            await conn.execute(f"ANALYZE {tbl}")
            gin_mb = await conn.fetchval(
                "SELECT sum(pg_relation_size(indexrelid)) / 1048576.0 FROM pg_index "
                "WHERE indrelid = $1::regclass AND NOT indisprimary", tbl)
            lex = await conn.fetchval(f"SELECT avg(length(tsv))::numeric(6,1) FROM {tbl}")
            print(f"\n== {tag}")
            print(f"   refresh  {refresh:7.1f}s total, {len(per_batch)} batches, "
                  f"batch ms min/med/max {mmm(per_batch)}")
            print(f"   GIN      {gin_s:7.1f}s build, {gin_mb:8.1f} MB, {lex} lexemes/row")

            # Trigger cost: 10,000 inserts through a BEFORE INSERT trigger, 5x.
            await conn.execute(
                f"CREATE TEMP TABLE trig_{tbl} (id int, search_text text, tsv tsvector)")
            trig_expr = tsvector_expr(langs, "COALESCE(NEW.search_text, '')")
            await conn.execute(
                f"CREATE FUNCTION pg_temp.trg_{tbl}() RETURNS trigger AS $$ BEGIN "
                f"NEW.tsv := {trig_expr}; RETURN NEW; END $$ LANGUAGE plpgsql")
            await conn.execute(
                f"CREATE TRIGGER t BEFORE INSERT ON trig_{tbl} FOR EACH ROW "
                f"EXECUTE FUNCTION pg_temp.trg_{tbl}()")
            runs = []
            for _ in range(5):
                await conn.execute(f"TRUNCATE trig_{tbl}")
                t0 = time.monotonic()
                await conn.execute(f"INSERT INTO trig_{tbl} (id, search_text) "
                                   f"SELECT id, search_text FROM src WHERE id < 10000")
                runs.append((time.monotonic() - t0) * 1000 / 10000 * 1000)
            print(f"   trigger  µs/row min/med/max {mmm(runs)}")

            print(f"   {'question':<26} {'matches':>8}   top-25 ms min      med      max")
            for q in QUESTIONS:
                tsq = tsquery_expr(langs, "$1")
                n = await conn.fetchval(f"SELECT count(*) FROM {tbl} WHERE tsv @@ {tsq}", q)
                lat = []
                for _ in range(5):
                    t0 = time.monotonic()
                    await conn.fetch(f"SELECT id FROM {tbl} WHERE tsv @@ {tsq} "
                                     f"ORDER BY ts_rank_cd(tsv, {tsq}, 1) DESC, id LIMIT 25", q)
                    lat.append((time.monotonic() - t0) * 1000)
                print(f"   {q:<26} {n:>8,}   {mmm(lat)}")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
