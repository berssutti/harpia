from pydantic import BaseModel, ConfigDict, Field, field_serializer
from datetime import datetime, timezone
from typing import Literal, Optional

TargetType = Literal["email", "domain", "cpf"]
WorkerStatus = Literal[
    "starting",
    "connected",
    "waiting_for_code",
    "waiting_for_password",
    "restarting",
    "error",
]

MAX_BULK_ITEMS = 5000


class WatchlistCreate(BaseModel):
    target_type: TargetType
    value: str = Field(min_length=1, max_length=320)


class WatchlistResponse(WatchlistCreate):
    id: int
    added_at: datetime
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class WatchlistBulkCreate(BaseModel):
    items: list[WatchlistCreate] = Field(max_length=MAX_BULK_ITEMS)


class WatchlistBulkResult(BaseModel):
    added: list[WatchlistResponse]
    added_count: int
    skipped_duplicates: list[str]
    skipped_duplicates_count: int
    invalid: list[str]
    invalid_count: int


class MonitoredGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    telegram_chat_id: Optional[str] = Field(default=None, max_length=64)


class MonitoredGroupResponse(MonitoredGroupCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)


class GroupBulkCreate(BaseModel):
    items: list[str] = Field(max_length=MAX_BULK_ITEMS)


class GroupBulkResult(BaseModel):
    added: list[MonitoredGroupResponse]
    added_count: int
    skipped_duplicates: list[str]
    skipped_duplicates_count: int
    invalid: list[str]
    invalid_count: int


class CredentialsCreate(BaseModel):
    service: str = Field(min_length=1, max_length=64)
    api_id: str = Field(min_length=1, max_length=64)
    # Empty on update means "keep the stored hash".
    api_hash: str = Field(default="", max_length=256)
    phone: Optional[str] = Field(default=None, max_length=32)


class CredentialsResponse(BaseModel):
    id: int
    service: str
    api_id: Optional[str] = None
    # Masked in every public response; only /internal returns the real value.
    api_hash: Optional[str] = None
    phone: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TelegramAuthCode(BaseModel):
    code: Optional[str] = Field(default=None, max_length=16)
    password: Optional[str] = Field(default=None, max_length=256)


class AlertCreate(BaseModel):
    target_value: str = Field(min_length=1, max_length=320)
    target_type: TargetType
    telegram_group_id: str = Field(min_length=1, max_length=64)
    telegram_group_name: Optional[str] = Field(default=None, max_length=255)
    telegram_message_id: str = Field(min_length=1, max_length=64)
    message_text: str = Field(min_length=1, max_length=65536)
    timestamp: datetime


class AlertResponse(BaseModel):
    id: str
    target_value: str
    target_type: TargetType
    telegram_group_id: str
    telegram_group_name: Optional[str] = None
    telegram_message_id: str
    message_text: str
    timestamp: datetime
    received_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("timestamp", "received_at", when_used="json")
    def serialize_timestamp(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()


class AlertIngestResult(BaseModel):
    status: Literal["created", "duplicate"]
    alert: AlertResponse


class WorkerHeartbeat(BaseModel):
    status: WorkerStatus
    version: str = Field(min_length=1, max_length=32)
    instance_id: str = Field(min_length=1, max_length=64)
    analyzed_messages: int = Field(ge=0)
    watchlist_size: int = Field(ge=0)
    monitored_groups_count: int = Field(ge=0)


class MonitoringConfigWatchlistItem(BaseModel):
    value: str
    target_type: TargetType


class MonitoringConfigGroupItem(BaseModel):
    name: str


class MonitoringConfigResponse(BaseModel):
    watchlist: list[MonitoringConfigWatchlistItem]
    groups: list[MonitoringConfigGroupItem]
    generated_at: datetime
