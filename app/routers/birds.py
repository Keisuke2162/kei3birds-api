from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.config import get_supabase
from app.models.schemas import BirdSpecies

router = APIRouter(prefix="/birds", tags=["birds"])


@router.get("", response_model=list[BirdSpecies])
def get_birds(search: Optional[str] = Query(None, description="name_ja の部分一致検索")):
    """鳥の種類マスタ一覧を返す。"""
    supabase = get_supabase()
    query = supabase.table("bird_species").select(
        "id, name_ja, name_en, scientific_name, family, order_name"
    )
    if search:
        query = query.ilike("name_ja", f"%{search}%")

    result = query.execute()
    return result.data


@router.get("/{species_id}", response_model=BirdSpecies)
def get_bird(species_id: int):
    """指定した種の詳細を返す。"""
    supabase = get_supabase()
    result = (
        supabase.table("bird_species")
        .select("id, name_ja, name_en, scientific_name, family, order_name")
        .eq("id", species_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Bird not found")
    return result.data
