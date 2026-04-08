from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from app.auth import get_current_user_id, get_raw_token
from app.config import get_supabase_with_token
from app.models.schemas import Observation, ObservationCreate

router = APIRouter(prefix="/observations", tags=["observations"])


@router.get("", response_model=list[Observation])
def list_observations(
    species_id: Optional[int] = Query(None),
    user_id: str = Depends(get_current_user_id),
    token: str = Depends(get_raw_token),
):
    """ログインユーザーの撮影記録一覧を返す。"""
    supabase = get_supabase_with_token(token)
    query = (
        supabase.table("user_observations")
        .select("*")
        .eq("user_id", user_id)
    )
    if species_id is not None:
        query = query.eq("species_id", species_id)

    result = query.order("created_at", desc=True).execute()
    return result.data


@router.get("/{observation_id}", response_model=Observation)
def get_observation(
    observation_id: str,
    user_id: str = Depends(get_current_user_id),
    token: str = Depends(get_raw_token),
):
    """指定した撮影記録の詳細を返す。"""
    supabase = get_supabase_with_token(token)
    result = (
        supabase.table("user_observations")
        .select("*")
        .eq("id", observation_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Observation not found")
    return result.data


@router.post("", response_model=Observation, status_code=201)
def create_observation(
    body: ObservationCreate,
    user_id: str = Depends(get_current_user_id),
    token: str = Depends(get_raw_token),
):
    """撮影記録を新規登録する。"""
    supabase = get_supabase_with_token(token)

    record: dict = {
        "user_id": user_id,
        "photo_url": body.photo_url,
        "species_id": body.species_id,
        "taken_at": body.taken_at.isoformat() if body.taken_at else None,
        "location_name": body.location_name,
        "notes": body.notes,
    }
    # 座標が指定されている場合は PostGIS の point 形式で保存
    if body.lat is not None and body.lng is not None:
        record["location"] = f"POINT({body.lng} {body.lat})"

    result = supabase.table("user_observations").insert(record).execute()
    return result.data[0]


@router.delete("/{observation_id}", status_code=204)
def delete_observation(
    observation_id: str,
    user_id: str = Depends(get_current_user_id),
    token: str = Depends(get_raw_token),
):
    """自分の撮影記録を削除する。"""
    supabase = get_supabase_with_token(token)
    result = (
        supabase.table("user_observations")
        .delete()
        .eq("id", observation_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Observation not found")
