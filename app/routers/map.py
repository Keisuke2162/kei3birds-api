"""
マップ用エンドポイント

PostGIS の地理クエリは Supabase の RPC（PostgreSQL 関数）で実行する。
事前に以下の2つの関数を Supabase SQL Editor で作成しておくこと：

  -- GBIF観察記録を半径内で取得
  create or replace function get_gbif_map(
    _lat float, _lng float, _radius_m float,
    _species_id bigint default null,
    _season text default null
  )
  returns table (
    species_id bigint, name_ja text,
    lat float, lng float, observed_at date
  )
  language sql stable as $$
    select
      o.species_id,
      b.name_ja,
      st_y(o.location::geometry) as lat,
      st_x(o.location::geometry) as lng,
      o.observed_at
    from gbif_observations o
    join bird_species b on b.id = o.species_id
    where st_dwithin(o.location, st_makepoint(_lng, _lat)::geography, _radius_m)
      and (_species_id is null or o.species_id = _species_id)
      and (_season      is null or o.season     = _season)
    limit 1000;
  $$;

  -- ユーザー自身の観察記録を全件取得
  create or replace function get_my_map(_user_id uuid)
  returns table (
    id uuid, species_id bigint, name_ja text,
    photo_url text, lat float, lng float,
    taken_at timestamptz, location_name text
  )
  language sql stable as $$
    select
      o.id,
      o.species_id,
      b.name_ja,
      o.photo_url,
      st_y(o.location::geometry) as lat,
      st_x(o.location::geometry) as lng,
      o.taken_at,
      o.location_name
    from user_observations o
    left join bird_species b on b.id = o.species_id
    where o.user_id = _user_id;
  $$;
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from app.auth import get_current_user_id, get_raw_token
from app.config import get_supabase, get_supabase_with_token
from app.models.schemas import GBIFMapItem, MyMapItem

router = APIRouter(prefix="/map", tags=["map"])


@router.get("/gbif", response_model=list[GBIFMapItem])
def get_gbif_map(
    lat: float = Query(..., description="中心緯度"),
    lng: float = Query(..., description="中心経度"),
    radius_km: int = Query(50, description="検索半径（km）"),
    species_id: Optional[int] = Query(None),
    season: Optional[str] = Query(None, pattern="^(spring|summer|autumn|winter)$"),
):
    """指定座標から半径内の GBIF 観察記録を返す（最大1000件）。"""
    supabase = get_supabase()
    result = supabase.rpc(
        "get_gbif_map",
        {
            "_lat": lat,
            "_lng": lng,
            "_radius_m": radius_km * 1000,
            "_species_id": species_id,
            "_season": season,
        },
    ).execute()
    return result.data


@router.get("/my", response_model=list[MyMapItem])
def get_my_map(user_id: str = Depends(get_current_user_id), token: str = Depends(get_raw_token)):
    """ログインユーザーの撮影記録を地図用に返す。"""
    supabase = get_supabase_with_token(token)
    result = supabase.rpc("get_my_map", {"_user_id": user_id}).execute()
    return result.data
