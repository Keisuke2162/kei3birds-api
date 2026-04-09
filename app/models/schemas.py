from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


# ──────────────────────────────────────────────
# Bird
# ──────────────────────────────────────────────

class BirdSpecies(BaseModel):
    id: int
    name_ja: Optional[str] = None
    name_en: Optional[str] = None
    scientific_name: Optional[str] = None
    family: Optional[str] = None
    order_name: Optional[str] = None


# ──────────────────────────────────────────────
# Map
# ──────────────────────────────────────────────

class GBIFMapItem(BaseModel):
    species_id: int
    name_ja: Optional[str] = None
    lat: float
    lng: float
    observed_at: Optional[date] = None


class MyMapItem(BaseModel):
    id: str
    species_id: Optional[int] = None
    name_ja: Optional[str] = None
    photo_url: Optional[str] = None
    lat: float
    lng: float
    taken_at: Optional[datetime] = None
    location_name: Optional[str] = None


# ──────────────────────────────────────────────
# Observations
# ──────────────────────────────────────────────

class AiCandidate(BaseModel):
    species_id: int
    name_ja: str
    confidence: float


class ObservationCreate(BaseModel):
    species_id: Optional[int] = None
    ai_species_id: Optional[int] = None
    name_ja: Optional[str] = None
    scientific_name: Optional[str] = None
    photo_url: str
    taken_at: Optional[datetime] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    location_name: Optional[str] = None
    notes: Optional[str] = None


class Observation(BaseModel):
    id: str
    user_id: str
    species_id: Optional[int] = None
    ai_species_id: Optional[int] = None
    name_ja: Optional[str] = None
    scientific_name: Optional[str] = None
    photo_url: Optional[str] = None
    taken_at: Optional[datetime] = None
    location_name: Optional[str] = None
    ai_candidates: Optional[list[AiCandidate]] = None
    notes: Optional[str] = None
    created_at: datetime


# ──────────────────────────────────────────────
# Upload
# ──────────────────────────────────────────────

class UploadPhotoResponse(BaseModel):
    url: str


class IdentifyCandidate(BaseModel):
    species_id: Optional[int] = None
    ai_species_id: Optional[int] = None
    name_ja: str
    scientific_name: Optional[str] = None
    confidence: float


class IdentifyResponse(BaseModel):
    identified: bool
    candidates: list[IdentifyCandidate]
