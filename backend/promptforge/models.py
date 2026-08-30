"""SQLAlchemy 2.0 models — the full PromptForge data model."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer,
                        String, Text, UniqueConstraint, Index)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("platform", "platform_post_id", name="uq_platform_post"),
        Index("ix_posts_model_family", "model_family"),
        Index("ix_posts_scraped_at", "scraped_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(50))
    platform_post_id: Mapped[str] = mapped_column(String(200))
    prompt: Mapped[str | None] = mapped_column(Text)
    negative_prompt: Mapped[str | None] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(String(200))
    model_family: Mapped[str | None] = mapped_column(String(100))  # normalized via aliases
    model_version: Mapped[str | None] = mapped_column(String(100))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    media_type: Mapped[str] = mapped_column(String(10), default="image")  # image | video
    media_url: Mapped[str | None] = mapped_column(Text)
    media_path: Mapped[str | None] = mapped_column(Text)   # relative to DATA_DIR
    thumb_path: Mapped[str | None] = mapped_column(Text)
    media_width: Mapped[int | None] = mapped_column(Integer)
    media_height: Mapped[int | None] = mapped_column(Integer)
    duration_s: Mapped[float | None] = mapped_column(Float)
    author: Mapped[str | None] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    nsfw: Mapped[bool] = mapped_column(Boolean, default=False)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    origin: Mapped[str] = mapped_column(String(12), default="scraped")  # scraped | generated
    technique_tags: Mapped[list] = mapped_column(JSON, default=list)
    synced_to_baserow: Mapped[bool] = mapped_column(Boolean, default=False)
    posted_to_discord: Mapped[bool] = mapped_column(Boolean, default=False)

    tags: Mapped[list[Tag]] = relationship(
        secondary="post_tags", back_populates="posts", lazy="selectin")


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # case-insensitive uniqueness
    name: Mapped[str] = mapped_column(String(100, collation="NOCASE"), unique=True)

    posts: Mapped[list[Post]] = relationship(
        secondary="post_tags", back_populates="tags", lazy="noload")


class PostTag(Base):
    __tablename__ = "post_tags"
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)


class Collection(Base):
    __tablename__ = "collections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    cover_post_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"))
    model_family: Mapped[str | None] = mapped_column(String(100))
    allow_mixed_models: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CollectionPost(Base):
    __tablename__ = "collection_posts"
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReferenceImage(Base):
    __tablename__ = "reference_images"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    path: Mapped[str] = mapped_column(Text)  # relative to DATA_DIR
    source: Mapped[str | None] = mapped_column(String(200))  # upload | post:{id} | url
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RefLink(Base):
    """Links a reference image to a saved prompt and/or generation with a role."""
    __tablename__ = "ref_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ref_id: Mapped[int] = mapped_column(ForeignKey("reference_images.id", ondelete="CASCADE"))
    saved_prompt_id: Mapped[int | None] = mapped_column(
        ForeignKey("saved_prompts.id", ondelete="CASCADE"))
    generation_id: Mapped[int | None] = mapped_column(
        ForeignKey("generations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20), default="style")  # style|character|composition|other


class SavedPrompt(Base):
    __tablename__ = "saved_prompts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    negative: Mapped[str | None] = mapped_column(Text)
    model_family: Mapped[str | None] = mapped_column(String(100))
    collection_id: Mapped[int | None] = mapped_column(
        ForeignKey("collections.id", ondelete="SET NULL"))
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("templates.id", ondelete="SET NULL"))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    origin: Mapped[str] = mapped_column(String(12), default="manual")  # manual|enhanced|template
    starred: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Template(Base):
    __tablename__ = "templates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collection_id: Mapped[int | None] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer, default=1)
    schema_json: Mapped[dict] = mapped_column(JSON, default=dict)  # visual form definition
    text_template: Mapped[str] = mapped_column(Text, default="")
    recommended_model: Mapped[str | None] = mapped_column(String(100))
    ref_slots: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Generation(Base):
    __tablename__ = "generations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    saved_prompt_id: Mapped[int | None] = mapped_column(
        ForeignKey("saved_prompts.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(50))
    provider_model_id: Mapped[str] = mapped_column(String(200))
    model_family: Mapped[str | None] = mapped_column(String(100))
    prompt: Mapped[str | None] = mapped_column(Text)
    cost_estimate: Mapped[float | None] = mapped_column(Float)
    cost_actual: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued|running|succeeded|failed
    error: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    output_post_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)  # JSON-encoded


class Companion(Base):
    __tablename__ = "companions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LlmJob(Base):
    """Knowledge/analysis jobs queued while the LLM (companion) is offline (D30)."""
    __tablename__ = "llm_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued|running|done|error
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ScraperState(Base):
    """Per-adapter persisted state: enable flag, interval, last run stats, cursors."""
    __tablename__ = "scraper_state"
    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=15)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(20))  # ok | error | running
    last_error: Mapped[str | None] = mapped_column(Text)
    last_found: Mapped[int] = mapped_column(Integer, default=0)
    last_new: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[dict] = mapped_column(JSON, default=dict)  # adapter cursors etc.
