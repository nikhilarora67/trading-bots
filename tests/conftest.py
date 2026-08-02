import json
import threading
import time

import pytest
import zmq

from src.models.enums import MsgType


class FakeSocket:
    """Stand-in for the PUSH socket. Records every message the client sends so a
    test can assert on order flow without any network."""

    def __init__(self):
        self.messages = []

    def send_string(self, s):
        self.messages.append(json.loads(s))

    def orders(self):
        return [m["body"] for m in self.messages if m["header"]["type"] == MsgType.NEW_ORDER]

    def cancels(self):
        return [m["body"] for m in self.messages if m["header"]["type"] == MsgType.CANCEL]


@pytest.fixture
def fake_socket():
    return FakeSocket()


def make_ack(client_order_id, order_id, symbol):
    return json.dumps({
        "header": {"version": 1, "type": MsgType.ACK, "seq": 0, "client_id": 0},
        "body": {"client_order_id": client_order_id, "order_id": order_id, "symbol": symbol},
    })


def make_fill(order_id, symbol, side, qty, price, complete=True):
    return json.dumps({
        "header": {"version": 1, "type": MsgType.FILL, "seq": 0, "client_id": 0},
        "body": {"order_id": order_id, "symbol": symbol, "side": side,
                 "fill_qty": qty, "fill_price": price, "complete": complete},
    })


class FakeExchange:
    """A real ZeroMQ endpoint that acks and fills every order it receives, so the
    client runs its actual send and listener paths over real sockets. Runs on its
    own thread; call stop() to shut it down."""

    def __init__(self, send_port, recv_port, fill=True):
        self._send_port = send_port
        self._recv_port = recv_port
        self._fill = fill
        self._running = False
        self._thread = None
        self._ready = threading.Event()
        self.received = 0

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self):
        ctx = zmq.Context()
        pull = ctx.socket(zmq.PULL)
        pull.setsockopt(zmq.LINGER, 0)
        pull.bind(f"tcp://*:{self._send_port}")
        push = ctx.socket(zmq.PUSH)
        push.setsockopt(zmq.LINGER, 0)
        push.bind(f"tcp://*:{self._recv_port}")
        self._ready.set()

        next_id = 10_000
        while self._running:
            if not pull.poll(timeout=100):
                continue
            msg = json.loads(pull.recv_string())
            if msg["header"]["type"] != MsgType.NEW_ORDER:
                continue  # cancels are accepted silently, like a real fire-and-forget cancel
            body = msg["body"]
            next_id += 1
            self.received += 1
            push.send_string(make_ack(body["client_order_id"], next_id, body["symbol"]))
            if self._fill:
                push.send_string(make_fill(next_id, body["symbol"], body["side"],
                                           body["qty"], body["limit_price"]))

        pull.close()
        push.close()
        ctx.term()


_next_port = 5600


@pytest.fixture
def exchange():
    """Yields a started FakeExchange on a fresh port pair, torn down after the test."""
    global _next_port
    send_port, recv_port = _next_port, _next_port + 1
    _next_port += 2
    ex = FakeExchange(send_port, recv_port)
    ex.start()
    ex.send_port = send_port
    ex.recv_port = recv_port
    yield ex
    ex.stop()


def wait_until(predicate, timeout=5.0, interval=0.02):
    """Poll predicate() until it's true or the timeout elapses. Returns the final value."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()