"""Loopback UDP tests. These are simulations, not captured hardware replies."""
import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components/geeklink"))
from protocol import Client, GeeklinkError, INIT, LEARN, PREFIX, decode_learning, frame, validate_code


def code(kind="rf", body=b"\x03\x04\x05"):
    raw = PREFIX[kind] + body
    return (raw + bytes([sum(raw) % 256])).hex()


def learning_packet(kind="rf", body=b"\x03\x04\x05"):
    transmitted = bytes.fromhex(code(kind, body))
    delta = -113 if kind == "ir" else 31
    # Deliberately synthetic prefix: parser offsets are inferred from old scripts.
    return frame(b"\xa1\x00\x00\x00\x00" + body + bytes([(transmitted[-1] - delta) % 256]))


class FakeHub(asyncio.DatagramProtocol):
    def __init__(self):
        self.received = []
        self.silent = False
        self.learning_silent = False
        self.drop_commands = False

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        self.received.append(data[2:-2])
        if self.silent:
            return
        if self.drop_commands and data[2:-2] != INIT and data[2:-2] not in LEARN.values():
            return
        if data[2:-2] in LEARN.values():
            self.transport.sendto(frame(INIT), addr)
            if not self.learning_silent:
                kind = next(k for k, v in LEARN.items() if v == data[2:-2])
                self.transport.sendto(learning_packet(kind), addr)
        else:
            self.transport.sendto(frame(INIT), addr)


class CodecTests(unittest.TestCase):
    def test_ir_and_rf_roundtrip(self):
        for kind in ("ir", "rf"):
            self.assertEqual(decode_learning(learning_packet(kind), kind), code(kind))

    def test_checksum_wraparound(self):
        for kind in ("ir", "rf"):
            for value in range(256):
                body = bytes([value, 1, 2])
                self.assertEqual(decode_learning(learning_packet(kind, body), kind), code(kind, body))

    def test_invalid_inputs(self):
        for value in ("", "zz", "ffee", "00" * 10, code()[:-2] + "00"):
            with self.assertRaises(GeeklinkError):
                validate_code(value)

    def test_invalid_learning_frame(self):
        for value in (b"", frame(INIT), b"xx" + learning_packet()[2:], learning_packet()[:-1]):
            with self.assertRaises(GeeklinkError):
                decode_learning(value, "rf")


class UDPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.transport, self.server = await asyncio.get_running_loop().create_datagram_endpoint(
            FakeHub, local_addr=("127.0.0.1", 0))
        self.client = Client("127.0.0.1", self.transport.get_extra_info("sockname")[1], timeout=0.05, delay=0.001)

    async def asyncTearDown(self):
        self.client.close()
        self.transport.close()
        await asyncio.sleep(0)

    async def test_probe_and_send(self):
        await self.client.probe()
        await self.client.send(code())
        self.assertEqual(self.server.received, [INIT, INIT, bytes.fromhex(code())])
        self.assertFalse(self.client._sockets)

    async def test_learning_skips_short_ack(self):
        for kind in ("ir", "rf"):
            self.assertEqual(await self.client.learn(kind), code(kind))

    async def test_send_timeout_does_not_poison_queue(self):
        self.server.silent = True
        with self.assertRaises(GeeklinkError):
            await self.client.send(code())
        self.server.silent = False
        await self.client.send(code())
        self.assertFalse(self.client.lock.locked())

    async def test_concurrent_commands_are_serialized(self):
        await asyncio.gather(self.client.send(code()), self.client.send(code("ir")))
        self.assertEqual(self.server.received, [INIT, bytes.fromhex(code()), INIT, bytes.fromhex(code("ir"))])

    async def test_cancel_learning_releases_socket_and_lock(self):
        self.server.learning_silent = True
        task = asyncio.create_task(self.client.learn("rf"))
        for _ in range(100):
            if LEARN["rf"] in self.server.received:
                break
            await asyncio.sleep(0.001)
        self.assertIn(LEARN["rf"], self.server.received)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.client._sockets)
        await self.client.send(code())

    async def test_send_waits_for_learning(self):
        await asyncio.gather(self.client.learn("rf"), self.client.send(code()))
        self.assertEqual(self.server.received, [INIT, LEARN["rf"], INIT, bytes.fromhex(code())])

    async def test_reject_bad_code_before_sending(self):
        with self.assertRaises(GeeklinkError):
            await self.client.send("not hex")
        self.assertEqual(self.server.received, [])

    async def new_hub(self):
        transport, server = await asyncio.get_running_loop().create_datagram_endpoint(
            FakeHub, local_addr=("127.0.0.2", self.client.port))
        self.addAsyncCleanup(self.close_transport, transport)
        return server

    async def close_transport(self, transport):
        transport.close()
        await asyncio.sleep(0)

    async def test_changed_ip_recovers_before_sending_once(self):
        new = await self.new_hub()
        self.server.silent = True
        self.client.auto_discover = True
        changes = []
        self.client.on_host_changed = lambda old, new: changes.append((old,new))
        with patch("protocol.discover", AsyncMock(return_value=["127.0.0.2"])) as discovery:
            await asyncio.gather(self.client.send(code()), self.client.send(code("ir")))
        discovery.assert_awaited_once()
        self.assertEqual(self.client.host,"127.0.0.2")
        self.assertEqual(changes,[("127.0.0.1","127.0.0.2")])
        self.assertEqual(new.received,[INIT,bytes.fromhex(code()),INIT,bytes.fromhex(code("ir"))])
        self.assertEqual(self.server.received,[INIT])

    async def test_lost_ack_never_replays_command(self):
        new = await self.new_hub()
        self.server.drop_commands = True
        self.client.auto_discover = True
        with patch("protocol.discover", AsyncMock(return_value=["127.0.0.2"])):
            with self.assertRaises(GeeklinkError):
                await self.client.send(code())
        self.assertEqual(new.received,[INIT])
        self.assertEqual(self.server.received,[INIT,bytes.fromhex(code())])
        self.assertEqual(self.client.host,"127.0.0.2")
        await self.client.send(code("ir"))
        self.assertEqual(new.received,[INIT,INIT,bytes.fromhex(code("ir"))])

    async def test_unsuccessful_discovery_keeps_old_address(self):
        self.client.auto_discover = True
        self.server.silent = True
        for hosts in ([],["127.0.0.1","127.0.0.2"],["127.0.0.2"]):
            with patch("protocol.discover", AsyncMock(return_value=hosts)):
                with self.assertRaises(GeeklinkError):
                    await self.client.send(code())
            self.assertEqual(self.client.host,"127.0.0.1")
            self.assertFalse(self.client._sockets)

    async def test_learning_recovers_before_entering_learning_mode(self):
        new = await self.new_hub()
        self.server.silent = True
        self.client.auto_discover = True
        with patch("protocol.discover", AsyncMock(return_value=["127.0.0.2"])):
            self.assertEqual(await self.client.learn("ir"),code("ir"))
        self.assertEqual(new.received,[INIT,LEARN["ir"]])


if __name__ == "__main__":
    unittest.main()
