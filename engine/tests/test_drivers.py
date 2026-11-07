"""Tests for the pluggable launch-driver registry."""

from persona import drivers
from persona.models import Profile
from persona.fingerprint import generate


def test_builtin_engines_registered():
    names = drivers.names()
    assert "playwright" in names
    assert "patchright" in names
    assert "camoufox" in names


def test_availability_map_covers_all():
    avail = drivers.available()
    assert set(avail) == set(drivers.names())
    assert all(isinstance(v, bool) for v in avail.values())


def test_unknown_engine_raises():
    try:
        drivers.get("does-not-exist")
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "Unknown engine" in str(e)


def test_uninstalled_engine_raises_with_hint():
    # camoufox isn't a test dependency, so this should raise a helpful error.
    if not drivers.is_installed("camoufox"):
        try:
            drivers.get("camoufox")
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "camoufox" in str(e)


def test_profile_defaults_to_playwright_engine():
    p = Profile(name="x", fingerprint=generate(os="windows"))
    assert p.engine == "playwright"
    # round-trips through serialization
    assert Profile.from_dict(p.to_dict()).engine == "playwright"


# ---- geolocation + WebRTC coherence --------------------------------------
from persona.models import Proxy
from persona.drivers import _webrtc_arg


def _p(country=None, locale="en-US"):
    proxy = Proxy(server="http://h:1", country=country) if country else None
    return Profile(name="g", fingerprint=generate(seed=1, locale=locale), proxy=proxy)


def test_webrtc_forces_proxy_when_one_is_set():
    assert "disable_non_proxied_udp" in _webrtc_arg(_p(country="US"))[0]


def test_webrtc_hides_local_ip_without_proxy():
    assert "default_public_interface_only" in _webrtc_arg(_p())[0]


def test_camoufox_launch_kwargs(tmp_path):
    (tmp_path / drivers.CAMOUFOX_FP_FILE).write_text('{"mock": "fp"}')
    p = _p(country="US")
    kwargs = drivers._camoufox_launch_kwargs(p, tmp_path, headless=True)
    assert kwargs["headless"] is True
    assert kwargs["locale"] == "en-US"
    assert kwargs["persistent_context"] is True
    assert kwargs["user_data_dir"] == str(tmp_path)
    assert kwargs["i_know_what_im_doing"] is True
    assert kwargs["fingerprint"] == {"mock": "fp"}
    assert kwargs["geoip"] is True
    assert kwargs["proxy"]["server"] == "http://h:1"

def test_camoufox_prefetch_skipped_in_locked(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(drivers, "prefetch_geo", lambda p: called.append(p))

    class DummyStore:
        def user_data_path(self, pid):
            return tmp_path / pid

    p_cam = Profile(name="cam", engine="camoufox", fingerprint=generate(seed=1))
    p_pw = Profile(name="pw", engine="playwright", fingerprint=generate(seed=2))

    @drivers._locked
    def dummy_driver(profile, store, *args, keep_open=False, **kwargs):
        return None

    store = DummyStore()
    dummy_driver(p_cam, store, keep_open=False)
    assert len(called) == 0

    dummy_driver(p_pw, store, keep_open=False)
    assert len(called) == 1
