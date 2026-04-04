import pytest
import socket
from unittest.mock import patch, MagicMock

def test_port_monitor_init_numeric(pb):
    monitor = pb.PortMonitor("localhost", "80")
    assert monitor.port == "80"
    assert monitor.port_num == 80
    assert monitor.port_name in ("http", "80")

def test_port_monitor_init_name(pb):
    monitor = pb.PortMonitor("localhost", "http")
    assert monitor.port == "http"
    assert monitor.port_num == 80
    assert monitor.port_name == "http"

def test_port_monitor_init_invalid(pb):
    monitor = pb.PortMonitor("localhost", "invalid_port_name")
    assert monitor.port == "invalid_port_name"
    assert monitor.port_num is None
    assert monitor.port_name == "invalid_port_name"

def test_port_monitor_get_display_name(pb):
    monitor = pb.PortMonitor("127.0.0.1", "80")
    monitor.resolved_hostname = "localhost"
    assert monitor.get_display_name('off') == "127.0.0.1:80"
    assert monitor.get_display_name('hostname') in ("localhost", "localhost:80", "localhost:http")
    assert monitor.get_display_name('ip') == "127.0.0.1:80"

@patch('socket.create_connection')
def test_port_monitor_ping_success(mock_create_connection, pb):
    monitor = pb.PortMonitor("localhost", "80")
    monitor.running = False # Run once

    # We need to test the loop, but it's a while loop. Let's patch time.sleep to raise an exception to break the loop after one iteration if running doesn't work.
    # Actually, if we set monitor.running = False inside the mock, it will do one iteration.
    def side_effect(*args, **kwargs):
        monitor.running = False
        return MagicMock()
    mock_create_connection.side_effect = side_effect

    monitor.running = True
    monitor.ping()

    assert monitor.alive is True
    assert monitor.rx_count == 1
    assert monitor.xx_count == 0
    assert len(monitor.history) == 1

@patch('socket.create_connection')
def test_port_monitor_ping_fail(mock_create_connection, pb):
    monitor = pb.PortMonitor("localhost", "80")

    def side_effect(*args, **kwargs):
        monitor.running = False
        raise ConnectionRefusedError()
    mock_create_connection.side_effect = side_effect

    monitor.running = True
    monitor.ping()

    assert monitor.alive is False
    assert monitor.rx_count == 0
    assert monitor.xx_count == 1
    assert len(monitor.history) == 1
    assert monitor.history[0] is None

def test_cmd_port(pb):
    app = pb.Application([])
    app._cmd_port("localhost 80")
    assert len(app.monitors) == 1
    assert isinstance(app.monitors[0], pb.PortMonitor)
    assert app.monitors[0].host == "localhost:80"

def test_cmd_port_invalid_args(pb):
    app = pb.Application([])
    app._cmd_port("localhost")
    assert len(app.monitors) == 0
    assert "usage" in app.events[-1]
