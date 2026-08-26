"""The settings that NAME the database have no defaults, and .env is read.

Two defects, which had to be fixed together.

**The loader never read `.env`.** Its class docstring says "Supports
profile-specific .env files" and nothing ever called `load_dotenv` — only
`admin_cmd` did, for itself. So a host-run process ignored a correct `.env`
sitting in the repo root.

**And it defaulted the target.** `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USERNAME` fell
back to `postgres@localhost:5432/vitalgraph`. With nothing configured, a process
did not fail — it connected somewhere nobody named. On a machine where that
database exists it succeeds against the WRONG one and reports success, which is
`issues/055`: fixtures written to one cluster and read from another, both ends
reporting success because same-named spaces existed on both. This machine carries
`sparql_sql_graph` on 5432 AND 5433.

Fixing only the reading would have hidden the defaulting; fixing only the
defaulting would have made every host run fail with a correct `.env` present.

The PASSWORD keeps its empty default deliberately: an empty password is
legitimate under trust authentication, and a wrong one fails at the server rather
than redirecting anywhere.
"""

from __future__ import annotations

import pytest

from vitalgraph.config import config_loader as cl

TARGET_KEYS = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USERNAME")
ALL_DB_ENV = TARGET_KEYS + ("DB_PASSWORD",)


@pytest.fixture
def isolated_env(monkeypatch):
    """No DB_* anywhere, and no .env discovered.

    The repo root always holds a .env in a checkout, and `load_dotenv_files`
    searches upward from cwd, so it would be found and the failure path would
    never be reached from a test.
    """
    for key in ALL_DB_ENV:
        monkeypatch.delenv(key, raising=False)
        for profile in ("LOCAL", "DEV", "PROD", "TEST"):
            monkeypatch.delenv(f"{profile}_{key}", raising=False)
    monkeypatch.setattr(cl, "load_dotenv_files", lambda: None)


class TestTheTargetIsRequired:

    @pytest.mark.parametrize("key", TARGET_KEYS)
    def test_a_missing_setting_raises_naming_it(self, isolated_env, key, monkeypatch):
        # supply every OTHER key so the failure is unambiguous
        for other in TARGET_KEYS:
            if other != key:
                monkeypatch.setenv(other, "5432" if other == "DB_PORT" else "x")
        with pytest.raises(ValueError) as exc:
            cl.VitalGraphConfig()
        assert key in str(exc.value)

    def test_the_error_names_both_variables_it_looked_for(self, isolated_env):
        with pytest.raises(ValueError) as exc:
            cl.VitalGraphConfig()
        msg = str(exc.value)
        assert "LOCAL_DB_HOST" in msg and "DB_HOST" in msg, (
            f"the message must name the profile-prefixed and plain forms: {msg}")

    def test_the_password_is_still_optional(self, isolated_env, monkeypatch):
        """Trust authentication is legitimate, and a wrong password fails at the
        server rather than redirecting to another database."""
        for key in TARGET_KEYS:
            monkeypatch.setenv(key, "5432" if key == "DB_PORT" else "x")
        cfg = cl.VitalGraphConfig()
        assert cfg.get_database_config()["password"] == ""

    def test_a_complete_environment_is_used_verbatim(self, isolated_env, monkeypatch):
        for key, val in (("DB_HOST", "h1"), ("DB_PORT", "6543"),
                         ("DB_NAME", "db1"), ("DB_USERNAME", "u1"),
                         ("DB_PASSWORD", "p1")):
            monkeypatch.setenv(key, val)
        db = cl.VitalGraphConfig().get_database_config()
        assert (db["host"], db["port"], db["database"], db["username"],
                db["password"]) == ("h1", 6543, "db1", "u1", "p1")


class TestProfilePrecedence:
    """Pinned because it is surprising, and now REACHABLE.

    `_get_profile_env` checks `<PROFILE>_KEY` before the plain `KEY`. Before this
    change `.env` was never loaded, so `LOCAL_*` only existed if someone exported
    it. Now a `.env` full of `LOCAL_DB_*` outranks a plain `DB_HOST` from the real
    environment — which is why `.env` is in `.dockerignore`: inside the container
    it would outrank compose's `DB_HOST=postgres`.
    """

    def test_the_profile_prefixed_variable_wins(self, isolated_env, monkeypatch):
        for key in TARGET_KEYS:
            monkeypatch.setenv(key, "5432" if key == "DB_PORT" else "plain")
        monkeypatch.setenv("LOCAL_DB_HOST", "profile")
        assert cl.VitalGraphConfig().get_database_config()["host"] == "profile"


class TestDotenvIsActuallyLoaded:

    def test_the_loader_calls_it(self, monkeypatch):
        """The defect was that it never did, while documenting that it did."""
        called = []
        monkeypatch.setattr(cl, "load_dotenv_files",
                            lambda: called.append(True) or None)
        for key in TARGET_KEYS:
            monkeypatch.setenv(key, "5432" if key == "DB_PORT" else "x")
        cl.VitalGraphConfig()
        assert called, "VitalGraphConfig did not load .env"

    def test_it_finds_the_repo_env_from_the_checkout(self):
        """Not a mock: the real function must locate the real file.

        Skipped where there is no `.env` to find. It is gitignored, so a fresh
        checkout -- CI's, and any new clone -- does not have one, and asserting
        that the loader finds a file nobody shipped tests the developer's
        machine rather than the loader. `test_the_loader_calls_it` above covers
        the defect this was written for (the loader documented that it loaded
        .env and never did) without needing the file to exist.
        """
        import pathlib
        repo_env = pathlib.Path(__file__).resolve().parents[2] / ".env"
        if not repo_env.is_file():
            pytest.skip("no .env in this checkout — it is gitignored")
        assert cl.load_dotenv_files(), "no .env found from the repo checkout"
