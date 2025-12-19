"""SQLAlchemy models for tracked items and price monitoring."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class TrackedItem(Base):
    """User-tracked items for price monitoring.
    
    A tracked item represents a product that a user wants to monitor across
    multiple stores. It can be:
    - Exact product (with canonical_product_id)
    - Spec-based (e.g., "RTX 4060 laptop, 16GB RAM" stored in specs JSONB)
    """
    __tablename__ = "tracked_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    canonical_product_id = Column(Text, nullable=False, index=True)
    specs = Column(JSON, nullable=True)  # JSONB for spec-based tracking
    target_price = Column(Numeric(10, 2), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    store_mappings = relationship("TrackedItemStore", back_populates="tracked_item", cascade="all, delete-orphan")
    current_prices = relationship("CurrentPrice", back_populates="tracked_item", cascade="all, delete-orphan")
    lowest_price = relationship("LowestPrice", back_populates="tracked_item", uselist=False, cascade="all, delete-orphan")


class TrackedItemStore(Base):
    """Store-specific mappings for tracked items.
    
    Links a tracked item to specific stores with their SKUs and URLs.
    One tracked item can have multiple store mappings.
    """
    __tablename__ = "tracked_item_stores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tracked_item_id = Column(Integer, ForeignKey("tracked_items.id", ondelete="CASCADE"), nullable=False, index=True)
    store_id = Column(Text, nullable=False, index=True)  # e.g., 'amazon_eg', 'noon', 'jumia'
    store_sku = Column(Text, nullable=False)
    store_url = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    tracked_item = relationship("TrackedItem", back_populates="store_mappings")


class CurrentPrice(Base):
    """Current price snapshot for tracked items across stores.
    
    Materialized view of the latest price for each tracked item per store.
    Updated whenever a price change is detected.
    """
    __tablename__ = "current_prices"

    tracked_item_id = Column(Integer, ForeignKey("tracked_items.id", ondelete="CASCADE"), primary_key=True, index=True)
    store_id = Column(Text, primary_key=True)
    price_usd = Column(Numeric(10, 4), nullable=False)
    price_local = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(10), nullable=False)
    in_stock = Column(Boolean, nullable=False, default=True, index=True)
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    tracked_item = relationship("TrackedItem", back_populates="current_prices")


class LowestPrice(Base):
    """Cached lowest price for each tracked item.
    
    Denormalized table storing the current best deal across all stores
    for fast API reads.
    """
    __tablename__ = "lowest_prices"

    tracked_item_id = Column(Integer, ForeignKey("tracked_items.id", ondelete="CASCADE"), primary_key=True)
    store_id = Column(Text, nullable=False)
    price_usd = Column(Numeric(10, 4), nullable=False)
    price_local = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(10), nullable=False)
    url = Column(Text, nullable=False)
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    tracked_item = relationship("TrackedItem", back_populates="lowest_price")
