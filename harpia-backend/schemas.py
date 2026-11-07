from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal, Optional

TargetType = Literal["email", "domain", "cpf"]

MAX_BULK_ITEMS = 5000


class WatchlistCreate(BaseModel):
    target_type: TargetType
    value: str = Field(min_length=1, max_length=320)


class WatchlistResponse(WatchlistCreate):
    id: int
    added_at: datetime
    is_active: bool

    class Config:
        from_attributes = True


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

    class Config:
        from_attributes = True


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

    class Config:
        from_attributes = True


class TelegramAuthCode(BaseModel):
    code: Optional[str] = Field(default=None, max_length=16)
    password: Optional[str] = Field(default=None, max_length=256)
