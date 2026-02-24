import json
from dataclasses import dataclass
from typing import Union
from .enums import Side, OrdType, TimeInForce, MsgType

# All Message Structures to be sent over ZeroMQ are defined here

@dataclass
class MessageHeader:
    version: int
    type: MsgType
    seq: int
    client_id: int

    def to_dict(self):
        return{"version": self.version, "type": int(self.type), "seq": self.seq, "client_id": self.client_id}
    
    @classmethod
    def from_dict(cls, data):
        return cls(version=data["version"],
                   type = MsgType(data["type"]),
                   seq = data["seq"],
                   client_id = data["client_id"]
                   )


# --------------------------------- Bot sends this to Exchange --------------------------------------------------


@dataclass
class NewOrderRequest:
    client_order_id: int
    symbol: str
    side: Side
    ord_type: OrdType
    qty: int
    limit_price: int
    tif: TimeInForce

    def to_dict(self):
        return {"client_order_id": self.client_order_id, "symbol": self.symbol, "side": self.side.as_string(), "ord_type": self.ord_type.as_string(), "qty": self.qty, "limit_price": self.limit_price, "tif": self.tif.as_string()}



@dataclass
class CancelRequest:
    symbol: str
    order_id: int
    client_order_id: int

    def to_dict(self):
        return {"symbol": self.symbol, "order_id": self.order_id, "client_order_id": self.client_order_id}


# ---------------------------------- Exchange sends this to bot -----------------------------------------


@dataclass
class Ack:
    client_order_id: int
    order_id: int
    symbol: str

    @classmethod
    def from_dict(cls, data):
        return cls(client_order_id = data["client_order_id"],
                   order_id = data["order_id"],
                   symbol = data["symbol"]
                   )


@dataclass
class RejectInfo:
    reason: str
    code: int

    @classmethod
    def from_dict(cls, data):
        return cls(reason = data["reason"],
                   code = data["code"]
                   )


# Reject contains a RejectInfo with the rejection details
@dataclass
class Reject:
    client_order_id: int
    symbol: str
    info: RejectInfo

    @classmethod
    def from_dict(cls, data):
        return cls(client_order_id = data["client_order_id"],
                   symbol = data["symbol"],
                   info = RejectInfo.from_dict(data["info"])
                   )
    

@dataclass
class Fill:
    order_id: int
    symbol: str
    side: Side 
    fill_qty: int
    fill_price: int
    complete: bool

    @classmethod 
    def from_dict(cls, data):
        return cls(order_id = data["order_id"],
                   symbol = data["symbol"],
                   side = Side.parse(data["side"]),
                   fill_qty = data["fill_qty"],
                   fill_price = data["fill_price"],
                   complete = data["complete"])



# -------------------------------- Envelope ------------------------------------------------


@dataclass
class Envelope:
    """ This Class wraps header and body together and is what gets sent over the network """
    header: MessageHeader
    body: Union[NewOrderRequest, CancelRequest, Ack, Reject, Fill]

    def to_json(self):
        return json.dumps({"header": self.header.to_dict(),
                           "body": self.body.to_dict()
                           })
    
    @classmethod
    def from_json(cls, json_string):
        data = json.loads(json_string)
        header = MessageHeader.from_dict(data["header"])
        body_data = data["body"]

        if header.type == MsgType.ACK:
            body = Ack.from_dict(body_data)
        elif header.type == MsgType.REJECT:
            body = Reject.from_dict(body_data)
        elif header.type == MsgType.FILL:
            body = Fill.from_dict(body_data)
        else:
            body = body_data
        
        return cls(header=header,body=body)
