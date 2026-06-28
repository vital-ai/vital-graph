"""Verify vitalgraph_term_uuid() SQL function matches Python _generate_term_uuid()."""
import uuid
import subprocess
import sys

_VITALGRAPH_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')

def _generate_term_uuid(term_text, term_type, lang=None, datatype_id=None):
    parts = [term_text, term_type]
    if lang is not None:
        parts.append(f"lang:{lang}")
    if datatype_id is not None:
        parts.append(f"datatype:{datatype_id}")
    return uuid.uuid5(_VITALGRAPH_NS, "\x00".join(parts))

def sql_uuid(text, ttype, lang=None, datatype_id=None):
    lang_arg = f"'{lang}'" if lang else "NULL"
    dt_arg = str(datatype_id) if datatype_id is not None else "NULL"
    query = f"SELECT vitalgraph_term_uuid('{text}', '{ttype}', {lang_arg}, {dt_arg});"
    result = subprocess.run(
        ['psql-17', '-d', 'vitalgraphdb', '-t', '-A', '-c', query],
        capture_output=True, text=True)
    return result.stdout.strip()

tests = [
    ("hello", "U", None, None),
    ("hello", "L", None, None),
    ("2026-04-30T12:00:00+00:00", "L", None, 9),
    ("some text", "L", "en", None),
    ("label", "L", "fr", 5),
    ("0", "L", None, 3),
    ("true", "L", None, 7),
]

ok = True
for text, ttype, lang, dt_id in tests:
    py = str(_generate_term_uuid(text, ttype, lang, dt_id))
    sq = sql_uuid(text, ttype, lang, dt_id)
    match = "PASS" if py == sq else "FAIL"
    if py != sq:
        ok = False
    print(f"  {match}: ({text!r}, {ttype}, lang={lang}, dt={dt_id})")
    if py != sq:
        print(f"    Python: {py}")
        print(f"    SQL:    {sq}")

print()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
