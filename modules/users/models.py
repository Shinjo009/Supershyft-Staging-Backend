"""Users module models.

Auth depends on this module for read-only existence checks.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, JSON, String, func, text

from db.base import Base


class User(Base):
    """SQLAlchemy model for `users` table."""

    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_parent_id", "parent_id"),
        Index(
            "ix_users_metsights_profile_id",
            "metsights_profile_id",
            postgresql_where=text("metsights_profile_id IS NOT NULL"),
        ),
    )

    user_id = Column(Integer, primary_key=True)
    first_name = Column(String)
    last_name = Column(String)
    age = Column(Integer, nullable=True)
    phone = Column(String, nullable=False)
    email = Column(String)
    metsights_profile_id = Column(String, nullable=True)
    profile_photo = Column(String)
    date_of_birth = Column(Date, nullable=True)
    gender = Column(String)
    address = Column(String)
    pin_code = Column(String)
    city = Column(String)
    state = Column(String)
    country = Column(String)
    referred_by = Column(String)
    is_participant = Column(Boolean)
    status = Column(String)
    parent_id = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    relationship = Column(String, nullable=False, server_default=text("'self'"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UserPreference(Base):
    """SQLAlchemy model for `user_preferences` table."""

    __tablename__ = "user_preferences"

    preference_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, unique=True)
    push_enabled = Column(Boolean, nullable=False, server_default=text("true"))
    email_enabled = Column(Boolean, nullable=False, server_default=text("true"))
    sms_enabled = Column(Boolean, nullable=False, server_default=text("false"))
    access_to_files = Column(Boolean, nullable=False, server_default=text("true"))
    store_downloaded_files = Column(Boolean, nullable=False, server_default=text("true"))
    diet_preference = Column(String, nullable=True)
    allergies = Column(JSON, nullable=True, server_default=text("'[]'"))
    sports_playlists = Column(JSON, nullable=True, server_default=text("'{}'"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class UserAddress(Base):
    """SQLAlchemy model for `user_addresses` table (max 3 per user)."""

    __tablename__ = "user_addresses"
    __table_args__ = (Index("ix_user_addresses_user_id", "user_id"),)

    user_address_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    address_line1 = Column(String, nullable=True)
    address_line2 = Column(String, nullable=True)
    landmark = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    pincode = Column(String, nullable=True)
    address = Column(String, nullable=True)
    is_default = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
