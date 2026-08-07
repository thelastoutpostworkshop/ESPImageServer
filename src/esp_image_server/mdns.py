"""Advertise ESPImageServer as espimageserver.local on the local network."""

from __future__ import annotations

import socket

from zeroconf import ServiceInfo, Zeroconf


class MdnsAdvertiser:
    def __init__(self, port: int) -> None:
        self._port = port
        self._zeroconf: Zeroconf | None = None
        self._service: ServiceInfo | None = None

    def start(self) -> None:
        addresses = {
            address
            for address in socket.gethostbyname_ex(socket.gethostname())[2]
            if not address.startswith(("127.", "169.254."))
        }
        if not addresses:
            return
        hostname = "espimageserver.local."
        self._service = ServiceInfo(
            "_http._tcp.local.",
            "ESPImageServer._http._tcp.local.",
            addresses=[socket.inet_aton(address) for address in addresses],
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
