"""Blog tables used by the author dashboard."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from db.base import Base
from db.column_types import blog_post_status_enum


class Author(Base):
    __tablename__ = "authors"
    __table_args__ = (Index("ix_authors_partner_id", "partner_id", unique=True),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    partner_id = Column(Integer, nullable=False)
    author_bio = Column(Text, nullable=True)
    avatar_url = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    partner = relationship(
        "Partner",
        primaryjoin="foreign(Author.partner_id) == Partner.partner_id",
        viewonly=True,
    )
    employee = relationship(
        "Employee",
        primaryjoin="foreign(Author.partner_id) == Employee.employee_id",
        viewonly=True,
    )
    posts = relationship("Post", back_populates="author")


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(150), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    posts = relationship("Post", back_populates="category")


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        Index("idx_posts_author_id", "author_id"),
        Index("idx_posts_category_id", "category_id"),
        Index("idx_posts_status", "status"),
        Index("idx_posts_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    slug = Column(String(255), nullable=False, unique=True)
    content = Column(JSONB, nullable=False, server_default="[]")
    description = Column(String(500), nullable=True)
    thumbnail_url = Column(Text, nullable=True)
    background_color = Column(String(32), nullable=True)
    background_image_url = Column(Text, nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    author_id = Column(Integer, ForeignKey("authors.id", ondelete="RESTRICT"), nullable=False)
    status = Column(blog_post_status_enum, nullable=False, server_default="draft")
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    category = relationship("Category", back_populates="posts")
    author = relationship("Author", back_populates="posts")
    keywords = relationship(
        "Keyword",
        back_populates="post",
        cascade="all, delete-orphan",
        uselist=False,
    )


class Keyword(Base):
    __tablename__ = "keywords"

    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, unique=True)
    focus_keyword = Column(Text, nullable=True)

    post = relationship("Post", back_populates="keywords")
