"""İstemci IP çözümleyici (ADR-0002): güvenilir vekil, XFF zinciri, IPv6 ve geçersiz girdiler."""

from __future__ import annotations

import ipaddress

import pytest

from app.core.clientip import UNKNOWN_IP, ClientIpResolver

NETS = [ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12")]


def cidr(*, hops: int = 0) -> ClientIpResolver:
    return ClientIpResolver(NETS, hops)


def test_no_trust_configured_uses_peer_and_ignores_header() -> None:
    resolver = ClientIpResolver()
    assert resolver.trusts_proxy is False
    assert resolver.resolve("203.0.113.9", "6.6.6.6") == "203.0.113.9"
    assert resolver.resolve("203.0.113.9", None) == "203.0.113.9"


def test_peer_outside_trusted_cidrs_ignores_header() -> None:
    assert cidr().resolve("203.0.113.9", "6.6.6.6, 10.0.0.1") == "203.0.113.9"


def test_trusted_peer_without_header_is_the_client() -> None:
    assert cidr().resolve("10.0.0.2", None) == "10.0.0.2"
    assert cidr().resolve("10.0.0.2", "") == "10.0.0.2"


def test_rightmost_untrusted_address_is_the_client() -> None:
    # Soldaki 6.6.6.6 istemcinin yazdığı sahte değerdir; zincirde güvenilmeyen ilk sağ adres esastır.
    assert cidr().resolve("10.0.0.2", "6.6.6.6, 203.0.113.9") == "203.0.113.9"
    assert cidr().resolve("10.0.0.2", "6.6.6.6, 203.0.113.9, 10.0.0.1") == "203.0.113.9"
    assert cidr().resolve("172.20.1.1", "203.0.113.9, 172.16.5.5, 10.9.9.9") == "203.0.113.9"


def test_all_trusted_chain_falls_back_to_leftmost() -> None:
    assert cidr().resolve("10.0.0.2", "10.0.0.7, 10.0.0.1") == "10.0.0.7"


def test_hops_without_cidrs_skips_exactly_n_hops_from_the_right() -> None:
    one = ClientIpResolver(trusted_hops=1)
    assert one.trusts_proxy is True
    assert one.resolve("172.18.0.5", "203.0.113.9") == "203.0.113.9"
    assert one.resolve("172.18.0.5", "6.6.6.6, 203.0.113.9") == "203.0.113.9"
    two = ClientIpResolver(trusted_hops=2)
    assert two.resolve("172.18.0.5", "6.6.6.6, 203.0.113.9, 104.16.0.1") == "203.0.113.9"
    # Zincir hop sayısından kısaysa en soldaki (en az güvenilen değil, elde olan en uzak) adres
    assert two.resolve("172.18.0.5", "203.0.113.9") == "203.0.113.9"


def test_hops_and_cidrs_combine() -> None:
    resolver = ClientIpResolver(NETS, trusted_hops=1)
    assert resolver.resolve("10.0.0.2", "203.0.113.9, 10.0.0.1") == "203.0.113.9"
    assert resolver.resolve("198.51.100.1", "203.0.113.9") == "198.51.100.1"  # eş güvenilir değil


def test_garbage_entries_cut_off_everything_to_their_left() -> None:
    assert cidr().resolve("10.0.0.2", "garbage, 203.0.113.9") == "203.0.113.9"
    assert cidr().resolve("10.0.0.2", "203.0.113.9, garbage") == "10.0.0.2"
    assert cidr().resolve("10.0.0.2", ",,  ,") == "10.0.0.2"
    assert cidr().resolve("10.0.0.2", "[::1") == "10.0.0.2"


def test_ports_brackets_and_mapped_addresses_are_normalized() -> None:
    assert cidr().resolve("10.0.0.2", "203.0.113.9:4711") == "203.0.113.9"
    assert cidr().resolve("10.0.0.2", "[2001:db8::7]:443") == "2001:db8::/64"
    assert cidr().resolve("10.0.0.2", "::ffff:203.0.113.9") == "203.0.113.9"


def test_ipv6_bucketed_by_slash_64() -> None:
    resolver = ClientIpResolver(trusted_hops=1)
    a = resolver.resolve("10.0.0.2", "2001:db8:1:1::1")
    b = resolver.resolve("10.0.0.2", "2001:db8:1:1:aaaa:bbbb:cccc:dddd")
    c = resolver.resolve("10.0.0.2", "2001:db8:1:2::1")
    assert a == b == "2001:db8:1:1::/64" and c != a


def test_ipv6_trusted_networks_match_by_family() -> None:
    resolver = ClientIpResolver([ipaddress.ip_network("fd00::/8")])
    assert resolver.resolve("fd00::5", "203.0.113.9") == "203.0.113.9"
    assert resolver.resolve("10.0.0.2", "203.0.113.9") == "10.0.0.2"  # IPv4 eş, IPv6 ağında değil


@pytest.mark.parametrize("peer", ["testclient", "unix-socket"])
def test_non_ip_peer_is_returned_verbatim(peer: str) -> None:
    assert cidr().resolve(peer, "203.0.113.9") == peer


def test_missing_peer_is_unknown() -> None:
    assert ClientIpResolver().resolve(None, "1.2.3.4") == UNKNOWN_IP
