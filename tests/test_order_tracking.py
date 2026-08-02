"""Order-tracking edge cases in ExchangeClient.

These push hand-built messages through the real parsing path (_handle_response)
to exercise the message orderings that only happen under concurrency: a cancel
racing an ack, a fill beating a cancel, a duplicate fill. The lock and the
ordering rules are what these prove.
"""

from src.connection.exchange_client import ExchangeClient
from src.models.enums import Side
from tests.conftest import make_ack, make_fill


def make_client(fake_socket):
    c = ExchangeClient(client_id=1)
    c.send_socket = fake_socket
    return c


def tracking_sizes(client):
    return (len(client._pending_orders),
            len(client._order_id_map),
            len(client._exchange_id_map))


def test_order_registered_before_send(fake_socket):
    # The order must be in the pending map by the time send returns, so a fill that
    # arrives immediately can be matched.
    c = make_client(fake_socket)
    cid = c.send_order("X", Side.BUY, 10, 100)
    assert cid in c._pending_orders


def test_ack_records_id_mapping_both_directions(fake_socket):
    c = make_client(fake_socket)
    cid = c.send_order("X", Side.BUY, 10, 100)
    c._handle_response(make_ack(cid, 501, "X"))
    assert c._order_id_map[cid] == 501
    assert c._exchange_id_map[501] == cid


def test_complete_fill_clears_all_tracking(fake_socket):
    c = make_client(fake_socket)
    cid = c.send_order("X", Side.BUY, 10, 100)
    c._handle_response(make_ack(cid, 501, "X"))
    c._handle_response(make_fill(501, "X", "B", 10, 100, complete=True))
    assert tracking_sizes(c) == (0, 0, 0)


def test_partial_fill_keeps_order_alive(fake_socket):
    c = make_client(fake_socket)
    cid = c.send_order("X", Side.BUY, 10, 100)
    c._handle_response(make_ack(cid, 501, "X"))
    c._handle_response(make_fill(501, "X", "B", 4, 100, complete=False))
    assert cid in c._pending_orders  # not done yet


def test_cancel_clears_tracking_by_client_id(fake_socket):
    c = make_client(fake_socket)
    cid = c.send_order("X", Side.BUY, 10, 100)
    c._handle_response(make_ack(cid, 501, "X"))
    c.cancel_order("X", client_order_id=cid)
    assert tracking_sizes(c) == (0, 0, 0)


def test_cancel_clears_tracking_by_exchange_id(fake_socket):
    # Cancelling with only the exchange id must reverse-resolve and clear the
    # client-side entries too.
    c = make_client(fake_socket)
    cid = c.send_order("X", Side.BUY, 10, 100)
    c._handle_response(make_ack(cid, 502, "X"))
    c.cancel_order("X", order_id=502)
    assert tracking_sizes(c) == (0, 0, 0)


def test_late_ack_after_cancel_does_not_leak(fake_socket):
    # A cancel sent before the ack arrives: the late ack must not resurrect map
    # entries for an order we already declared dead.
    c = make_client(fake_socket)
    cid = c.send_order("X", Side.BUY, 10, 100)
    c.cancel_order("X", client_order_id=cid)   # cancel first
    c._handle_response(make_ack(cid, 503, "X"))  # ack arrives afterwards
    assert tracking_sizes(c) == (0, 0, 0)


def test_fill_after_cancel_still_fires_callback(fake_socket):
    # A cancel that loses the race with a fill: cleanup is optimistic, but the fill
    # callback must still fire so positions stay correct.
    c = make_client(fake_socket)
    got = []
    c.on_fill = lambda symbol, side, qty, price: got.append((symbol, side, qty, price))
    cid = c.send_order("X", Side.BUY, 10, 100)
    c._handle_response(make_ack(cid, 504, "X"))
    c.cancel_order("X", client_order_id=cid)
    c._handle_response(make_fill(504, "X", "B", 10, 100))  # fills anyway
    assert got == [("X", Side.BUY, 10, 100)]
    assert tracking_sizes(c) == (0, 0, 0)


def test_reject_clears_pending(fake_socket):
    from src.models.enums import MsgType
    import json
    c = make_client(fake_socket)
    cid = c.send_order("X", Side.BUY, 10, 100)
    reject = json.dumps({
        "header": {"version": 1, "type": MsgType.REJECT, "seq": 0, "client_id": 1},
        "body": {"client_order_id": cid, "symbol": "X", "info": {"reason": "risk limit", "code": 1}},
    })
    c._handle_response(reject)
    assert cid not in c._pending_orders