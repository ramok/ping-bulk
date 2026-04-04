import pytest
import socket
from unittest.mock import patch, MagicMock

class TestPortMonitorUnit:
    def test_port_monitor_init_numeric(self, pb):
        monitor = pb.PortMonitor("localhost", "80")
        assert monitor.port == "80"
        assert monitor.port_num == 80
        assert monitor.port_name in ("http", "80")

    def test_port_monitor_init_name(self, pb):
        monitor = pb.PortMonitor("localhost", "http")
        assert monitor.port == "http"
        assert monitor.port_num == 80
        assert monitor.port_name == "http"

    def test_port_monitor_init_invalid(self, pb):
        monitor = pb.PortMonitor("localhost", "invalid_port_name")
        assert monitor.port == "invalid_port_name"
        assert monitor.port_num is None
        assert monitor.port_name == "invalid_port_name"

    def test_resolve_port_custom_port_to_service(self, pb):
        port_map = {8080: "myapp"}
        monitor = pb.PortMonitor("localhost", "8080", port_map=port_map)
        assert monitor.port_num == 8080
        assert monitor.port_name == "myapp"

    def test_resolve_port_custom_service_to_port(self, pb):
        port_map = {"myservice": 9999}
        monitor = pb.PortMonitor("localhost", "myservice", port_map=port_map)
        assert monitor.port_num == 9999
        assert monitor.port_name == "myservice"

    def test_resolve_port_standard_service(self, pb):
        monitor = pb.PortMonitor("localhost", "http")
        assert monitor.port_num == 80
        assert monitor.port_name == "http"

    def test_resolve_port_standard_port(self, pb):
        monitor = pb.PortMonitor("localhost", "80")
        assert monitor.port_num == 80
        assert monitor.port_name == "http" # Usually, socket.getservbyport(80) is "http"

    def test_resolve_port_unknown_service(self, pb):
        monitor = pb.PortMonitor("localhost", "unknown_svc_xyz")
        assert monitor.port_num is None
        assert monitor.port_name == "unknown_svc_xyz"

    def test_resolve_port_unknown_port(self, pb):
        # Port 65534 is unlikely to have a service name
        monitor = pb.PortMonitor("localhost", "65534")
        assert monitor.port_num == 65534
        assert monitor.port_name == "65534"

    def test_resolve_port_edge_cases(self, pb):
        # Empty string
        monitor = pb.PortMonitor("localhost", "")
        assert monitor.port_num is None
        assert monitor.port_name == ""

        # Negative port (not valid but handled as unknown service initially then int parse fail, wait, "-1" -> ValueError or int)
        monitor = pb.PortMonitor("localhost", "-1")
        assert monitor.port_num == -1
        assert monitor.port_name == "-1" # socket.getservbyport(-1) raises OSError

    def test_port_monitor_get_display_name(self, pb):
        monitor = pb.PortMonitor("127.0.0.1", "80")
        monitor.resolved_hostname = "localhost"
        assert monitor.get_display_name('off') == "127.0.0.1:80"
        assert monitor.get_display_name('hostname') in ("localhost", "localhost:80", "localhost:http")
        assert monitor.get_display_name('ip') == "127.0.0.1:80"

    @patch('socket.create_connection')
    def test_port_monitor_ping_success(self, mock_create_connection, pb):
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
    def test_port_monitor_ping_fail(self, mock_create_connection, pb):
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

    def test_cmd_ping_port(self, pb):
        app = pb.Application([])
        app._cmd_ping("localhost:80")
        assert len(app.monitors) == 1
        assert isinstance(app.monitors[0], pb.PortMonitor)
        assert app.monitors[0].host == "localhost:80"
