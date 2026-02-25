import zmq
import threading
import time

from ..models.enums import OrdType, TimeInForce, MsgType
from ..models.messages import Envelope, MessageHeader, NewOrderRequest, CancelRequest


class ExchangeClient:
    """
    Handles connection to the C++ exchange.
    """
    
    def __init__(self, client_id, host="localhost", send_port=5555, recv_port=5556):
        self.client_id = client_id
        self.host = host
        self.send_port = send_port
        self.recv_port = recv_port
        
        # ZeroMQ 
        self.context = None
        self.send_socket = None
        self.recv_socket = None
        
        # Background listener
        self._running = False
        self._listener_thread = None
        
        # Auto-incrementing IDs
        self._next_order_id = 1
        self._next_seq = 1
        
        # Order tracking
        self._pending_orders = {}    # client_order_id -> order info
        self._order_id_map = {}      # client_order_id -> exchange's order_id
    
    
    # ==================== Connection ====================
    
    def connect(self):
        """Connect to the exchange."""
        self.context = zmq.Context()
        
        # Socket to send orders (port 5555)
        self.send_socket = self.context.socket(zmq.PUSH)
        self.send_socket.connect(f"tcp://{self.host}:{self.send_port}")
        
        # Socket to receive responses (port 5556)
        self.recv_socket = self.context.socket(zmq.PULL)
        self.recv_socket.connect(f"tcp://{self.host}:{self.recv_port}")
    
    
    def disconnect(self):
        """Disconnect from the exchange."""
        self.stop_listening()
        
        if self.send_socket:
            self.send_socket.close()
        if self.recv_socket:
            self.recv_socket.close()
        if self.context:
            self.context.term()
    
    
    # ==================== Sending ====================
    
    def send_order(self, symbol, side, qty, price, ord_type=OrdType.LIMIT, tif=TimeInForce.DAY):
        """Send an order to the exchange. Returns the client_order_id for tracking."""
        
        # Get next IDs
        client_order_id = self._next_order_id
        self._next_order_id += 1
        
        seq = self._next_seq
        self._next_seq += 1
        
        # Build message
        header = MessageHeader(
            version=1,
            type=MsgType.NEW_ORDER,
            seq=seq,
            client_id=self.client_id
        )
        
        body = NewOrderRequest(
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            ord_type=ord_type,
            qty=qty,
            limit_price=price,
            tif=tif
        )
        
        envelope = Envelope(header=header, body=body)
        
        # Send
        self.send_socket.send_string(envelope.to_json())
        
        # Track
        self._pending_orders[client_order_id] = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "sent_time": time.time()
        }
        
        return client_order_id
    
    
    def cancel_order(self, symbol, order_id=None, client_order_id=None):
        """Cancel an order. Provide either order_id (from Ack) or client_order_id."""
        
        # Look up exchange's order_id if needed
        if order_id is None and client_order_id is not None:
            order_id = self._order_id_map.get(client_order_id, 0)
        
        seq = self._next_seq
        self._next_seq += 1
        
        header = MessageHeader(
            version=1,
            type=MsgType.CANCEL,
            seq=seq,
            client_id=self.client_id
        )
        
        body = CancelRequest(
            symbol=symbol,
            order_id=order_id or 0,
            client_order_id=client_order_id or 0
        )
        
        envelope = Envelope(header=header, body=body)
        self.send_socket.send_string(envelope.to_json())
    
    
    # ==================== Receiving ====================
    
    def start_listening(self):
        """Start listening for responses in background."""
        self._running = True
        self._listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._listener_thread.start()
    
    
    def stop_listening(self):
        """Stop the background listener."""
        self._running = False
        if self._listener_thread:
            self._listener_thread.join(timeout=1.0)
    
    
    def _listen_loop(self):
        """Background loop - receives and handles messages from exchange."""
        while self._running:
            if self.recv_socket.poll(timeout=100):
                json_string = self.recv_socket.recv_string()
                self._handle_response(json_string)
    
    
    # ==================== Response Handlers ====================
    
    def _handle_response(self, json_string):
        """Route response to the right handler."""
        envelope = Envelope.from_json(json_string)
        
        if envelope.header.type == MsgType.ACK:
            self._handle_ack(envelope.body)
        elif envelope.header.type == MsgType.REJECT:
            self._handle_reject(envelope.body)
        elif envelope.header.type == MsgType.FILL:
            self._handle_fill(envelope.body)
    
    
    def _handle_ack(self, ack):
        """Order accepted - save the order_id mapping."""
        self._order_id_map[ack.client_order_id] = ack.order_id
        print(f"ACK: {ack.symbol} | My ID: {ack.client_order_id} -> Exchange ID: {ack.order_id}")
    
    
    def _handle_reject(self, reject):
        """Order rejected - remove from pending."""
        self._pending_orders.pop(reject.client_order_id, None)
        print(f"REJECT: {reject.symbol} | {reject.info.reason}")
    
    
    def _handle_fill(self, fill):
        """Order filled - update tracking."""
        # Find my order ID from exchange's order ID
        client_order_id = None
        for cid, eid in self._order_id_map.items():
            if eid == fill.order_id:
                client_order_id = cid
                break
        
        # If fully filled, remove from pending
        if fill.complete and client_order_id:
            self._pending_orders.pop(client_order_id, None)
        
        print(f"FILL: {fill.symbol} | {fill.fill_qty} @ {fill.fill_price} | Complete: {fill.complete}")
    
    
    # ==================== Utilities ====================
    
    def get_pending_orders(self):
        """Get all orders that haven't been fully filled."""
        return dict(self._pending_orders)
    
    
    def get_exchange_order_id(self, client_order_id):
        """Get the exchange's order ID for one of our orders."""
        return self._order_id_map.get(client_order_id)