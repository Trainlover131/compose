"""Pydantic schemas for EditPlan, PlanPatch, and API request/response models."""

from __future__ import annotations

import copy
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# === Enums ===

class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class ProgressStep(str, Enum):
    UPLOADING = "uploading"
    TRANSCRIBING = "transcribing"
    PLANNING = "planning"
    FETCHING_BROLL = "fetching_broll"
    RENDERING = "rendering"
    DONE = "done"
    ERROR = "error"


# === EditPlan Schema ===

class OutputConfig(BaseModel):
    aspect_ratio: str = "9:16"
    resolution: list[int] = Field(default=[1080, 1920])
    max_duration_sec: int = 60


class MainCut(BaseModel):
    start: float
    end: float

    @field_validator("end")
    @classmethod
    def end_after_start(cls, v: float, info) -> float:
        if "start" in info.data and v <= info.data["start"]:
            raise ValueError("end must be after start")
        return v


class PunchIn(BaseModel):
    start: float
    end: float
    scale: float = Field(ge=1.0, le=1.5, default=1.1)


class BrollInsert(BaseModel):
    start: float
    end: float
    query: str
    keywords: list[str] = []
    source: str = "pexels"
    notes: str = ""
    asset_path: Optional[str] = None  # filled after download


class BrollConfig(BaseModel):
    enabled: bool = True
    strategy: str = "cutaway_fullscreen"
    inserts: list[BrollInsert] = []


class OverlayPlacement(BaseModel):
    x: float = Field(default=0.82, ge=0.0, le=1.0)
    y: float = Field(default=0.12, ge=0.0, le=1.0)
    w: float = Field(default=0.18, ge=0.0, le=1.0)


class OverlayAnimation(BaseModel):
    fade_in: float = 0.12
    fade_out: float = 0.12


class RenderIntent(BaseModel):
    profile: str = "graphic"
    has_text: bool = False
    requires_high_fidelity_text: bool = False
    wants_transparency: bool = True


class OverlayItem(BaseModel):
    type: str = "image_overlay"  # "image_overlay" | "video_overlay"
    start: float
    end: float
    anchor_phrase: str = ""
    keyword: str = ""
    query: str = ""
    source: str = "ai"  # "ai" | "pexels"
    style_hint: str = ""
    placement: OverlayPlacement = OverlayPlacement()
    animation: OverlayAnimation = OverlayAnimation()
    notes: str = ""
    asset_path: Optional[str] = None
    # Creative fields from VisualDirector
    intent: str = ""
    style_notes: Optional[str] = None
    must_include: list[str] = []
    must_avoid: list[str] = []
    text: Optional[str] = None
    render_intent: RenderIntent = RenderIntent()

    @field_validator("end")
    @classmethod
    def end_after_start(cls, v: float, info) -> float:
        if "start" in info.data and v <= info.data["start"]:
            raise ValueError("end must be after start")
        return v


class OverlayConfig(BaseModel):
    enabled: bool = True
    items: list[OverlayItem] = []


class CaptionKaraokeStyle(BaseModel):
    enabled: Optional[bool] = None
    color: Optional[str] = None  # "#RRGGBB"


class CaptionPauseEmphasis(BaseModel):
    enabled: Optional[bool] = None
    threshold_sec: Optional[float] = None  # e.g. 0.35


class CaptionStyle(BaseModel):
    """Optional user-driven caption style overrides.

    All fields are optional; when absent the renderer uses the style_id
    preset defaults.  The planner populates only the fields the user
    explicitly requested.
    """
    font_primary: Optional[str] = None       # e.g. "Helvetica", "Inter"
    font_emphasis: Optional[str] = None      # e.g. "Playfair Display Italic"
    size: Optional[int] = None               # px
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    color: Optional[str] = None              # "#RRGGBB"
    outline_color: Optional[str] = None      # "#RRGGBB"
    outline_width: Optional[int] = None      # 0..10
    shadow_depth: Optional[int] = None       # 0..10
    tracking: Optional[int] = None           # letter spacing, -6..6
    y: Optional[int] = None                  # absolute pixel y, e.g. 900..1700
    align: Optional[int] = None              # ASS alignment (1-9), default 5
    karaoke: Optional[CaptionKaraokeStyle] = None
    pause_emphasis: Optional[CaptionPauseEmphasis] = None
    invert: Optional[bool] = None            # difference-blend negative captions
    invert_scope: Optional[str] = None       # "all" | "emphasis"
    emphasis_size_multiplier: Optional[float] = None  # 1.00..1.35


class CaptionConfig(BaseModel):
    enabled: bool = True
    style_id: str = "default"
    max_words_per_line: int = 5
    max_lines: int = 2
    style: Optional[CaptionStyle] = None


class MusicConfig(BaseModel):
    enabled: bool = True
    track_id: str = "upbeat-energy"
    target_volume_db: float = -18.0


class Rationale(BaseModel):
    hook: str = ""
    structure: list[str] = []


class EditPlan(BaseModel):
    version: str = "1"
    preset_id: str = "snappy-creator"
    output: OutputConfig = OutputConfig()
    main_cuts: list[MainCut] = []
    punch_ins: list[PunchIn] = []
    broll: BrollConfig = BrollConfig()
    overlays: OverlayConfig = OverlayConfig()
    captions: CaptionConfig = CaptionConfig()
    music: MusicConfig = MusicConfig()
    rationale: Rationale = Rationale()

    @field_validator("main_cuts")
    @classmethod
    def cuts_sorted_non_overlapping(cls, v: list[MainCut]) -> list[MainCut]:
        if not v:
            return v
        sorted_cuts = sorted(v, key=lambda c: c.start)
        for i in range(1, len(sorted_cuts)):
            if sorted_cuts[i].start < sorted_cuts[i - 1].end:
                raise ValueError(f"main_cuts overlap at index {i}")
        return sorted_cuts

    @field_validator("overlays")
    @classmethod
    def overlays_sorted_non_overlapping(cls, v: OverlayConfig) -> OverlayConfig:
        if not v.items:
            return v
        sorted_items = sorted(v.items, key=lambda o: o.start)
        for i in range(1, len(sorted_items)):
            if sorted_items[i].start < sorted_items[i - 1].end:
                raise ValueError(f"overlays.items overlap at index {i}")
        v.items = sorted_items
        return v

    def total_duration(self) -> float:
        return sum(c.end - c.start for c in self.main_cuts)


# === PlanPatch Schema ===

class CaptionPatch(BaseModel):
    style_id: Optional[str] = None
    max_words_per_line: Optional[int] = None
    max_lines: Optional[int] = None
    enabled: Optional[bool] = None
    style: Optional[CaptionStyle] = None


class MusicPatch(BaseModel):
    enabled: Optional[bool] = None
    track_id: Optional[str] = None
    target_volume_db: Optional[float] = None


class BrollPatch(BaseModel):
    enabled: Optional[bool] = None
    max_broll_clips: Optional[int] = None
    strategy: Optional[str] = None


class PunchInPatch(BaseModel):
    enabled: Optional[bool] = None
    strength_multiplier: Optional[float] = None


class OutputPatch(BaseModel):
    resolution: Optional[list[int]] = None
    aspect_ratio: Optional[str] = None


class TimingPatch(BaseModel):
    target_duration_sec: Optional[int] = None
    tightness: Optional[float] = Field(None, ge=0.5, le=1.5)


class PlanPatch(BaseModel):
    captions: Optional[CaptionPatch] = None
    music: Optional[MusicPatch] = None
    broll: Optional[BrollPatch] = None
    punch_ins: Optional[PunchInPatch] = None
    output: Optional[OutputPatch] = None
    timing_adjustments: Optional[TimingPatch] = None


def apply_patch(plan: EditPlan, patch: PlanPatch) -> EditPlan:
    """Apply a PlanPatch to an EditPlan, returning a new EditPlan."""
    data = plan.model_dump()

    if patch.captions:
        for k, v in patch.captions.model_dump(exclude_none=True).items():
            data["captions"][k] = v

    if patch.music:
        for k, v in patch.music.model_dump(exclude_none=True).items():
            data["music"][k] = v

    if patch.broll:
        patch_data = patch.broll.model_dump(exclude_none=True)
        if "enabled" in patch_data:
            data["broll"]["enabled"] = patch_data["enabled"]
        if "strategy" in patch_data:
            data["broll"]["strategy"] = patch_data["strategy"]
        if "max_broll_clips" in patch_data:
            data["broll"]["inserts"] = data["broll"]["inserts"][
                : patch_data["max_broll_clips"]
            ]

    if patch.punch_ins:
        patch_data = patch.punch_ins.model_dump(exclude_none=True)
        if "enabled" in patch_data and not patch_data["enabled"]:
            data["punch_ins"] = []
        if "strength_multiplier" in patch_data:
            mult = patch_data["strength_multiplier"]
            for pi in data["punch_ins"]:
                pi["scale"] = min(1.5, max(1.0, pi["scale"] * mult))

    if patch.output:
        for k, v in patch.output.model_dump(exclude_none=True).items():
            data["output"][k] = v

    if patch.timing_adjustments:
        td = patch.timing_adjustments
        if td.target_duration_sec is not None:
            data["output"]["max_duration_sec"] = td.target_duration_sec
        if td.tightness is not None:
            # Adjust cuts: tightness < 1.0 means shorter
            current_cuts = data["main_cuts"]
            if current_cuts and td.tightness < 1.0:
                target_total = sum(
                    c["end"] - c["start"] for c in current_cuts
                ) * td.tightness
                running = 0.0
                new_cuts = []
                for c in current_cuts:
                    dur = c["end"] - c["start"]
                    if running + dur <= target_total:
                        new_cuts.append(c)
                        running += dur
                    else:
                        remaining = target_total - running
                        if remaining > 0.5:
                            new_cuts.append(
                                {"start": c["start"], "end": c["start"] + remaining}
                            )
                        break
                data["main_cuts"] = new_cuts

    return EditPlan.model_validate(data)


# === API Schemas ===

class JobCreateResponse(BaseModel):
    job_id: str


class RevisionSummary(BaseModel):
    revision_id: str
    revision_number: int
    status: str
    output_url: Optional[str] = None
    instruction: Optional[str] = None


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress_step: Optional[ProgressStep] = None
    error: Optional[str] = None
    output_url: Optional[str] = None
    edit_plan: Optional[dict] = None
    revisions: list[RevisionSummary] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class EditRequest(BaseModel):
    instruction: str


class EditResponse(BaseModel):
    revision_id: str
    status: str


class RevisionResponse(BaseModel):
    revision_id: str
    revision_number: int
    status: str
    output_url: Optional[str] = None


class PresetResponse(BaseModel):
    id: str
    name: str
    description: str
    config: dict


# === Presigned Upload Schemas ===

class PresignRequest(BaseModel):
    filename: str
    content_type: str


class PresignResponse(BaseModel):
    file_key: str
    upload_url: str
