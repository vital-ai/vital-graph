# `vitalgraphimport --config` Is Accepted And Discarded

## Status: FIXED 2026-09-29 — `--config` now REFUSES with exit 2 and names the
## environment variables to use. NOT implemented as a config path, and the
## preferred option below is withdrawn for a reason the issue could not have
## known.

## Why option 1 was not taken

The fix preferred below — "give `VitalGraphConfig` an optional config path" —
would reverse a deliberate decision. Configuration has been ENVIRONMENT-ONLY
since **2026-02-03** (`5e62cf03`): `VitalGraphConfig.__init__` builds from
`_load_from_env()` and sets `config_path = None`, and the YAML loading was
removed in the same commit. That is seven months BEFORE this issue was written,
so satisfying the flag means re-adding file loading that was taken out on
purpose — a larger change than the flag justifies, and one that reintroduces two
sources of truth.

So the flag refuses instead, loudly, naming the profile variables from this
issue's own workaround section. The help text no longer promises a file.

One detail worth keeping: the first version of the refusal used `return 2` in
`main()`, which ends in `sys.exit(exit_code)` — so it exited **0** and the
refusal was as silent as the bug it replaced. `sys.exit(2)` now, with a test
asserting the code.

**Tests:** `tests/unit/test_import_cmd_config_flag.py`, 5 cases, including the
general form this issue asked for — every argument the parser accepts must be
read or refused. It found a false positive on `--format` first (explicit
`dest="file_format"`), which is why the check honours `dest=` rather than
deriving it from the flag name.


## What happens

    vitalgraphimport -s maint_large_trial -f data.nt -c /tmp/vg-test.yaml
    ❌ Space 'maint_large_trial' not found. Create it first with vitalgraphadmin.

The space existed. The CLI was reading a DIFFERENT DATABASE, because `--config`
does nothing: `args.config` is never referenced, and the loader is constructed
with no arguments at `vitalgraph_import_cmd.py:91`:

    config = VitalGraphConfig()

`VitalGraphConfig.__init__(self)` takes no path at all — it is driven entirely by
`VITALGRAPH_ENVIRONMENT` and `<PROFILE>_DB_*` environment variables. So the flag
cannot work as written, and the help text actively misleads:

    "--config", "-c", default=None,
    help="Path to vitalgraphdb-config.yaml (default: env / standard locations)"

## Why this one matters more than a normal dead flag

The failure it produces is WRITING TO THE WRONG DATABASE, silently. Here it
failed loudly only because the space happened not to exist in the other target.
Had the same space id existed in both — which is the normal case, since fixture
names are reused across the host cluster and the docker stack — the import would
have SUCCEEDED against the wrong one and said so.

That is the exact shape of `issues/055` and `issues/099`, and of the note in
`devtools/target.py`:

    "a migration ALTERS whichever cluster it reached, and the host carries
     same-named spaces, so it succeeds and says so"

It is also the shape of `trigger_maintenance(space_id=)`, which accepted a
parameter documented as "Target space (omit for auto-select)" and discarded it:
a caller who scoped the request got no error and no scoping.

## The workaround, for anyone hitting this now

Set the profile variables instead — the flag is inert:

    LOCAL_DB_HOST=localhost LOCAL_DB_PORT=5433 \
    LOCAL_DB_NAME=sparql_sql_graph \
    LOCAL_DB_USERNAME=postgres LOCAL_DB_PASSWORD=testpass \
    python -m vitalgraph.cmd.vitalgraph_import_cmd -s <space> -f <file>

## Fix — two options, and they are not equivalent

1. MAKE IT WORK. Give `VitalGraphConfig` an optional config path and pass
   `args.config` through. This is what the help text promises and what every
   other ops script in the repo does (`devtools/target.py` takes explicit
   `--host/--port/...`). Preferred.

2. REMOVE THE FLAG. Honest, and worse: the CLI then has no way to be pointed at
   a target except process-wide environment variables, which is the condition
   `devtools/target.py` was written to escape.

Either way the help text must stop describing behaviour that does not exist.

## Testing

Nothing covers the CLI's argument handling. A test that passes `--config` at a
path whose database differs from the environment, and asserts the CLI reads the
FILE, would have caught this. The general form — "every accepted argument
changes behaviour" — is worth a test of its own, given this is the second
instance in one session.
