#!/usr/bin/env python3
"""issues/248 at production scale: a synthetic registry, and recall measured on it.

No local registry is anywhere near production's (1.27M fuzzy keys; dev has 2,317
entities, the test stack 330), and 248's defect is scale-dependent by nature: geo
compresses similarity toward 1 and the adaptive level-walk is crowded out by
same-city rivals. So this builds a registry the size and shape of production in
its OWN database inside the test-stack container and measures there.

    create     CREATE DATABASE registry_scale_248 + the registry schema
    generate   COPY ~1.2M synthetic entities and aliases, plus the planted cases
    rebuild    the real full fuzzy rebuild (EntityFuzzyIndexPG.initialize)
    measure    run every planted case through find_similar_by_name

The shape, matched to what production was measured to hold:
  * 640,000 business entities, 210,000 of them `company-<digits>` placeholders
    (249 measured 209,580 of 643,791); 400,000 persons; 120,000 aliases.
  * US geo, states weighted by population, cities Zipf-weighted within a state,
    so the top cities are CROWDED — the condition 248's compression needs.
  * business names from templates over a shared industry vocabulary, so many
    same-city businesses share most of their shingles ("... Landscaping LLC").

Planted cases (table `syn_case`), each with a target it must find:
  dup_*      identical-name pairs; member 2's geo agrees / lacks locality /
             is another city / another state. 248: "8/8 must not regress".
  typo_*     one-edit variants of a unique business name in a crowded city,
             queried with geo AGREEING, ABSENT and DISAGREEING. 248's defect.
  lit_*      248's literal cases: Aur Trdaing Corp (must find), Dice Durid
             (near-threshold), Carbal (expected to stay missed).

Run `measure` from another checkout to get a before/after:
    VG_ROOT=/path/to/old/worktree python scale_registry_248.py rebuild
    VG_ROOT=/path/to/old/worktree python scale_registry_248.py measure --tag before
"""
import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("VG_ROOT") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402

DB = "registry_scale_248"
CONN = dict(host="localhost", port=5433, user="postgres", password="testpass")
SEED = 248

SURNAMES = """Smith Johnson Williams Brown Jones Garcia Miller Davis Rodriguez Martinez
Hernandez Lopez Gonzalez Wilson Anderson Thomas Taylor Moore Jackson Martin Lee Perez
Thompson White Harris Sanchez Clark Ramirez Lewis Robinson Walker Young Allen King Wright
Scott Torres Nguyen Hill Flores Green Adams Nelson Baker Hall Rivera Campbell Mitchell
Carter Roberts Gomez Phillips Evans Turner Diaz Parker Cruz Edwards Collins Reyes Stewart
Morris Morales Murphy Cook Rogers Gutierrez Ortiz Morgan Cooper Peterson Bailey Reed Kelly
Howard Ramos Kim Cox Ward Richardson Watson Brooks Chavez Wood James Bennett Gray Mendoza
Ruiz Hughes Price Alvarez Castillo Sanders Patel Myers Long Ross Foster Jimenez Powell
Jenkins Perry Russell Sullivan Bell Coleman Butler Henderson Barnes Gonzales Fisher
Vasquez Simmons Romero Jordan Patterson Alexander Hamilton Graham Reynolds Griffin Wallace
Moreno West Cole Hayes Bryant Herrera Gibson Ellis Tran Medina Aguilar Stevens Murray Ford
Castro Marshall Owens Harrison Fernandez McDonald Woods Washington Kennedy Wells Vargas
Henry Chen Freeman Webb Tucker Guzman Burns Crawford Olson Simpson Porter Hunter Gordon
Mendez Silva Shaw Snyder Mason Dixon Munoz Hunt Hicks Holmes Palmer Wagner Black Robertson
Boyd Rose Stone Salazar Fox Warren Mills Meyer Rice Schmidt Garza Daniels Ferguson Nichols
Stephens Soto Weaver Ryan Gardner Payne Grant Dunn Kelley Spencer Hawkins Arnold Pierce
Vazquez Hansen Peters Santos Hart Bradley Knight Elliott Cunningham Duncan Armstrong
Hudson Carroll Lane Riley Andrews Alvarado Ray Delgado Berry Perkins Hoffman Johnston
Matthews Pena Richards Contreras Willis Carpenter Lawrence Sandoval Guerrero George
Chapman Rios Estrada Ortega Watkins Greene Nunez Wheeler Valdez Harper Burke Larson
Santiago Maldonado Morrison Franklin Carlson Austin Dominguez Carr Lawson Jacobs Obrien
Lynch Singh Vega Bishop Montgomery Oliver Jensen Harvey Williamson Gilbert Dean Sims
Espinoza Howell Li Wong Reid Hanson Le McCoy Garrett Burton Fuller Wang Weber Welch Rojas
Lucas Marquez Fields Park Yang Little Banks Padilla Day Walsh Bowman Schultz Luna Fowler
Mejia Davidson Acosta Brewer May Holland Juarez Newman Pearson Curtis Cortez Douglas
Schneider Joseph Barrett Navarro Figueroa Keller Avila Wade Molina Stanley Hopkins
Campos Barnett Bates Chambers Caldwell Beck Lambert Miranda Byrd Craig Ayala Lowe Frazier
Powers Neal Leonard Gregory Carrillo Sutton Fleming Rhodes Shelton Schwartz Norris
Jennings Watts Duran Walters Cohen McDaniel Moran Parks Steele Vaughn Becker Holt
DeLeon Barker Terry Hale Leon Hail Benson Haynes Horton Miles Lyons Pham Graves Bush
Thornton Wolfe Warner Cabrera McKinney Mann Zimmerman Dawson Lara Fletcher Page McCarthy
Love Robles Cervantes Solis Erickson Reeves Chang Klein Salinas Fuentes Baldwin Daniel
Simon Velasquez Hardy Higgins Aguirre Lin Cummings Chandler Sharp Barber Bowen Ochoa
Dennis Robbins Liu Ramsey Francis Griffith Paul Blair Oconnor Cardenas Pacheco Cross
Calderon Quinn Moss Swanson Chan Rivas Khan Rodgers Serrano Fitzgerald Rosales Stevenson
Christensen Manning Gill Curry McLaughlin Harmon McGee Gross Doyle Garner Newton Burgess
Reese Walton Blake Trujillo Adkins Brady Goodman Roman Webster Goodwin Fischer Huang
Potter Delacruz Montoya Todd Wu Hines Mullins Castaneda Malone Cannon Tate Mack Sherman
Hubbard Hodges Zhang Guerra Wolf Valencia Saunders Franco Rowe Gallagher Farmer Hammond
Hampton Townsend Ingram Wise Gallegos Clarke Barton Schroeder Maxwell Waters Logan
Camacho Strickland Norman Person Colon Parsons Frank Harrington Glover Osborne Buchanan
Casey Floyd Patton Ibarra Ball Tyler Suarez Bowers Orozco Salas Cobb Gibbs Andrade
Bauer Conner Moody Escobar McGuire Lloyd Mueller Hartman French Kramer McBride Pope
Lindsey Velazquez Norton McCormick Sparks Flynn Yates Hogan Marsh Macias Villanueva
Zamora Pratt Stokes Owen Ballard Lang Brock Villarreal Charles Drake Barrera Cain
Patrick Pineda Burnett Mercado Santana Shepherd Bautista Ali Shaffer Lamb Trevino McKenzie
Hess Beil Olsen Cochran Morton Nash Wilkins Petersen Briggs Shah Roth Nicholson Holloway
Lozano Rangel Flowers Hoover Short Arias Mora Valenzuela Bryan Meyers Weiss Underwood
Bass Greer Summers Houston Carson Morrow Clayton Whitaker Decker Yoder Collier Zuniga
Carey Wilcox Melendez Poole Roberson Larsen Conley Davenport Copeland Massey Lam Huff
Rocha Cameron Jefferson Hood Monroe Anthony Pittman Huynh Randall Singleton Kirk Combs
Mathis Christian Skinner Bradford Richard Galvan Wall Boone Kirby Wilkinson Bridges Bruce
Atkinson Velez Meza Roy Vincent York Hodge Villa Abbott Allison Tapia Gates Chase Sosa
Sweeney Farrell Wyatt Dalton Horn Barron Phelps Yu Dickerson Heath Foley Atkins Mathews
Bonilla Acevedo Benitez Zavala Hensley Glenn Cisneros Harrell Shields Rubio Huffman
Choi Boyer Garrison Arroyo Bond Kane Hancock Callahan Dillon Cline Wiggins Grimes
Arellano Melton Oneill Savage Ho Beltran Pitts Parrish Ponce Rich Booth Koch Golden
Ware Brennan McDowell Marks Cantu Humphrey Baxter Sawyer Clay Tanner Hutchinson Kaur
Berg Wiley Gilmore Russo Villegas Hobbs Keith Wilkerson Ahmed Beard McClain Montes Mata
Rosario Vang Walter Henson Oneal Mosley McClure Beasley Stephenson Snow Huerta Preston
Vance Barry Johns Eaton Blackwell Dyer Prince Macdonald Solomon Guevara Stafford English
Hurst Woodard Cortes Shannon Kemp Nolan McCullough Merritt Murillo Moon Salgado Strong
Kline Cordova Barajas Roach Rosas Winters Jacobson Lester Knox Bullock Kerr Leach Meadows
Davila Orr Whitehead Pruitt Kent Conway McKee Barr David Dejesus Marin Berger McIntyre
Blankenship Gaines Palacios Cuevas Bartlett Durham Dorsey McCall Odonnell Stein Browning
Stout Lowery Sloan McLean Hendricks Calhoun Sexton Chung Gentry Hull Duarte Ellison Nielsen
Gillespie Buck Middleton Sellers Leblanc Esparza Hardin Bradshaw McIntosh Howe Livingston
Frost Glass Morse Knapp Herman Stark Bravo Noble Spears Weeks Corona Frederick Buckley
McFarland Hebert Enriquez Hickman Quintero Randolph Schaefer Walls Trejo House Reilly
Pennington Michael Conrad Giles Benjamin Crosby Fitzpatrick Donovan Mays Mahoney Valentine
Raymond Medrano Hahn McMillan Small Bentley Felix Peck Lucero Boyle Hanna Pace Rush Hurley
Harding McConnell Bernal Nava Ayers Everett Ventura Avery Pugh Mayer Bender Shepard
McMahon Landry Case Sampson Moses Magana Blackburn Dunlap Gould Duffy Vaughan Herring
McKay Espinosa Rivers Farley Bernard Ashley Friedman Potts Truong Costa Correa Blevins
Nixon Clements Fry Delarosa Best Benton Lugo Portillo Dougherty Crane Haley Phan Villalobos
Blanchard Horne Finley Quintana Lynn Esquivel Bean Dodson Mullen Xiong Hayden Cano Levy
Huber Richmond Moyer Lim Frye Sheppard McCarty Avalos Booker Waller Parra Woodward Jaramillo
Krueger Rasmussen Brandt Peralta Donaldson Stuart Faulkner Maynard Galindo Coffey Estes
Sanford Burch Maddox Vo Oconnell Vu Andersen Spence McPherson Church Schmitt Stanton Leal
Cherry Compton Dudley Sierra Pollard Alfaro Hester Proctor Lu Hinton Novak Good Madden
McCann Terrell Jarvis Dickson Reyna Cantrell Mayo Branch Hendrix Rollins Rowland Whitney
Duke Odom Daugherty Travis Tang Archer""".split()

INDUSTRY = """Landscaping Plumbing Roofing Electric Construction Auto Repair Detailing Dental
Cafe Bakery Pizza Grill Restaurant Catering Cleaning Janitorial Painting Flooring Remodeling
HVAC Heating Cooling Pest Control Pool Services Lawn Care Tree Service Moving Storage
Trucking Logistics Transport Towing Insurance Realty Properties Holdings Investments Capital
Consulting Marketing Media Design Studio Photography Printing Signs Fitness Yoga Salon Spa
Barbershop Nails Boutique Apparel Jewelry Florist Pharmacy Clinic Medical Chiropractic
Therapy Veterinary Pet Grooming Daycare Academy Tutoring Law Accounting Tax Payroll Staffing
Security Locksmith Glass Fence Concrete Paving Excavation Welding Machine Tools Supply
Hardware Lumber Electronics Computers Software Technologies Solutions Systems Networks
Telecom Wireless Solar Energy Fuel Oil Gas Farms Nursery Produce Market Grocery Liquors
Smoke Vape Tattoo Music Entertainment Events Travel Tours Motors Cars Tires Collision
Body Shop Car Wash Laundry Dry Cleaning Tailoring Upholstery Furniture Appliance Mattress
Cabinets Countertops Kitchen Bath Windows Doors Gutters Siding Masonry Drywall Insulation
Waterproofing Restoration Handyman Maintenance Rentals Leasing Funding Lending Mortgage""".split()
SUFFIXES = ["LLC", "LLC", "LLC", "Inc", "Inc.", "Corp", "Co", "Group", "Company",
            "Services", "Enterprises", "& Sons", "LLC", "Inc"]

STATES = [("CA", 39), ("TX", 30), ("FL", 22), ("NY", 20), ("PA", 13), ("IL", 13), ("OH", 12),
          ("GA", 11), ("NC", 11), ("MI", 10), ("NJ", 9), ("VA", 9), ("WA", 8), ("AZ", 7),
          ("TN", 7), ("MA", 7), ("IN", 7), ("MO", 6), ("MD", 6), ("WI", 6), ("CO", 6),
          ("MN", 6), ("SC", 5), ("AL", 5), ("LA", 5), ("KY", 5), ("OR", 4), ("OK", 4),
          ("CT", 4), ("UT", 3), ("IA", 3), ("NV", 3), ("AR", 3), ("MS", 3), ("KS", 3),
          ("NM", 2), ("NE", 2), ("ID", 2), ("WV", 2), ("HI", 1), ("NH", 1), ("ME", 1),
          ("MT", 1), ("RI", 1), ("DE", 1), ("SD", 1), ("ND", 1), ("AK", 1), ("VT", 1), ("WY", 1)]


def _words(rng):
    raw = [w.strip() for w in open("/usr/share/dict/words")]
    good = [w.capitalize() for w in raw if w.isalpha() and w.islower() and 4 <= len(w) <= 9]
    rng.shuffle(good)
    return good[:6000]


def _firsts():
    return [w.strip() for w in open("/usr/share/dict/propernames") if w.strip().isalpha()]


class Gen:
    def __init__(self):
        self.rng = random.Random(SEED)
        self.brands = _words(self.rng)
        self.firsts = _firsts()
        # Cities: 40 per state, named from brand words so they are unique strings;
        # Zipf weights so a handful per state hold most of its entities.
        self.cities = {s: [self.brands[(i * 40 + j) % len(self.brands)] + " City"
                           for j in range(40)] for i, (s, _) in enumerate(STATES)}
        self.city_w = [1.0 / (j + 1) for j in range(40)]
        self.state_keys = [s for s, _ in STATES]
        self.state_w = [w for _, w in STATES]
        self.crowded = ("FL", self.cities["FL"][0])   # the single most crowded city

    def geo(self):
        r = self.rng
        st = r.choices(self.state_keys, self.state_w)[0]
        city = r.choices(self.cities[st], self.city_w)[0]
        if r.random() < 0.15:                          # patchy metadata is normal
            city = None
        return "US", st, city

    def business(self, city_hint=None):
        r, t = self.rng, self.rng.random()
        ind = r.choice(INDUSTRY)
        suf = r.choice(SUFFIXES)
        if t < 0.30:
            return f"{r.choice(SURNAMES)} {ind} {suf}"
        if t < 0.55:
            return f"{r.choice(self.brands)} {ind} {suf}"
        if t < 0.65:
            return f"{r.choice(self.brands)} {ind}"
        if t < 0.73:
            return f"{r.choice(self.firsts)}'s {ind}"
        if t < 0.78:
            return f"{r.choice(SURNAMES)} & {r.choice(SURNAMES)} {suf}"
        if t < 0.88:
            return f"{r.choice(self.brands)} {r.choice(self.brands)} {ind} {suf}"
        if t < 0.95:
            return f"{(city_hint or r.choice(self.brands)).replace(' City', '')} {ind} {suf}"
        ini = "".join(r.choice("ABCDEFGHJKLMNPRSTW") for _ in range(r.choice([2, 3])))
        return f"{ini} {ind} {suf}"

    def person(self):
        r = self.rng
        if r.random() < 0.3:
            return f"{r.choice(self.firsts)} {r.choice('ABCDEFGHJKLMNPRSTW')}. {r.choice(SURNAMES)}"
        return f"{r.choice(self.firsts)} {r.choice(SURNAMES)}"


def typo(rng, name, kind):
    """One edit inside the longest token, away from its edges."""
    toks = name.split(" ")
    i = max(range(len(toks)), key=lambda k: len(toks[k]))
    w = toks[i]
    p = rng.randrange(1, len(w) - 2)
    if kind == "sub":
        c = rng.choice([ch for ch in "aeioulnrst" if ch != w[p].lower()])
        w = w[:p] + c + w[p + 1:]
    elif kind == "omit":
        w = w[:p] + w[p + 1:]
    elif kind == "insert":
        w = w[:p] + rng.choice("aeiourst") + w[p:]
    elif kind == "transpose":
        w = w[:p] + w[p + 1] + w[p] + w[p + 2:]
    toks[i] = w
    return " ".join(toks)


async def connect(db=DB):
    return await asyncpg.connect(database=db, **CONN)


async def pool(db=DB):
    return await asyncpg.create_pool(database=db, min_size=2, max_size=8, **CONN)


async def cmd_create(_):
    from vitalgraph.entity_registry.entity_registry_schema import EntityRegistrySchema
    c = await connect("postgres")
    if await c.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", DB):
        print(f"{DB} exists — refusing to recreate; drop it deliberately first")
        return
    await c.execute(f"CREATE DATABASE {DB}")
    await c.close()
    s = EntityRegistrySchema()
    c = await connect()
    for sql in s.create_tables_sql() + s.migrations_sql() + s.create_indexes_sql():
        await c.execute(sql)
    await c.execute(s.seed_entity_types_sql())
    await c.execute("INSERT INTO alias_type (type_key, type_label) VALUES ('aka','AKA') "
                    "ON CONFLICT DO NOTHING")
    print(f"created {DB}")
    await c.close()


ENT_COLS = ["entity_id", "entity_type_id", "primary_name", "country", "region", "locality",
            "status", "is_placeholder_name"]


async def cmd_generate(a):
    g = Gen()
    r = g.rng
    c = await connect()
    if await c.fetchval("SELECT count(*) FROM entity"):
        print("entity table is not empty — generate runs once")
        return
    ents, aliases, cases = [], [], []
    n = 0

    def ent(etype, name, geo, ph=False):
        nonlocal n
        n += 1
        eid = f"syn_{n:08d}"
        ents.append((eid, etype, name, geo[0], geo[1], geo[2], "active", ph))
        return eid

    t0 = time.time()
    for _ in range(a.business - a.placeholders):
        geo = g.geo()
        ent(2, g.business(geo[2]), geo)
    for i in range(a.placeholders):
        ent(2, f"company-{1000000 + i}", g.geo(), True)
    for _ in range(a.persons):
        ent(1, g.person(), g.geo())
    biz_ids = [e[0] for e in ents if e[1] == 2 and not e[7]]
    for eid in r.sample(biz_ids, a.aliases):
        aliases.append((eid, g.business(), "aka", "active"))

    # -- planted: names that cannot occur by chance (two brands + a surname)
    used = {e[2].lower() for e in ents}

    def unique_name():
        while True:
            nm = f"{r.choice(g.brands)} {r.choice(SURNAMES)} {r.choice(INDUSTRY)} {r.choice(SUFFIXES)}"
            if nm.lower() not in used:
                used.add(nm.lower())
                return nm

    cst, ccity = g.crowded
    other_city = g.cities["FL"][1]
    for k in range(a.cases):
        nm = unique_name()
        e1 = ent(2, nm, ("US", cst, ccity))
        variant = ["agree", "no_locality", "other_city", "other_state"][k % 4]
        geo2 = {"agree": ("US", cst, ccity), "no_locality": ("US", cst, None),
                "other_city": ("US", cst, other_city), "other_state": ("US", "WA", g.cities["WA"][0])}[variant]
        e2 = ent(2, nm, geo2)
        cases.append((f"dup_{variant}", nm, "US", cst, ccity, [e1, e2]))
    for k in range(a.cases):
        nm = unique_name()
        e1 = ent(2, nm, ("US", cst, ccity))
        kind = ["sub", "omit", "insert", "transpose"][k % 4]
        q = typo(r, nm, kind)
        for gv, geo in (("agree", ("US", cst, ccity)), ("absent", (None, None, None)),
                        ("disagree", ("US", "WA", g.cities["WA"][0]))):
            cases.append((f"typo_{kind}_{gv}", q, geo[0], geo[1], geo[2], [e1]))
    tampa = ("US", "FL", "Tampa")
    for nm, q, kind in (("Aur Trading Corp", "Aur Trdaing Corp", "lit_aur"),
                        ("Dice Druid", "Dice Durid", "lit_dice"),
                        ("Cabral", "Carbal", "lit_carbal")):
        e1 = ent(2, nm, tampa)
        for gv, geo in (("agree", tampa), ("absent", (None, None, None))):
            cases.append((f"{kind}_{gv}", q, geo[0], geo[1], geo[2], [e1]))
    # Tampa is a crowded city too: 3,000 same-city rivals for the literal cases.
    for _ in range(3000):
        ent(2, g.business("Tampa"), tampa)
    print(f"generated {len(ents):,} entities, {len(aliases):,} aliases, {len(cases)} cases "
          f"in {time.time() - t0:.0f}s")

    t0 = time.time()
    await c.copy_records_to_table("entity", records=ents, columns=ENT_COLS)
    await c.copy_records_to_table("entity_alias", records=aliases,
                                  columns=["entity_id", "alias_name", "alias_type", "status"])
    await c.execute("CREATE TABLE syn_case (case_id serial PRIMARY KEY, kind text, query_name text, "
                    "country text, region text, locality text, target_ids text[])")
    await c.copy_records_to_table("syn_case", records=cases,
                                  columns=["kind", "query_name", "country", "region", "locality", "target_ids"])
    await c.execute("ANALYZE")
    crowd = await c.fetchval("SELECT count(*) FROM entity WHERE region=$1 AND locality=$2", cst, ccity)
    print(f"loaded in {time.time() - t0:.0f}s; crowded city {ccity}, {cst}: {crowd:,} entities")
    await c.close()


BAND_TABLES = ("entity_fuzzy_band", "entity_fuzzy_phonetic_band")


async def cmd_rebuild(a):
    """The real rebuild. `--bulk` loads the band tables with their indexes dropped.

    As shipped, each band COPY maintains a PK and two secondary btrees per table
    (one of them, the `(band_id, band_hash) INCLUDE (entity_key)` lookup, is the
    PK's columns again — 252's redundant covering index). On the test stack that
    ran at ~250 entities/s falling to ~100/s, a 3+ hour rebuild. `--bulk` drops
    them, loads, and recreates the SAME DDL read back from the catalog, so the
    index measured afterwards is identical; only the load path differs.
    """
    from vitalgraph.entity_registry.entity_fuzzy_pg import EntityFuzzyIndexPG
    p = await pool()
    idx = EntityFuzzyIndexPG(pool=p, num_perm=64, threshold=0.3)
    ddl = []
    if a.bulk:
        async with p.acquire() as c:
            for t in BAND_TABLES:
                pk = await c.fetchrow(
                    "SELECT conname, pg_get_constraintdef(oid) AS d FROM pg_constraint "
                    "WHERE conrelid = $1::regclass AND contype = 'p'", t)
                idxs = await c.fetch(
                    "SELECT c.relname, pg_get_indexdef(i.indexrelid) AS d FROM pg_index i "
                    "JOIN pg_class c ON c.oid = i.indexrelid "
                    "WHERE i.indrelid = $1::regclass AND NOT i.indisprimary", t)
                if pk:
                    ddl.append(f"ALTER TABLE {t} ADD CONSTRAINT {pk['conname']} {pk['d']}")
                    await c.execute(f"ALTER TABLE {t} DROP CONSTRAINT {pk['conname']}")
                for r in idxs:
                    ddl.append(r["d"])
                    await c.execute(f"DROP INDEX {r['relname']}")
        print(f"bulk: dropped {len(ddl)} band indexes for the load")
    t0 = time.time()
    n = await idx.initialize(p, skip_lock=True)
    dt = time.time() - t0
    async with p.acquire() as c:
        if ddl:
            t1 = time.time()
            await c.execute("SET maintenance_work_mem = '2GB'")
            for d in ddl:
                await c.execute(d)
            print(f"bulk: recreated {len(ddl)} indexes in {time.time() - t1:.0f}s")
        b = await c.fetchval("SELECT count(*) FROM entity_fuzzy_band")
        ph = await c.fetchval("SELECT count(*) FROM entity_fuzzy_phonetic_band")
        await c.execute("VACUUM (ANALYZE) entity_fuzzy_band, entity_fuzzy_phonetic_band, entity_fuzzy_hash")
    print(f"rebuild ({ROOT.name}): {n:,} indexed, {b:,} primary + {ph:,} phonetic band rows, "
          f"{dt:.0f}s, {n / dt:.0f}/s")
    await p.close()


async def cmd_measure(a):
    from vitalgraph.entity_registry.entity_fuzzy_pg import EntityFuzzyIndexPG
    p = await pool()
    idx = EntityFuzzyIndexPG(pool=p, num_perm=64, threshold=0.3)
    seen = {}
    orig = idx.get_candidate_ids

    async def counting(*args, **kw):
        ids = await orig(*args, **kw)
        seen["n"] = len(ids)
        return ids
    idx.get_candidate_ids = counting
    # Band batches per query: 7 means every band was read; fewer means the
    # progressive early stop fired (issues/254 cause 2).
    orig_qb = idx.storage.query_bands

    async def counting_qb(*args, **kw):
        seen["batches"] = seen.get("batches", 0) + 1
        return await orig_qb(*args, **kw)
    idx.storage.query_bands = counting_qb
    # Only meaningful on code that still has the progressive query (before 254's fix).
    if a.no_early_stop and hasattr(idx.storage, "query_bands_progressive"):
        orig_prog = idx.storage.query_bands_progressive

        async def all_bands(table, band_queries, **kw):
            kw["min_candidates"] = 10 ** 9
            return await orig_prog(table, band_queries, **kw)
        idx.storage.query_bands_progressive = all_bands
    async with p.acquire() as c:
        cases = await c.fetch("SELECT * FROM syn_case ORDER BY case_id")
    # Warm once so the first case does not carry the cold cache alone.
    await idx.find_similar_by_name(name="warm up query", limit=10)
    rows = []
    for cs in cases:
        seen["batches"] = 0
        t0 = time.perf_counter()
        hits = await idx.find_similar_by_name(name=cs["query_name"], country=cs["country"],
                                              region=cs["region"], locality=cs["locality"],
                                              limit=a.limit)
        ms = (time.perf_counter() - t0) * 1000
        ids = [h.get("entity_id") for h in hits]
        tgt = list(cs["target_ids"])
        ranks = [ids.index(t) + 1 if t in ids else None for t in tgt]
        rows.append(dict(kind=cs["kind"], ranks=ranks, ms=ms, cand=seen.get("n"),
                         batches=seen["batches"],
                         top_score=hits[0]["score"] if hits else None,
                         tgt_score=next((h["score"] for h in hits if h.get("entity_id") == tgt[0]), None)))
    groups = {}
    for rw in rows:
        groups.setdefault(rw["kind"], []).append(rw)
    print(f"\n{a.tag} ({ROOT.name}), limit={a.limit}")
    print(f"{'kind':28} {'n':>4} {'all found':>9} {'rank1':>6} {'median cand':>11} {'median ms':>9} {'batches':>7}")
    for kind in sorted(groups):
        g = groups[kind]
        allf = sum(all(x is not None for x in rw["ranks"]) for rw in g)
        r1 = sum(rw["ranks"][0] == 1 for rw in g)
        print(f"{kind:28} {len(g):4} {allf:9} {r1:6} {statistics.median(rw['cand'] for rw in g):11.0f} "
              f"{statistics.median(rw['ms'] for rw in g):9.1f} {statistics.median(rw['batches'] for rw in g):7.0f}")
    out = Path(f"/tmp/scale248_{a.tag}.json")
    out.write_text(json.dumps(rows))
    print(f"rows -> {out}")
    await p.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("create")
    g = sub.add_parser("generate")
    g.add_argument("--business", type=int, default=640_000)
    g.add_argument("--placeholders", type=int, default=210_000)
    g.add_argument("--persons", type=int, default=400_000)
    g.add_argument("--aliases", type=int, default=120_000)
    g.add_argument("--cases", type=int, default=200)
    rb = sub.add_parser("rebuild")
    rb.add_argument("--bulk", action="store_true")
    m = sub.add_parser("measure")
    m.add_argument("--tag", default="after")
    m.add_argument("--limit", type=int, default=50)
    m.add_argument("--no-early-stop", action="store_true",
                   help="read every band (issues/254 cause 2 recall check)")
    a = ap.parse_args()
    asyncio.run({"create": cmd_create, "generate": cmd_generate,
                 "rebuild": cmd_rebuild, "measure": cmd_measure}[a.cmd](a))


if __name__ == "__main__":
    main()
