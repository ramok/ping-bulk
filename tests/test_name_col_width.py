"""Unit tests for _get_name_col_width.

Covers three related bugs:

1. ``_name_col_dirty`` was never cleared because it waited for ALL
   ``len(DNS_MODES)`` entries to accumulate in the cache.  In practice only
   one mode is active at a time, so the flag stayed ``True`` forever and the
   column was recomputed on every draw frame.

2. As DNS resolved asynchronously after a mode switch, each recomputed frame
   returned a wider value — the column grew continuously for the lifetime of
   the process instead of stabilising once all DNS was resolved.

3. Monitors in *folded* sections were still counted when computing the column
   width, so a host with a long name in a collapsed section (e.g.
   ``www.evologics.de:http (IP:80)`` in the "web services" subsection) inflated
   the column even though it was never rendered.

The fix (three parts):
  a) Clear ``_name_col_dirty`` immediately after computing *any* one mode.
  b) ``resolve_dns`` accepts an ``on_resolved`` callback; callers pass
     ``_invalidate_name_col_cache`` so the column re-expands on the next
     draw frame after DNS completes, then stays stable.
  c) Skip monitors whose immediate parent section is folded when computing
     max_name_len; invalidate the cache whenever fold state changes.
"""

import pytest
from unittest.mock import patch


def _make_app(pb, tmp_path):
    cfg = tmp_path / "ping-bulk" / "config"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('')
    with patch.object(pb, '_config_path', return_value=str(cfg)):
        return pb.Application([], log_file=None)


def _internet_section(pb, app):
    """Set up an 'internet' section mirroring the user's evo-lan file."""
    sec = pb.SectionLabel("internet", level=1, folded_default=False)

    m1 = pb.PingMonitor("10.10.0.1")
    m1.resolved_ip = "10.10.0.1"
    m1.resolved_hostname = "router"
    m1.resolv_static = True

    m2 = pb.PingMonitor("24.40.136.201")
    m2.resolved_ip = "24.40.136.201"
    m2.resolved_hostname = "gw-versatel"
    m2.resolv_static = True

    m3 = pb.PingMonitor("8.8.8.8")
    m3.resolved_ip = "8.8.8.8"
    m3.resolved_hostname = "gw-canary-versatel"
    m3.resolv_static = True

    app.entries = [sec, m1, m2, m3]
    app.monitors = [m1, m2, m3]
    return m1, m2, m3


class TestNameColWidthGap:
    """The stat column must sit within 4 characters of the longest name."""

    def test_gap_at_most_4_name_plus_ip(self, pb, tmp_path):
        """stat_col − longest name ≤ 4 with name+ip dns mode."""
        app = _make_app(pb, tmp_path)
        m1, m2, m3 = _internet_section(pb, app)

        w = app._get_name_col_width("name+ip")
        stat_col = w + 1
        indent = 2  # level-1 section

        max_len = max(
            indent + len(m.get_display_name("name+ip"))
            for m in [m1, m2, m3]
        )
        gap = stat_col - max_len
        assert gap <= 4, (
            f"Gap too large: stat_col={stat_col}, max_name={max_len}, gap={gap}"
        )

        for m in app.monitors:
            m.stop()

    def test_section_title_visible_with_autofold_suffix(self, pb, tmp_path):
        """Section title must not be fully hidden even with the longest count suffix."""
        app = _make_app(pb, tmp_path)
        _internet_section(pb, app)

        w = app._get_name_col_width("name+ip")
        stat_col = w + 1

        prefix = "── [-] "          # level-1 section: no extra indent
        count_suffix = " (autofold lock)"   # len = 16, the longest suffix
        available = stat_col - len(prefix) - len(count_suffix) - 1
        assert available >= 1, (
            f"Section title would be fully truncated: available={available}"
        )

        for m in app.monitors:
            m.stop()


class TestNameColDirtyFlag:
    """The dirty flag must clear after the first computation, not after all modes."""

    def test_dirty_clears_after_first_compute(self, pb, tmp_path):
        """_name_col_dirty becomes False after _get_name_col_width for any one mode."""
        app = _make_app(pb, tmp_path)
        _internet_section(pb, app)

        app._name_col_dirty = True
        app._name_col_cache.clear()

        app._get_name_col_width("name+ip")

        assert not app._name_col_dirty, (
            "dirty flag should be False after computing one mode"
        )

        for m in app.monitors:
            m.stop()

    def test_column_stable_across_repeated_frames(self, pb, tmp_path):
        """Column width must not change between consecutive calls with no state change.

        Previously the dirty flag was never cleared (waited for all DNS modes),
        so every draw frame recomputed the width and the column grew as DNS
        resolved in the background.
        """
        app = _make_app(pb, tmp_path)
        _internet_section(pb, app)

        app._name_col_dirty = True
        app._name_col_cache.clear()

        # Simulate many draw frames
        widths = [app._get_name_col_width("name+ip") for _ in range(10)]

        assert len(set(widths)) == 1, (
            f"Column width changed across frames: {widths}"
        )

        for m in app.monitors:
            m.stop()

    def test_column_expands_after_dns_resolves(self, pb, tmp_path):
        """Column expands when DNS resolves and the cache is invalidated."""
        app = _make_app(pb, tmp_path)
        sec = pb.SectionLabel("test", level=1, folded_default=False)

        m1 = pb.PingMonitor("10.10.0.1")
        m1.resolved_ip = None
        m1.resolved_hostname = None

        app.entries = [sec, m1]
        app.monitors = [m1]

        # Pre-DNS: column is narrow (falls back to raw IP)
        w_before = app._get_name_col_width("name+ip")

        # DNS resolves → triggers cache invalidation
        m1.resolved_ip = "10.10.0.1"
        m1.resolved_hostname = "gw-canary-versatel"   # much longer than "10.10.0.1"
        app._invalidate_name_col_cache()

        w_after = app._get_name_col_width("name+ip")

        assert w_after > w_before, (
            f"Column did not expand after DNS resolved: before={w_before}, after={w_after}"
        )

        for m in app.monitors:
            m.stop()

    def test_resolve_dns_callback_invoked(self, pb, tmp_path):
        """resolve_dns() must call on_resolved when provided."""
        app = _make_app(pb, tmp_path)

        m = pb.PingMonitor("127.0.0.1")
        m.resolved_ip = "127.0.0.1"   # pre-set to avoid real DNS lookup

        called = []

        def _cb():
            called.append(True)

        # Patch socket calls to avoid real DNS traffic
        import socket
        from unittest.mock import patch as _patch
        with _patch.object(socket, 'gethostbyname', return_value="127.0.0.1"), \
             _patch.object(socket, 'gethostbyaddr', return_value=("localhost", [], ["127.0.0.1"])):
            m.resolve_dns(on_resolved=_cb)

        assert called, "on_resolved callback was not invoked"

        m.stop()


class TestNameColFoldVisibility:
    """Folded sections must not inflate the hostname column width."""

    def test_folded_subsection_does_not_inflate_column(self, pb, tmp_path):
        """A long host name inside a folded subsection must not widen the column.

        Reproduces: 'web services' subsection (L2) hosts www.evologics.de:http
        with a long name+ip display drives stat_col high even though the section
        is autofold-collapsed and the host is never rendered.
        """
        app = _make_app(pb, tmp_path)

        # Level-1 section "internet" with a couple of short hosts
        sec_internet = pb.SectionLabel("internet", level=1, folded_default=False)
        m_short = pb.PingMonitor("8.8.8.8")
        m_short.resolved_ip = "8.8.8.8"
        m_short.resolved_hostname = "gw-canary-versatel"

        # Level-2 subsection "web services" — *folded* — with a long-name host
        sec_web = pb.SectionLabel("web services", level=2, folded_default=False)
        sec_web.folded = True
        pm = pb.PortMonitor("www.evologics.de", "http")
        pm.resolved_ip = "185.234.218.227"
        pm.resolved_hostname = "www.evologics.de"

        app.entries = [sec_internet, m_short, sec_web, pm]
        app.monitors = [m_short, pm]

        w = app._get_name_col_width("name+ip")
        stat_col = w + 1

        # The folded PortMonitor display would be 46 chars including indent.
        # It must NOT drive the column — only m_short (30 chars) should count.
        long_name_len = 4 + len(pm.get_display_name("name+ip"))  # 4-char indent
        short_name_len = 2 + len(m_short.get_display_name("name+ip"))  # 2-char indent

        assert stat_col <= short_name_len + 4, (
            f"Folded host inflated stat_col={stat_col} beyond gap-4 bound "
            f"({short_name_len}+4={short_name_len+4}). "
            f"Folded display was {long_name_len} chars."
        )

        for m in app.monitors:
            m.stop()

    def test_column_shrinks_when_section_folds(self, pb, tmp_path):
        """After folding a section with a long-named host, the column narrows."""
        app = _make_app(pb, tmp_path)

        sec = pb.SectionLabel("internet", level=1, folded_default=False)
        m_long = pb.PingMonitor("24.40.136.201")
        m_long.resolved_ip = "24.40.136.201"
        m_long.resolved_hostname = "gw-versatel-very-long-hostname-indeed"

        app.entries = [sec, m_long]
        app.monitors = [m_long]

        w_open = app._get_name_col_width("name+ip")

        # Fold the section → m_long should no longer count
        sec.folded = True
        app._fold_state_changed()

        w_folded = app._get_name_col_width("name+ip")

        assert w_folded < w_open, (
            f"Column did not shrink after folding: open={w_open}, folded={w_folded}"
        )

        for m in app.monitors:
            m.stop()

    def test_fold_state_changed_invalidates_cache(self, pb, tmp_path):
        """_fold_state_changed must set the dirty flag and clear the cache."""
        app = _make_app(pb, tmp_path)

        # Populate cache with a dummy entry
        app._name_col_cache["off"] = 42
        app._name_col_dirty = False

        app._fold_state_changed()

        assert app._name_col_dirty, "_fold_state_changed must set dirty=True"
        assert not app._name_col_cache, "_fold_state_changed must clear the cache"

