"""Film Studio tables (S1.1). All additive; registered on the shared
`models.Base` metadata so `db.init_db()` creates/migrates them like every
other table (D61). Naming: film_* to keep the namespace obvious."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Index,
                        Integer, String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from ..models import Base, utcnow

ASSET_TYPES = ("character", "location", "prop", "vehicle", "outfit", "style")
MEDIA_STRATEGIES = ("ai_video", "image_animation", "user_footage", "stock",
                    "archival", "motion_graphics", "screen_recording",
                    "talking_head", "still")


class FilmProject(Base):
    __tablename__ = "film_projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    logline: Mapped[str | None] = mapped_column(Text)
    synopsis: Mapped[str | None] = mapped_column(Text)
    script: Mapped[str | None] = mapped_column(Text)        # pasted/imported/generated script
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|planning|production|complete
    settings: Mapped[dict] = mapped_column(JSON, default=dict)   # aspect, runtime, gaps, pacing, continuity, budget…
    plan: Mapped[dict] = mapped_column(JSON, default=dict)       # production plan (S2) + approval
    reference: Mapped[dict] = mapped_column(JSON, default=dict)  # reference-video analysis (S3)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FilmScene(Base):
    __tablename__ = "film_scenes"
    __table_args__ = (Index("ix_film_scenes_project", "project_id", "position"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("film_projects.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    act: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200), default="Scene")
    intent: Mapped[str | None] = mapped_column(Text)        # scene goal
    summary: Mapped[str | None] = mapped_column(Text)
    script_text: Mapped[str | None] = mapped_column(Text)   # the scene's script excerpt
    defaults: Mapped[dict] = mapped_column(JSON, default=dict)   # scene context: assets, time, weather, lighting, style…
    gap_after_s: Mapped[float | None] = mapped_column(Float)     # None ⇒ inherit project default
    transition: Mapped[dict | None] = mapped_column(JSON)        # editorial transition out of the scene (separate from gap)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)  # rough-cut approval
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FilmShot(Base):
    __tablename__ = "film_shots"
    __table_args__ = (Index("ix_film_shots_scene", "scene_id", "position"),
                      Index("ix_film_shots_project", "project_id"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("film_projects.id", ondelete="CASCADE"))
    scene_id: Mapped[int] = mapped_column(ForeignKey("film_scenes.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="planned")  # planned|framed|generated|approved|needs_repair
    duration_s: Mapped[float] = mapped_column(Float, default=4.0)
    transition: Mapped[dict | None] = mapped_column(JSON)     # to the NEXT shot: {kind, duration_s}
    media_strategy: Mapped[str] = mapped_column(String(20), default="ai_video")
    overrides: Mapped[dict] = mapped_column(JSON, default=dict)   # explicit shot overrides (action/camera/lighting/…)
    locks: Mapped[list] = mapped_column(JSON, default=list)       # locked property groups
    start_frame: Mapped[dict | None] = mapped_column(JSON)        # {kind, path, take_id, source_shot_id, locked}
    end_frame: Mapped[dict | None] = mapped_column(JSON)
    chain_from_previous: Mapped[bool] = mapped_column(Boolean, default=False)
    selected_take_id: Mapped[int | None] = mapped_column(Integer)   # FK-free on purpose (takes cascade from shots)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    qa: Mapped[dict | None] = mapped_column(JSON)               # last QA verdict
    warnings: Mapped[list] = mapped_column(JSON, default=list)  # continuity warnings cache
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FilmAsset(Base):
    """Global reusable asset (character/location/prop/vehicle/outfit/style).
    Structured attributes live on versions; this row is identity + metadata."""
    __tablename__ = "film_assets"
    __table_args__ = (Index("ix_film_assets_type", "type"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)   # asset-approval gate
    current_version_id: Mapped[int | None] = mapped_column(Integer)  # → film_asset_versions.id
    owner_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("film_assets.id", ondelete="CASCADE"))            # outfits belong to a character
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("film_projects.id", ondelete="SET NULL"))         # optional home project (assets are global)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)     # origin: manual|director|inspiration|import …
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FilmAssetVersion(Base):
    """Immutable once frozen (used by a shot/take, or superseded)."""
    __tablename__ = "film_asset_versions"
    __table_args__ = (UniqueConstraint("asset_id", "number", name="uq_film_asset_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("film_assets.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer, default=1)
    label: Mapped[str | None] = mapped_column(String(120))
    data: Mapped[dict] = mapped_column(JSON, default=dict)             # structured attributes (per-type schema)
    locks: Mapped[list] = mapped_column(JSON, default=list)            # locked attribute groups
    identity_anchors: Mapped[list] = mapped_column(JSON, default=list)
    continuity_rules: Mapped[list] = mapped_column(JSON, default=list)
    negative_constraints: Mapped[list] = mapped_column(JSON, default=list)
    primary_ref_id: Mapped[int | None] = mapped_column(Integer)        # → film_asset_refs.id
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)       # source: manual|duplicate|restore|ai|import, from_version_id, generation…
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FilmAssetRef(Base):
    """Reference image for an asset (optionally tied to one version). The
    original upload is preserved byte-for-byte; the thumb is a derivative."""
    __tablename__ = "film_asset_refs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("film_assets.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[int | None] = mapped_column(
        ForeignKey("film_asset_versions.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(30), default="custom")
    label: Mapped[str | None] = mapped_column(String(200))
    path: Mapped[str] = mapped_column(Text)            # relative to DATA_DIR (film/…)
    thumb_path: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(50), default="upload")   # upload | post:{id} | take:{id} | url
    source_post_id: Mapped[int | None] = mapped_column(Integer)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FilmShotAsset(Base):
    """Exact asset version pinned to a shot (overrides the scene default)."""
    __tablename__ = "film_shot_assets"
    __table_args__ = (UniqueConstraint("shot_id", "asset_id", name="uq_film_shot_asset"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shot_id: Mapped[int] = mapped_column(ForeignKey("film_shots.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("film_assets.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("film_asset_versions.id", ondelete="RESTRICT"))
    role: Mapped[str] = mapped_column(String(20), default="character")
    notes: Mapped[str | None] = mapped_column(Text)


class FilmTake(Base):
    """One generated/imported artifact for a shot (start/end frame, video,
    audio…). Alternates are never destroyed; the shot selects one."""
    __tablename__ = "film_takes"
    __table_args__ = (Index("ix_film_takes_shot", "shot_id", "kind"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shot_id: Mapped[int] = mapped_column(ForeignKey("film_shots.id", ondelete="CASCADE"))
    project_id: Mapped[int] = mapped_column(ForeignKey("film_projects.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(20), default="video")   # start_frame|end_frame|video|image|graphics|footage|audio
    status: Mapped[str] = mapped_column(String(12), default="queued") # queued|running|succeeded|failed|imported
    mode: Mapped[str | None] = mapped_column(String(30))              # generation mode (text_to_video, start_end_to_video…)
    generation_id: Mapped[int | None] = mapped_column(
        ForeignKey("generations.id", ondelete="SET NULL"))
    provider: Mapped[str | None] = mapped_column(String(50))
    model_family: Mapped[str | None] = mapped_column(String(100))
    provider_model_id: Mapped[str | None] = mapped_column(String(200))
    prompt: Mapped[str | None] = mapped_column(Text)
    negative: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    context: Mapped[dict] = mapped_column(JSON, default=dict)     # effective context snapshot incl. asset versions + locks
    decision: Mapped[dict] = mapped_column(JSON, default=dict)    # provider scoring: selected/alternatives/reason
    cost_estimate: Mapped[float | None] = mapped_column(Float)
    cost_actual: Mapped[float | None] = mapped_column(Float)
    duration_s: Mapped[float | None] = mapped_column(Float)
    media_path: Mapped[str | None] = mapped_column(Text)
    thumb_path: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id", ondelete="SET NULL"))
    qa: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FilmEvent(Base):
    """Decision log / audit trail (spec X) — concise reasons, never chain-of-
    thought. Also the source for Backlot “replay run”."""
    __tablename__ = "film_events"
    __table_args__ = (Index("ix_film_events_project", "project_id", "id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("film_projects.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    kind: Mapped[str] = mapped_column(String(20), default="decision")  # decision|gate|generation|edit|qa|cost|director|checkpoint
    stage: Mapped[str | None] = mapped_column(String(20))
    actor: Mapped[str] = mapped_column(String(12), default="user")     # user|director|system
    entity_type: Mapped[str | None] = mapped_column(String(20))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    reason: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class FilmGate(Base):
    """Creative approval gates (spec G): plan | assets | storyboard |
    rough_cut (per scene) | qa | export."""
    __tablename__ = "film_gates"
    __table_args__ = (UniqueConstraint("project_id", "kind", "scene_id", name="uq_film_gate"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("film_projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    scene_id: Mapped[int | None] = mapped_column(ForeignKey("film_scenes.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending|approved|rejected
    note: Mapped[str | None] = mapped_column(Text)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)   # what exactly was approved (ids/versions/takes)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FilmClip(Base):
    """Footage corpus (spec D/E): user footage + stock/archival results.
    License info is stored as given — never implied."""
    __tablename__ = "film_clips"
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_film_clip_source"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("film_projects.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(30), default="user")   # user|pexels|pixabay|unsplash|archive|wikimedia|nasa
    source_id: Mapped[str] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    license: Mapped[dict | None] = mapped_column(JSON)      # {name, url, attribution} or None = unknown
    media_type: Mapped[str] = mapped_column(String(10), default="video")
    duration_s: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    transcript: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    path: Mapped[str | None] = mapped_column(Text)          # local file when downloaded/uploaded
    thumb_path: Mapped[str | None] = mapped_column(Text)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)   # technical props, cuts, keyframes
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FilmJob(Base):
    """Resumable long-running work (spec Y): director runs, batches, exports,
    analyses. `checkpoint` records what already completed so a restart or a
    provider failure never redoes finished items."""
    __tablename__ = "film_jobs"
    __table_args__ = (Index("ix_film_jobs_project", "project_id", "status"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("film_projects.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued|running|paused|done|failed|cancelled
    stage: Mapped[str | None] = mapped_column(String(20))
    progress: Mapped[dict] = mapped_column(JSON, default=dict)     # {done, total, current}
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)   # completed item ids etc.
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FilmAudioTrack(Base):
    """Timeline audio (spec N): dialogue | narration | voice | music |
    ambience | sfx. Anchored to the project timeline (start_s) or to a
    shot/scene so it re-syncs when timing changes."""
    __tablename__ = "film_audio_tracks"
    __table_args__ = (Index("ix_film_audio_project", "project_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("film_projects.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20), default="music")
    label: Mapped[str | None] = mapped_column(String(200))
    path: Mapped[str] = mapped_column(Text)                       # film/projects/{id}/audio/…
    source: Mapped[str] = mapped_column(String(30), default="upload")   # upload | tts | music | sfx | import
    provider: Mapped[str | None] = mapped_column(String(50))
    anchor_kind: Mapped[str] = mapped_column(String(10), default="timeline")   # timeline | shot | scene
    anchor_id: Mapped[int | None] = mapped_column(Integer)
    offset_s: Mapped[float] = mapped_column(Float, default=0.0)   # relative to the anchor start
    duration_s: Mapped[float | None] = mapped_column(Float)
    trim_start_s: Mapped[float] = mapped_column(Float, default=0.0)
    trim_end_s: Mapped[float | None] = mapped_column(Float)
    gain_db: Mapped[float] = mapped_column(Float, default=0.0)
    muted: Mapped[bool] = mapped_column(Boolean, default=False)
    fade_in_s: Mapped[float] = mapped_column(Float, default=0.0)
    fade_out_s: Mapped[float] = mapped_column(Float, default=0.0)
    loop: Mapped[bool] = mapped_column(Boolean, default=False)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FilmSubtitle(Base):
    """One subtitle track per project (spec O): cues with optional shot
    anchors so they follow timing changes; style for burn-in."""
    __tablename__ = "film_subtitles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("film_projects.id", ondelete="CASCADE"), unique=True)
    language: Mapped[str] = mapped_column(String(10), default="en")
    cues: Mapped[list] = mapped_column(JSON, default=list)   # [{id, start_s, end_s, text, shot_id?, rel_start_s?, rel_end_s?}]
    style: Mapped[dict] = mapped_column(JSON, default=dict)  # {font_size, color, outline, position}
    source: Mapped[str] = mapped_column(String(20), default="manual")   # manual | script | imported | generated
    burn_in: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
