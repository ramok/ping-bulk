import os
from tmux_helper import TmuxSession

def test_cli_duplicate_hosts(app_path, tmp_path, request):
    """Test that passing duplicate hosts on the CLI produces a warning."""
    sess_name = f"{request.node.name}"
    with TmuxSession(sess_name) as session:
        session.start_app(["127.0.0.1", "127.0.0.1", "127.0.0.2"])
        session.wait_for("duplicate host ignored: 127.0.0.1")
        lines = session.capture_pane().splitlines()

        # Verify that only two hosts are actually monitored (plus header/footer)
        # One way is to check the number of rows or check that 127.0.0.2 is there
        # and 127.0.0.1 appears only once in the host list.
        host_count = sum(1 for line in lines if "127.0.0.1" in line and "duplicate host ignored" not in line and "Events" not in line and "ping-bulk" not in line)
        assert host_count == 1, "Duplicate host should only appear once in the monitor list"
        assert any("warning: duplicate host ignored: 127.0.0.1" in line for line in lines)

def test_file_duplicate_hosts(app_path, tmp_path, request):
    """Test that duplicate hosts in a file produce a warning."""
    hosts_file = tmp_path / "hosts.txt"
    hosts_file.write_text("127.0.0.1\n127.0.0.1\n127.0.0.3\n")

    sess_name = f"{request.node.name}"
    with TmuxSession(sess_name) as session:
        session.start_app(["-f", str(hosts_file)])
        session.wait_for("duplicate host ignored: 127.0.0.1")
        lines = session.capture_pane().splitlines()

        host_count = sum(1 for line in lines if "127.0.0.1" in line and "duplicate host ignored" not in line and "Events" not in line and "ping-bulk" not in line)
        assert host_count == 1, "Duplicate host should only appear once in the monitor list"
        assert any("warning: duplicate host ignored: 127.0.0.1" in line for line in lines)
