#!/usr/bin/env python3
"""Render the canonical PostgreSQL configuration (postgresql.vitalgraph.yaml) for one
node size, in the form a deployment profile consumes.

    render_config.py --mem-mb 65536 --vcpu 8 --format cnpg      # Cluster spec.postgresql fragment (YAML)
    render_config.py --mem-mb 65536 --vcpu 8 --format conf      # postgresql.conf lines (EC2 / Patroni)
    render_config.py --mem-mb 65536 --vcpu 8 --format sql       # bootstrap: role and database settings, extensions
    render_config.py ... --format cnpg --check FILE             # fail if FILE's rendered block differs

The CNPG fragment is written between the markers
    # BEGIN rendered by deploy/postgres/render_config.py
    # END rendered by deploy/postgres/render_config.py
so `--write FILE` replaces exactly that block in a manifest, and `--check FILE`
fails (exit 1) when someone edited the manifest instead of the canonical file.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CANON = HERE / "postgresql.vitalgraph.yaml"
BEGIN = "# BEGIN rendered by deploy/postgres/render_config.py"
END = "# END rendered by deploy/postgres/render_config.py"

_ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Load,
            ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.USub)
_FUNCS = {"min": min, "max": max, "round": round}


def _eval(expr: str, env: dict) -> int:
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise ValueError(f"not allowed in a size expression: {type(node).__name__} in {expr!r}")
        if isinstance(node, ast.Name) and node.id not in env and node.id not in _FUNCS:
            raise ValueError(f"unknown name {node.id!r} in {expr!r}")
    return eval(compile(tree, "<size>", "eval"), {"__builtins__": {}, **_FUNCS}, env)


def resolve(canon: dict, mem_mb: int, vcpu: int) -> dict:
    env = {"mem_mb": mem_mb, "vcpu": vcpu}
    out = {}
    for k, v in canon["parameters"].items():
        out[k] = re.sub(r"\{([^}]*)\}", lambda m: str(_eval(m.group(1), env)), str(v))
    return out


def render_cnpg(canon: dict, params: dict) -> str:
    lines = [BEGIN, "    parameters:"]
    for k, v in params.items():
        lines.append(f'      {k}: "{v}"')
    lines.append("    shared_preload_libraries:")
    for lib in canon["shared_preload_libraries"]:
        lines.append(f"      - {lib}")
    lines.append("    " + END)
    return "    " + "\n".join(lines)


def render_conf(canon: dict, params: dict) -> str:
    lines = ["# rendered by deploy/postgres/render_config.py from postgresql.vitalgraph.yaml; do not edit"]
    lines += [f"{k} = '{v}'" for k, v in params.items()]
    lines.append(f"shared_preload_libraries = '{', '.join(canon['shared_preload_libraries'])}'")
    return "\n".join(lines) + "\n"


def render_sql(canon: dict, database: str) -> str:
    lines = ["-- rendered by deploy/postgres/render_config.py from postgresql.vitalgraph.yaml; do not edit"]
    for role, settings in (canon.get("role_settings") or {}).items():
        for k, v in settings.items():
            lines.append(f"ALTER ROLE {role} SET {k} = '{v}';")
    for k, v in (canon.get("database_settings") or {}).items():
        lines.append(f"ALTER DATABASE {database} SET {k} = '{v}';")
    for ext in canon.get("extensions") or []:
        lines.append(f"CREATE EXTENSION IF NOT EXISTS {ext};")
    return "\n".join(lines) + "\n"


def _block(text: str) -> str:
    i, j = text.find(BEGIN), text.find(END)
    if i < 0 or j < 0:
        raise SystemExit(f"no rendered block (markers {BEGIN!r} ... {END!r})")
    start = text.rfind("\n", 0, i) + 1
    return text[start:j + len(END)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mem-mb", type=int, required=True)
    ap.add_argument("--vcpu", type=int, required=True)
    ap.add_argument("--format", choices=("cnpg", "conf", "sql"), required=True)
    ap.add_argument("--database", default="sparql_sql_graph")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", type=Path, help="replace the rendered block in this manifest")
    g.add_argument("--check", type=Path, help="fail if this manifest's rendered block differs")
    a = ap.parse_args()
    canon = yaml.safe_load(CANON.read_text())
    params = resolve(canon, a.mem_mb, a.vcpu)
    if a.format == "conf":
        out = render_conf(canon, params)
    elif a.format == "sql":
        out = render_sql(canon, a.database)
    else:
        out = render_cnpg(canon, params)
    if a.write or a.check:
        if a.format != "cnpg":
            raise SystemExit("--write/--check apply to --format cnpg")
        f = a.write or a.check
        text = f.read_text()
        have = _block(text)
        if a.check:
            if have != out:
                sys.stderr.write(f"{f}: rendered block differs from the canonical configuration; "
                                 f"run render_config.py ... --write {f}\n")
                return 1
            print(f"{f}: matches the canonical configuration")
            return 0
        f.write_text(text.replace(have, out))
        print(f"{f}: rendered block written")
        return 0
    sys.stdout.write(out if out.endswith("\n") else out + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
