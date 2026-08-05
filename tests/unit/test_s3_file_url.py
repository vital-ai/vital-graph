"""
Storage endpoint normalisation and URL construction.

The endpoint is supplied both ways in practice — the docstring says
'localhost:9000', while deployments set 'http://minio:9000' (STORAGE_ENDPOINT in
docker-compose). Consumers used to each re-derive what they needed: the Minio
client stripped the scheme locally, while get_file_url prepended one
unconditionally and produced 'http://http://minio:9000/...' in every stored
`hasFileURL`. The endpoint is now split once in __init__ so no consumer has to
handle it. Surfaced by issue 018 item 4; it affected the Files API too.
"""

import pytest

from vitalgraph.storage.s3_file_manager import S3FileManager, _split_endpoint


class TestSplitEndpoint:
    @pytest.mark.parametrize(
        "given,expected",
        [
            ("http://minio:9000", ("minio:9000", "http")),
            ("https://s3.example.com", ("s3.example.com", "https")),
            ("minio:9000", ("minio:9000", None)),
            ("localhost:9000", ("localhost:9000", None)),
            ("HTTPS://Example.com", ("Example.com", "https")),
            ("http://minio:9000/", ("minio:9000", "http")),
            ("  http://minio:9000  ", ("minio:9000", "http")),
        ],
    )
    def test_splits_host_and_scheme(self, given, expected):
        assert _split_endpoint(given) == expected

    def test_missing_endpoint_is_the_aws_case(self):
        assert _split_endpoint(None) == (None, None)
        assert _split_endpoint("") == (None, None)


def _manager(endpoint, use_ssl=False):
    """Build a manager without __init__ (which constructs a live Minio client)."""
    m = S3FileManager.__new__(S3FileManager)
    host, scheme = _split_endpoint(endpoint)
    m.endpoint_url = endpoint
    m.endpoint_host = host
    m.bucket_name = "vitalgraph-files"
    m.use_ssl = (scheme == "https") if scheme else use_ssl
    m.region = "us-east-1"
    return m


class TestGetFileUrl:
    def test_endpoint_with_scheme_is_not_doubled(self):
        url = _manager("http://minio:9000").get_file_url("obj")
        assert url == "http://minio:9000/vitalgraph-files/obj"
        assert "http://http://" not in url

    def test_endpoint_without_scheme_still_works(self):
        url = _manager("minio:9000").get_file_url("obj")
        assert url == "http://minio:9000/vitalgraph-files/obj"

    def test_https_endpoint(self):
        url = _manager("https://s3.example.com").get_file_url("obj")
        assert url == "https://s3.example.com/vitalgraph-files/obj"

    def test_trailing_slash_does_not_double_up(self):
        url = _manager("http://minio:9000/").get_file_url("obj")
        assert url == "http://minio:9000/vitalgraph-files/obj"

    def test_use_ssl_governs_scheme_when_endpoint_has_none(self):
        url = _manager("minio:9000", use_ssl=True).get_file_url("obj")
        assert url.startswith("https://")

    def test_bucket_override(self):
        url = _manager("http://minio:9000").get_file_url("obj", bucket_name="other")
        assert url == "http://minio:9000/other/obj"

    def test_aws_style_when_no_endpoint(self):
        url = _manager(None).get_file_url("obj")
        assert url == "https://s3.us-east-1.amazonaws.com/vitalgraph-files/obj"

    def test_url_building_ignores_the_raw_endpoint_url(self):
        """
        `endpoint_url` keeps the raw configured string for logging and is the
        exact shape that caused the doubled-scheme bug. Pin that URL building
        reads `endpoint_host` instead, so a future edit cannot quietly go back
        to the raw value.
        """
        m = _manager("http://minio:9000")
        m.endpoint_url = "http://SHOULD-NOT-BE-USED:1234"
        assert m.get_file_url("obj") == "http://minio:9000/vitalgraph-files/obj"


class TestConstructorNormalisation:
    """
    Exercise the real __init__ with Minio patched out, so these assertions cover
    the constructor rather than the test helper above.

    An explicit scheme is the more specific statement, so it decides both the
    client's `secure` flag and the generated URLs. A contradiction with use_ssl
    is a config mistake and is logged rather than silently applied.
    """

    @staticmethod
    def _build(monkeypatch, endpoint, use_ssl):
        import vitalgraph.storage.s3_file_manager as mod

        calls = {}

        class FakeMinio:
            def __init__(self, host, access_key=None, secret_key=None, secure=None):
                calls['host'] = host
                calls['secure'] = secure

        monkeypatch.setattr(mod, "Minio", FakeMinio)
        monkeypatch.setattr(mod, "MINIO_AVAILABLE", True)
        monkeypatch.setattr(mod.S3FileManager, "_ensure_bucket_exists", lambda self: None)

        manager = mod.S3FileManager(
            endpoint_url=endpoint, access_key_id="k", secret_access_key="s",
            bucket_name="vitalgraph-files", use_ssl=use_ssl,
        )
        return manager, calls

    def test_client_receives_host_without_scheme(self, monkeypatch):
        _, calls = self._build(monkeypatch, "http://minio:9000", False)
        assert calls['host'] == "minio:9000"

    def test_https_endpoint_overrides_use_ssl_false(self, monkeypatch):
        m, calls = self._build(monkeypatch, "https://s3.example.com", False)
        assert m.use_ssl is True
        assert calls['secure'] is True
        assert m.get_file_url("obj").startswith("https://")

    def test_http_endpoint_overrides_use_ssl_true(self, monkeypatch):
        m, calls = self._build(monkeypatch, "http://minio:9000", True)
        assert m.use_ssl is False
        assert calls['secure'] is False
        assert m.get_file_url("obj").startswith("http://")

    def test_contradiction_is_logged(self, monkeypatch, caplog):
        with caplog.at_level("WARNING"):
            self._build(monkeypatch, "https://s3.example.com", False)
        assert any("use_ssl" in r.message for r in caplog.records), \
            "a scheme/use_ssl mismatch must be visible, not silent"

    def test_no_warning_when_consistent(self, monkeypatch, caplog):
        with caplog.at_level("WARNING"):
            self._build(monkeypatch, "http://minio:9000", False)
        assert not [r for r in caplog.records if "use_ssl" in r.message]

    def test_scheme_less_endpoint_leaves_use_ssl_alone(self, monkeypatch):
        m, calls = self._build(monkeypatch, "minio:9000", True)
        assert m.use_ssl is True
        assert calls['host'] == "minio:9000"
        assert calls['secure'] is True

    def test_deployed_config_shape_round_trips(self, monkeypatch):
        # The exact value docker-compose sets for the test stack.
        m, calls = self._build(monkeypatch, "http://minio:9000", False)
        assert calls['host'] == "minio:9000"
        assert m.get_file_url("some_object") == "http://minio:9000/vitalgraph-files/some_object"
