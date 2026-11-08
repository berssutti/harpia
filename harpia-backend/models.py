from sqlalchemy import Column, Index, Integer, String, Boolean, DateTime, Text, UniqueConstraint
from datetime import datetime, timezone
from database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Watchlist(Base):
    __tablename__ = "watchlist"
    id = Column(Integer, primary_key=True, index=True)
    target_type = Column(String, index=True)  # cpf, email, domain
    value = Column(String, index=True, unique=True)
    added_at = Column(DateTime(timezone=True), default=utcnow)
    is_active = Column(Boolean, default=True)


class MonitoredGroup(Base):
    __tablename__ = "monitored_groups"
    id = Column(Integer, primary_key=True, index=True)
    telegram_chat_id = Column(String, index=True, nullable=True)
    name = Column(String, index=True)


class Credentials(Base):
    __tablename__ = "credentials"
    id = Column(Integer, primary_key=True, index=True)
    service = Column(String, index=True, unique=True)
    api_id = Column(String)
    api_hash = Column(String)
    phone = Column(String, nullable=True)


class Alert(Base):
    """A Telegram message that matched a watchlist target.

    The pair (telegram_group_id, telegram_message_id) is unique so retries from
    the worker are idempotent. Alerts intentionally do not reference the
    watchlist row: removing a target must not delete its historical alerts.
    """

    __tablename__ = "alerts"
    id = Column(String(36), primary_key=True)
    target_value = Column(String(320), nullable=False, index=True)
    target_type = Column(String(16), nullable=False, index=True)
    telegram_group_id = Column(String(64), nullable=False, index=True)
    telegram_group_name = Column(String(255), nullable=True)
    telegram_message_id = Column(String(64), nullable=False)
    message_text = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    received_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "telegram_group_id",
            "telegram_message_id",
            name="uq_alerts_telegram_message",
        ),
        Index("ix_alerts_timestamp_type", "timestamp", "target_type"),
        Index("ix_alerts_group_timestamp", "telegram_group_id", "timestamp"),
        Index("ix_alerts_target_timestamp", "target_value", "timestamp"),
    )


class WorkerState(Base):
    """Single-row projection of the worker's latest heartbeat (id == 1)."""

    __tablename__ = "worker_state"
    id = Column(Integer, primary_key=True)
    status = Column(String(32), nullable=False, default="offline")
    version = Column(String(32), nullable=True)
    instance_id = Column(String(64), nullable=True)
    last_heartbeat = Column(DateTime(timezone=True), nullable=True)
    last_analyzed_count = Column(Integer, nullable=False, default=0)
    analyzed_total = Column(Integer, nullable=False, default=0)
    watchlist_size = Column(Integer, nullable=False, default=0)
    monitored_groups_count = Column(Integer, nullable=False, default=0)
