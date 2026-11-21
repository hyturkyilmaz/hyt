"""İstemci IP'sinin güvenilir vekil yapılandırmasıyla belirlenmesi (ADR-0002, denetim Y-01).

Kural: X-Forwarded-For yalnız güvenilir bir vekilden gelen bağlantıda okunur ve sağdan sola
yürünür; güvenilir vekil adresleri atlanır, ilk güvenilmeyen adres istemcidir. Sol taraftaki
değerleri istemci yazabildiği için hiçbir zaman esas alınmaz. Yapılandırma yoksa başlık yok sayılır.

Rate limit ve denetim kayıtları aynı çözümleyiciyi kullanır; böylece sahte başlıkla kova
değiştirilemez.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

# IPv6 istemcilerine genellikle bir /64 verilir; adres başına kova, saldırgana sınırsız kova
# verirdi. Bu yüzden IPv6 adresleri /64 önekine indirgenir.
_IPV6_BUCKET_PREFIX = 64
UNKNOWN_IP = "unknown"


def _parse_ip(raw: str) -> IPAddress | None:
    """Başlık girdisini IP'ye çevirir. Port ve köşeli parantezi ayıklar; geçersizse None."""
    value = raw.strip()
    if not value:
        return None
    if value.startswith("["):
        end = value.find("]")
        if end == -1:
            return None
        value = value[1:end]
    elif value.count(":") == 1:  # "1.2.3.4:5678"
        value = value.split(":", 1)[0]
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _bucket(address: IPAddress) -> str:
    """Kova anahtarı olarak kullanılan kanonik metin (IPv6 için /64 öneki)."""
    if isinstance(address, ipaddress.IPv6Address):
        network = ipaddress.ip_network((address, _IPV6_BUCKET_PREFIX), strict=False)
        return str(network)
    return str(address)


class ClientIpResolver:
    """Eş adres + X-Forwarded-For'dan istemci IP'sini çözer."""

    def __init__(self, trusted_cidrs: Sequence[IPNetwork] = (), trusted_hops: int = 0) -> None:
        self._cidrs = tuple(trusted_cidrs)
        self._hops = trusted_hops

    @property
    def trusts_proxy(self) -> bool:
        return bool(self._cidrs) or self._hops > 0

    def _is_trusted_network(self, address: IPAddress) -> bool:
        return any(address in network for network in self._cidrs if network.version == address.version)

    def resolve(self, peer: str | None, forwarded_for: str | None) -> str:
        """İstemci IP'sinin kova anahtarı. Eş adres IP değilse (ör. unix soket) olduğu gibi döner."""
        peer_ip = _parse_ip(peer) if peer else None
        if peer_ip is None:
            return peer or UNKNOWN_IP
        if not self.trusts_proxy or not forwarded_for:
            return _bucket(peer_ip)
        # Eş adres CIDR listesinde değilse (listede olması gerekirken) başlığa güvenilmez.
        if self._cidrs and not self._is_trusted_network(peer_ip):
            return _bucket(peer_ip)

        # Zincir: başlıktaki girdiler (soldan sağa) + bağlantının eş adresi.
        entries: list[IPAddress] = []
        for raw in forwarded_for.split(","):
            parsed = _parse_ip(raw)
            if parsed is None:
                # Geçersiz girdinin solundakilere güvenilemez: yalnız sağdakiler kalır.
                entries.clear()
            else:
                entries.append(parsed)
        chain = [*entries, peer_ip]

        remaining_hops = self._hops
        index = len(chain) - 1
        while index > 0:
            if remaining_hops > 0:
                remaining_hops -= 1
            elif not (self._cidrs and self._is_trusted_network(chain[index])):
                break
            index -= 1
        return _bucket(chain[index])
