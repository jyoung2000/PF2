"""Forge tables (spec §5, §8, §9, §18) on the shared Base — registered by
db._register_optional_models() so create_all + the additive migration (D61)
cover them. Nothing existing changes shape."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Index,
                        Integer, String, Text)
from sqlalchemy.orm import Mapped, mapped_column

from ..models import Base, utcnow


class PromptExperiment(Base):
    __tablename__ = "prompt_experiments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    brief: Mapped[str | None] = mapped_column(Text)
    intent: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PromptVariant(Base):
    __tablename__ = "prompt_variants"
    __table_args__ = (Index("ix_prompt_variants_exp", "experiment_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("prompt_experiments.id", ondelete="CASCADE"))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("prompt_variants.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    label: Mapped[str | None] = mapped_column(String(200))
    origin: Mapped[str] = mapped_column(String(12), default="manual")  # manual|compiled|refined|fork
    prompt: Mapped[str] = mapped_column(Text)
    negative: Mapped[str | None] = mapped_column(Text)
    family: Mapped[str | None] = mapped_column(String(100))
    provider: Mapped[str | None] = mapped_column(String(50))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    package: Mapped[dict] = mapped_column(JSON, default=dict)  # full PromptPackage snapshot
    winner: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VariantRun(Base):
    __tablename__ = "variant_runs"
    __table_args__ = (Index("ix_variant_runs_variant", "variant_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    variant_id: Mapped[int] = mapped_column(
        ForeignKey("prompt_variants.id", ondelete="CASCADE"))
    generation_id: Mapped[int | None] = mapped_column(
        ForeignKey("generations.id", ondelete="SET NULL"))
    family: Mapped[str | None] = mapped_column(String(100))
    provider: Mapped[str | None] = mapped_column(String(50))
    provider_model_id: Mapped[str | None] = mapped_column(String(200))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="queued")
    user_score: Mapped[int | None] = mapped_column(Integer)   # 1–5
    user_notes: Mapped[str | None] = mapped_column(Text)
    evaluation: Mapped[dict] = mapped_column(JSON, default=dict)
    cost: Mapped[float | None] = mapped_column(Float)
    latency_s: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CreativePlan(Base):
    __tablename__ = "creative_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    brief: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="draft")  # draft|running|done
    meta: Mapped[dict] = mapped_column(JSON, default=dict)   # preset used, llm note, …
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlanAsset(Base):
    __tablename__ = "plan_assets"
    __table_args__ = (Index("ix_plan_assets_plan", "plan_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("creative_plans.id", ondelete="CASCADE"))
    order: Mapped[int] = mapped_column(Integer, default=0)
    purpose: Mapped[str] = mapped_column(String(200))
    depends_on: Mapped[list] = mapped_column(JSON, default=list)  # sibling asset ids
    kind: Mapped[str] = mapped_column(String(10), default="image")
    family: Mapped[str | None] = mapped_column(String(100))
    provider: Mapped[str | None] = mapped_column(String(50))
    prompt: Mapped[str | None] = mapped_column(Text)
    package: Mapped[dict] = mapped_column(JSON, default=dict)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    references: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="planned")
    # planned|queued|running|succeeded|failed|locked-skip
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    generation_id: Mapped[int | None] = mapped_column(
        ForeignKey("generations.id", ondelete="SET NULL"))
    cost_estimate: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Workflow(Base):
    __tablename__ = "workflows"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    graph: Mapped[dict] = mapped_column(JSON, default=dict)   # {nodes, edges}
    is_template: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (Index("ix_workflow_runs_wf", "workflow_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    # queued|running|waiting_approval|succeeded|failed|cancelled
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    node_states: Mapped[dict] = mapped_column(JSON, default=dict)  # node id → {status, output, error}
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
