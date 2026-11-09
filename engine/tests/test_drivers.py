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


def test_cloak_identity_args_hardening(tmp_path):
    p = _p(country="US")
    p.fingerprint.seed = 123456
    p.fingerprint.audio_mode = "Real"
    p.fingerprint.webgl_mode = "Real"

    args = drivers.cloak_identity_args(p, tmp_path)
    assert any(a.startswith("--fingerprint-storage-quota=") for a in args)
    quota_val = int(next(a.split("=")[1] for a in args if a.startswith("--fingerprint-storage-quota=")))
    assert 122880 <= quota_val <= 512000
    assert "--fingerprint-taskbar-height=48" in args
    assert "--fingerprint-max-touch-points=0" in args
    assert "--fingerprint-noise=false" in args
    assert not any(a.startswith("--fingerprint-gpu-vendor=") for a in args)
    assert not any(a.startswith("--fingerprint-gpu-renderer=") for a in args)

    # CloakBrowser Pro flags
    assert f"--fingerprint-platform-version={drivers._CH_PLATFORM_VERSION.get(p.fingerprint.os, '10.0.0')}" in args
    assert "--fingerprint-brand=Google Chrome" in args
    assert f"--fingerprint-brand-version={p.fingerprint.chrome_version}" in args
    assert "--fingerprint-windows-font-metrics=true" in args
    assert "--fingerprint-sapi-voices=true" in args
    assert f"--fingerprint-timezone={p.fingerprint.timezone}" in args
    assert f"--fingerprint-locale={p.fingerprint.locale}" in args

    # Altered WebGL mode re-enables GPU vendor and renderer flags
    p.fingerprint.webgl_mode = "Altered"
    args_altered = drivers.cloak_identity_args(p, tmp_path)
    assert any(a.startswith("--fingerprint-gpu-vendor=") for a in args_altered)
    assert any(a.startswith("--fingerprint-gpu-renderer=") for a in args_altered)

    # Audio mode Noise + Canvas mode Noise allows CloakBrowser noise (no --fingerprint-noise=false)
    p.fingerprint.audio_mode = "Noise"
    p.fingerprint.canvas_mode = "Noise"
    args_noise = drivers.cloak_identity_args(p, tmp_path)
    assert "--fingerprint-noise=false" not in args_noise


def test_cloak_dual_instance_pro_parameter_isolation(tmp_path):
    proxy_a = Proxy(server="http://127.0.0.1:17890", country="JP")
    proxy_b = Proxy(server="http://127.0.0.1:17890", country="JP")

    fp_a = generate(seed=41001, os="windows", locale="ja-JP", proxy=proxy_a)
    fp_a.hardware_concurrency = 8
    fp_a.device_memory = 8
    fp_a.screen_width = 1920
    fp_a.screen_height = 1080
    fp_a.webgl_vendor = "Google Inc. (Intel)"
    fp_a.webgl_renderer = "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"
    p_a = Profile(name="instance_a", fingerprint=fp_a, proxy=proxy_a)

    fp_b = generate(seed=58219, os="windows", locale="ja-JP", proxy=proxy_b)
    fp_b.hardware_concurrency = 16
    fp_b.device_memory = 16
    fp_b.screen_width = 2560
    fp_b.screen_height = 1440
    fp_b.webgl_vendor = "Google Inc. (NVIDIA)"
    fp_b.webgl_renderer = "ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 Direct3D11 vs_5_0 ps_5_0, D3D11)"
    p_b = Profile(name="instance_b", fingerprint=fp_b, proxy=proxy_b)

    args_a = drivers.cloak_identity_args(p_a, tmp_path / "a")
    args_b = drivers.cloak_identity_args(p_b, tmp_path / "b")

    flags_a = dict(a.split("=", 1) for a in args_a if "=" in a)
    flags_b = dict(a.split("=", 1) for a in args_b if "=" in a)

    # Assert Pro flags presence and values
    for flags in (flags_a, flags_b):
        assert flags["--fingerprint-brand"] == "Google Chrome"
        assert flags["--fingerprint-windows-font-metrics"] == "true"
        assert flags["--fingerprint-sapi-voices"] == "true"
        assert flags["--fingerprint-timezone"] == "Asia/Tokyo"
        assert flags["--fingerprint-locale"] == "ja-JP"

    # Assert seed, hardware concurrency, device memory, screen width/height,
    # and GPU vendor/renderer are strictly different and isolated between A and B
    assert flags_a["--fingerprint"] != flags_b["--fingerprint"]
    assert flags_a["--fingerprint-hardware-concurrency"] != flags_b["--fingerprint-hardware-concurrency"]
    assert flags_a["--fingerprint-hardware-concurrency"] == "8"
    assert flags_b["--fingerprint-hardware-concurrency"] == "16"
    assert p_a.fingerprint.device_memory != p_b.fingerprint.device_memory
    assert p_a.fingerprint.device_memory == 8
    assert p_b.fingerprint.device_memory == 16
    assert flags_a["--fingerprint-screen-width"] != flags_b["--fingerprint-screen-width"]
    assert flags_a["--fingerprint-screen-width"] == "1920"
    assert flags_b["--fingerprint-screen-width"] == "2560"
    assert flags_a["--fingerprint-screen-height"] != flags_b["--fingerprint-screen-height"]
    assert flags_a["--fingerprint-screen-height"] == "1080"
    assert flags_b["--fingerprint-screen-height"] == "1440"
    assert flags_a["--fingerprint-gpu-vendor"] != flags_b["--fingerprint-gpu-vendor"]
    assert flags_a["--fingerprint-gpu-vendor"] == "Google Inc. (Intel)"
    assert flags_b["--fingerprint-gpu-vendor"] == "Google Inc. (NVIDIA)"
    assert flags_a["--fingerprint-gpu-renderer"] != flags_b["--fingerprint-gpu-renderer"]
    assert "Intel" in flags_a["--fingerprint-gpu-renderer"]
    assert "NVIDIA" in flags_b["--fingerprint-gpu-renderer"]


def test_webrtc_arg_modes():
    p = _p(country="US")
    # Altered with CloakBrowser exit IP spoofed keeps default_public_interface_only
    assert "default_public_interface_only" in drivers._webrtc_arg(p, cloak_webrtc_spoofed=True)[0]
    # Altered with proxy and un-spoofed CloakBrowser forces proxy UDP
    assert "disable_non_proxied_udp" in drivers._webrtc_arg(p, cloak_webrtc_spoofed=False)[0]
    # Real mode disables policy override
    p.fingerprint.webrtc_mode = "Real"
    assert drivers._webrtc_arg(p) == []
    # Disabled mode forces disable_non_proxied_udp even without proxy
    p_no_px = _p(country=None)
    p_no_px.fingerprint.webrtc_mode = "Disabled"
    assert "disable_non_proxied_udp" in drivers._webrtc_arg(p_no_px)[0]
