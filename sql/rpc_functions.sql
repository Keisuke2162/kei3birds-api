-- =============================================================
-- マップ用 RPC 関数
-- Supabase SQL Editor で実行すること
-- =============================================================

-- GBIF観察記録を指定座標の半径内で取得（最大1000件）
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
    st_y(o.location::geometry)::float as lat,
    st_x(o.location::geometry)::float as lng,
    o.observed_at
  from gbif_observations o
  join bird_species b on b.id = o.species_id
  where st_dwithin(o.location, st_makepoint(_lng, _lat)::geography, _radius_m)
    and (_species_id is null or o.species_id = _species_id)
    and (_season      is null or o.season     = _season)
  limit 1000;
$$;

-- ユーザー自身の観察記録を地図表示用に全件取得
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
    st_y(o.location::geometry)::float as lat,
    st_x(o.location::geometry)::float as lng,
    o.taken_at,
    o.location_name
  from user_observations o
  left join bird_species b on b.id = o.species_id
  where o.user_id = _user_id;
$$;
