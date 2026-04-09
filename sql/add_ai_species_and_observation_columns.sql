-- AI由来の種マスターテーブル
-- bird_species (GBIF) に存在しない鳥の名前解決・グルーピング用
CREATE TABLE IF NOT EXISTS ai_species (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scientific_name text NOT NULL UNIQUE,
    name_ja text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- user_observations に ai_species_id と表示用の名前カラムを追加
ALTER TABLE user_observations
ADD COLUMN IF NOT EXISTS ai_species_id bigint REFERENCES ai_species(id),
ADD COLUMN IF NOT EXISTS name_ja text,
ADD COLUMN IF NOT EXISTS scientific_name text;
