import pytest

class TestParseTargetUnit:
    def test_parse_target_basic(self, pb):
        assert pb.parse_target("localhost:80") == ("localhost", "80")
        assert pb.parse_target("example.com:http") == ("example.com", "http")
        assert pb.parse_target("127.0.0.1:443") == ("127.0.0.1", "443")

    def test_parse_target_no_port(self, pb):
        assert pb.parse_target("localhost") == ("localhost", None)
        assert pb.parse_target("127.0.0.1") == ("127.0.0.1", None)

    def test_parse_target_ipv6_with_port(self, pb):
        assert pb.parse_target("[2001:db8::1]:80") == ("2001:db8::1", "80")
        assert pb.parse_target("[::1]:443") == ("::1", "443")
        assert pb.parse_target("[::1]:https") == ("::1", "https")

    def test_parse_target_ipv6_no_port(self, pb):
        assert pb.parse_target("2001:db8::1") == ("2001:db8::1", None)
        assert pb.parse_target("::1") == ("::1", None)
        assert pb.parse_target("[2001:db8::1]") == ("2001:db8::1", None)

    def test_parse_target_empty(self, pb):
        assert pb.parse_target("") == ("", None)

    def test_port_monitor_display_name_dns_off(self, pb):
        monitor = pb.PortMonitor("localhost", "080")
        assert monitor.get_display_name(dns_mode="off") == "localhost:080"

        monitor2 = pb.PortMonitor("example.com", "80")
        assert monitor2.get_display_name(dns_mode="off") == "example.com:80"
