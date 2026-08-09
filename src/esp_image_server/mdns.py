"""Advertise ESPImageServer as espimageserver.local on the local network."""

from __future__ import annotations

import socket

from zeroconf import ServiceInfo, Zeroconf


def active_lan_address() -> str | None:
    """Return the IPv4 address used by this PC's default network route.

    Windows hosts with WSL or Hyper-V often resolve their hostname to a virtual
    172.x address first. That address cannot be reached by a physical ESP32.
    A UDP connect selects the same adapter Windows would use for normal LAN or
    internet traffic without sending application data.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("1.1.1.1", 80))
            address = probe.getsockname()[0]
    except OSError:
        return None
    if address.startswith(("127.", "169.254.")):
        return None
    return address


class MdnsAdvertiser:
    def __init__(self, port: int) -> None:
        self._port = port
        self._zeroconf: Zeroconf | None = None
        self._service: ServiceInfo | None = None

    def start(self) -> None:
        address = active_lan_address()
        if address is None:
            return
        hostname = "espimageserver.local."
        self._service = ServiceInfo(
            "_http._tcp.local.",
            "ESPImageServer._http._tcp.local.",
            addresses=[socket.inet_aton(address)],
            port=self._port,
            properties={"path": "/"},
            server=hostname,
        )
        self._zeroconf = Zeroconf()
        self._zeroconf.register_service(self._service)

    def close(self) -> None:
        if self._zeroconf and self._service:
            self._zeroconf.unregister_service(self._service)
        if self._zeroconf:
            self._zeroconf.close()
