import zmq
import threading
import time

from ..models.enums import OrdType, TimeInForce, MsgType
from ..models.messages import Envelope, MessageHeader, NewOrderRequest, CancelRequest


class ExchangeClient:
    """ZeroMQ connection to the exchange.
    Orders and cancels go out on a PUSH socket (5555), acks/rejects/fills come
    back on a PULL socket (5556) handled by a background listener thread. The
    id counters and order maps are shared between both threads, so they are
    only touched while holding self._lock.
    """

    def __init__(self, client_id, host="localhost", send_port=5555, recv_port=5556):
        self.client_id = client_id
        self.host = host
        self.send_port = send_port
        self.recv_port = recv_port

        self.context = None
        self.send_socket = None
        self.recv_socket = None

        self._running = False
        self._listener_thread = None

        # optional callback fn(symbol, side, qty, price), set by the owning bot
        self.on_fill = None

        self._lock = threading.Lock()
        # zmq sockets aren't thread-safe. Normally only the main thread sends,
        # but a fill handler can send orders from the listener thread, so all
        # writes to send_socket go through this lock.
        self._send_lock = threading.Lock()
        self._next_order_id = 1
        self._next_seq = 1
        self._pending_orders = {}   # client_order_id -> order info
        self._order_id_map = {}     # client_order_id -> exchange order_id
        self._exchange_id_map = {}  # exchange order_id -> client_order_id

    def connect(self):
        self.context = zmq.Context()

        # LINGER=0: drop queued messages on close instead of blocking term()
        # forever if the exchange is down
        self.send_socket = self.context.socket(zmq.PUSH)
        self.send_socket.setsockopt(zmq.LINGER, 0)
        self.send_socket.connect(f"tcp://{self.host}:{self.send_port}")

        self.recv_socket = self.context.socket(zmq.PULL)
        self.recv_socket.setsockopt(zmq.LINGER, 0)
        self.recv_socket.connect(f"tcp://{self.host}:{self.recv_port}")

    def disconnect(self):
        self.stop_listening()

        # closing a socket while another thread is polling it can crash libzmq,
        # so if the listener didn't exit in time, leave cleanup to the process
        if self._listener_thread and self._listener_thread.is_alive():
            print("[WARN] listener still running, skipping socket cleanup")
            return

        if self.send_socket:
            self.send_socket.close()
        if self.recv_socket:
            self.recv_socket.close()
        if self.context:
            self.context.term()

    def send_order(self, symbol, side, qty, price, ord_type=OrdType.LIMIT, tif=TimeInForce.DAY):
        """Send a new order to the exchange, returns the client_order_id."""
        # Register the order before it hits the wire. A fast fill can arrive on
        # the listener thread before send_string() even returns.
        with self._lock:
            client_order_id = self._next_order_id
            self._next_order_id += 1
            seq = self._next_seq
            self._next_seq += 1
            self._pending_orders[client_order_id] = {
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "price": price,
                "sent_time": time.time(),
            }

        header = MessageHeader(version=1, type=MsgType.NEW_ORDER, seq=seq, client_id=self.client_id)
        body = NewOrderRequest(
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            ord_type=ord_type,
            qty=qty,
            limit_price=price,
            tif=tif,
        )

        try:
            with self._send_lock:
                self.send_socket.send_string(Envelope(header=header, body=body).to_json())
        except Exception:
            # roll back so we don't track an order that never went out
            with self._lock:
                self._pending_orders.pop(client_order_id, None)
            raise

        return client_order_id

    def cancel_order(self, symbol, order_id=None, client_order_id=None):
        """Cancel an order by exchange order_id or by our client_order_id."""
        with self._lock:
            # resolve whichever id we weren't given
            if order_id is None and client_order_id is not None:
                order_id = self._order_id_map.get(client_order_id, 0)
            elif client_order_id is None and order_id is not None:
                client_order_id = self._exchange_id_map.get(order_id)

            # drop the order from tracking now rather than waiting on a
            # confirmation. If the cancel loses the race with a fill, the fill
            # handler still fires the callback, so positions stay correct.
            if client_order_id is not None:
                self._pending_orders.pop(client_order_id, None)
                self._order_id_map.pop(client_order_id, None)
            if order_id:
                self._exchange_id_map.pop(order_id, None)

            seq = self._next_seq
            self._next_seq += 1

        header = MessageHeader(version=1, type=MsgType.CANCEL, seq=seq, client_id=self.client_id)
        body = CancelRequest(
            symbol=symbol,
            order_id=order_id or 0,
            client_order_id=client_order_id or 0,
        )
        with self._send_lock:
            self.send_socket.send_string(Envelope(header=header, body=body).to_json())

    def start_listening(self):
        if self._running:
            return
        self._running = True
        self._listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._listener_thread.start()

    def stop_listening(self):
        self._running = False
        if self._listener_thread:
            self._listener_thread.join(timeout=1.0)

    def _listen_loop(self):
        while self._running:
            try:
                if self.recv_socket.poll(timeout=100):
                    self._handle_response(self.recv_socket.recv_string())
            except Exception as e:
                # one bad message shouldn't kill the listener
                if self._running:
                    print(f"[ERROR] listener: {e}")

    def _handle_response(self, json_string):
        envelope = Envelope.from_json(json_string)
        if envelope.header.type == MsgType.ACK:
            self._handle_ack(envelope.body)
        elif envelope.header.type == MsgType.REJECT:
            self._handle_reject(envelope.body)
        elif envelope.header.type == MsgType.FILL:
            self._handle_fill(envelope.body)

    def _handle_ack(self, ack):
        with self._lock:
            # ignore acks for orders we already canceled locally, otherwise a
            # cancel sent before the ack arrives would leak map entries
            if ack.client_order_id in self._pending_orders:
                self._order_id_map[ack.client_order_id] = ack.order_id
                self._exchange_id_map[ack.order_id] = ack.client_order_id
        print(f"ACK: {ack.symbol} | order {ack.client_order_id} -> exchange id {ack.order_id}")

    def _handle_reject(self, reject):
        with self._lock:
            self._pending_orders.pop(reject.client_order_id, None)
        print(f"REJECT: {reject.symbol} | {reject.info.reason}")

    def _handle_fill(self, fill):
        with self._lock:
            client_order_id = self._exchange_id_map.get(fill.order_id)
            if fill.complete and client_order_id is not None:
                self._pending_orders.pop(client_order_id, None)
                self._order_id_map.pop(client_order_id, None)
                self._exchange_id_map.pop(fill.order_id, None)
        print(f"FILL: {fill.symbol} | {fill.fill_qty} @ {fill.fill_price} | complete={fill.complete}")

        # notify the bot outside the lock, since its handler may turn around
        # and send orders that need the lock again
        if self.on_fill:
            self.on_fill(fill.symbol, fill.side, fill.fill_qty, fill.fill_price)

    def get_pending_orders(self):
        with self._lock:
            return dict(self._pending_orders)

    def get_exchange_order_id(self, client_order_id):
        with self._lock:
            return self._order_id_map.get(client_order_id)
