from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime, timezone
from database import Base

class Watchlist(Base):
    __tablename__ = "watchlist"
    id = Column(Integer, primary_key=True, index=True)
    target_type = Column(String, index=True) # cpf, email, domain
    value = Column(String, index=True, unique=True)
    added_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
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
