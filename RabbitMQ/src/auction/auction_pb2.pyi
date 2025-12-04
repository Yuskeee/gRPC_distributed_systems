import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AuctionStatus(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    AUCTION_STATUS_ACTIVE: _ClassVar[AuctionStatus]
    AUCTION_STATUS_PENDING: _ClassVar[AuctionStatus]
    AUCTION_STATUS_CLOSED: _ClassVar[AuctionStatus]
AUCTION_STATUS_ACTIVE: AuctionStatus
AUCTION_STATUS_PENDING: AuctionStatus
AUCTION_STATUS_CLOSED: AuctionStatus

class CreateAuctionRequest(_message.Message):
    __slots__ = ("description", "start_time", "end_time")
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    START_TIME_FIELD_NUMBER: _ClassVar[int]
    END_TIME_FIELD_NUMBER: _ClassVar[int]
    description: str
    start_time: _timestamp_pb2.Timestamp
    end_time: _timestamp_pb2.Timestamp
    def __init__(self, description: _Optional[str] = ..., start_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., end_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class Auction(_message.Message):
    __slots__ = ("id", "description", "start_time", "end_time", "status")
    ID_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    START_TIME_FIELD_NUMBER: _ClassVar[int]
    END_TIME_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    id: int
    description: str
    start_time: _timestamp_pb2.Timestamp
    end_time: _timestamp_pb2.Timestamp
    status: str
    def __init__(self, id: _Optional[int] = ..., description: _Optional[str] = ..., start_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., end_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., status: _Optional[str] = ...) -> None: ...

class ListAuctionsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListAuctionsResponse(_message.Message):
    __slots__ = ("auctions",)
    AUCTIONS_FIELD_NUMBER: _ClassVar[int]
    auctions: _containers.RepeatedCompositeFieldContainer[Auction]
    def __init__(self, auctions: _Optional[_Iterable[_Union[Auction, _Mapping]]] = ...) -> None: ...
