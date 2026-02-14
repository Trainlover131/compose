"""Preset API routes."""

from fastapi import APIRouter

from apps.api.models.presets import list_presets
from apps.api.models.schemas import PresetResponse

router = APIRouter(prefix="/api")


@router.get("/presets", response_model=list[PresetResponse])
async def get_presets():
    """Get available style presets."""
    return list_presets()
