"""Async UDP transport, derived from burakalakus/geeklink-python.

No Home Assistant imports, no threads, no retransmission of physical commands.
The learn-response conversion retains the original script's byte offsets and
checksum adjustment; this reverse-engineered dialect needs hardware testing.
"""
import asyncio
import ipaddress
import logging
import socket
from contextlib import asynccontextmanager

SOF = bytes.fromhex("ffee")
EOF = bytes.fromhex("effe")
INIT = bytes.fromhex("11000011")
LEARN = {"ir": bytes.fromhex("b111000000050000000020e7"),
         "rf": bytes.fromhex("b310000000050000000020e8")}
PREFIX = {"ir": bytes.fromhex("d1710000000000"),
          "rf": bytes.fromhex("d3110000000000")}
_LOGGER = logging.getLogger(__name__)


class GeeklinkError(Exception):
    """Communication or protocol failure."""


def ipv4(value):
    address = ipaddress.IPv4Address(value)
    if address.is_multicast or address.is_unspecified or str(address) == "255.255.255.255":
        raise ValueError("Enter a unicast IPv4 address")
    return str(address)


def frame(payload):
    return SOF + payload + EOF


def unframe(data):
    if len(data) < 8 or not data.startswith(SOF) or not data.endswith(EOF):
        raise GeeklinkError("Invalid Geeklink packet framing")
    return data[2:-2]


def validate_code(code):
    try:
        raw = bytes.fromhex(code)
    except (ValueError, TypeError) as err:
        raise GeeklinkError("Command must be a hexadecimal string") from err
    if len(raw) < 10 or len(raw) > 4092 or raw[:7] not in PREFIX.values():
        raise GeeklinkError("Unsupported or truncated IR/RF command")
    if sum(raw[:-1]) % 256 != raw[-1]:
        raise GeeklinkError("Command checksum does not match")
    return raw.hex()


def decode_learning(data, kind):
    if kind not in LEARN:
        raise GeeklinkError("Only ir and rf are supported")
    unframe(data)
    if len(data) < 13:
        raise GeeklinkError("Learning reply has no code")
    # Original scripts: strip 7 leading bytes, framing trailer, checksum;
    # prepend transmit header and adjust checksum modulo 256.
    checksum = (data[-3] + (-113 if kind == "ir" else 31)) % 256
    return validate_code((PREFIX[kind] + data[7:-3] + bytes([checksum])).hex())


class Client:
    def __init__(self, host, port=9001, timeout=5, delay=0.5):
        self.host = ipv4(host)
        self.port = port
        self.timeout = timeout
        self.delay = delay
        self.lock = asyncio.Lock()
        self._sockets = set()
        self._closed = False
        self.auto_discover = False
        self.on_host_changed = None

    def close(self):
        self._closed = True
        for sock in list(self._sockets):
            sock.close()

    @asynccontextmanager
    async def session(self):
        async with self.lock:
            if self._closed:
                raise GeeklinkError("Home Assistant is stopping")
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
            self._sockets.add(sock)
            try:
                yield sock
            except (TimeoutError, OSError) as err:
                raise GeeklinkError("No usable response from Geeklink; check IP/network or retry learning") from err
            finally:
                self._sockets.discard(sock)
                sock.close()
                # Keep the lock during the inter-command quiet period.
                if not self._closed:
                    await asyncio.sleep(self.delay)

    async def _send(self, sock, payload, address):
        await asyncio.get_running_loop().sock_sendto(sock, frame(payload), address)

    async def _receive(self, sock, timeout, expected):
        async with asyncio.timeout(timeout):
            while True:
                data, sender = await asyncio.get_running_loop().sock_recvfrom(sock, 4096)
                if sender != expected:
                    continue
                try:
                    unframe(data)
                except GeeklinkError:
                    continue
                return data

    async def _hello(self, sock):
        address = (self.host, self.port)
        try:
            await self._send(sock, INIT, address)
            await self._receive(sock, self.timeout, address)
            return address
        except (TimeoutError, OSError):
            if not self.auto_discover:
                raise
            # Only handshake packets have been sent: recovering here cannot
            # replay an appliance command. The session lock covers discovery.
            return await self._rediscover(sock)

    async def _rediscover(self, sock):
        hosts = await discover(port=self.port)
        if len(hosts) != 1:
            raise GeeklinkError("Geeklink is unreachable and discovery did not find exactly one hub; retry after the hub finishes booting")
        host = ipv4(hosts[0])
        address = (host, self.port)
        # Confirm the broadcast responder accepts a unicast handshake before
        # changing or persisting the address. No MAC address is consulted.
        await self._send(sock, INIT, address)
        await self._receive(sock, self.timeout, address)
        if host != self.host:
            old_host = self.host
            self.host = host
            if self.on_host_changed is not None:
                self.on_host_changed(old_host, host)
            _LOGGER.info("Geeklink rediscovered at %s (previous address %s)", host, old_host)
        return address

    async def probe(self):
        async with self.session() as sock:
            await self._hello(sock)

    async def send(self, code):
        payload = bytes.fromhex(validate_code(code))
        async with self.session() as sock:
            address = await self._hello(sock)
            try:
                await self._send(sock, payload, address)
                await self._receive(sock, self.timeout, address)
            except (TimeoutError, OSError):
                # The physical command may have executed. Find the new IP for
                # later calls, but never retransmit this command automatically.
                if self.auto_discover:
                    try:
                        await self._rediscover(sock)
                    except (GeeklinkError, TimeoutError, OSError):
                        pass
                raise
            # Reply framing is verified. Appliance execution is not observable.

    async def learn(self, kind, timeout=30):
        if kind not in LEARN or not 5 <= timeout <= 120:
            raise GeeklinkError("Use ir/rf and a learning timeout of 5–120 seconds")
        async with self.session() as sock:
            address = await self._hello(sock)
            await self._send(sock, LEARN[kind], address)
            async with asyncio.timeout(timeout):
                while True:
                    data = await self._receive(sock, timeout, address)
                    # Short acknowledgements may precede the learning payload.
                    if len(data) < 13:
                        continue
                    return decode_learning(data, kind)


async def discover(timeout=2, port=9001):
    """Return all framed responders; never silently choose among multiple hubs."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    found = set()
    loop = asyncio.get_running_loop()
    try:
        await loop.sock_sendto(sock, frame(INIT), ("255.255.255.255", port))
        try:
            async with asyncio.timeout(timeout):
                while True:
                    data, sender = await loop.sock_recvfrom(sock, 4096)
                    try:
                        unframe(data)
                    except GeeklinkError:
                        continue
                    if sender[1] == port:
                        found.add(sender[0])
        except TimeoutError:
            pass
    except OSError as err:
        raise GeeklinkError("Discovery failed; enter the hub IPv4 address") from err
    finally:
        sock.close()
    return sorted(found)
