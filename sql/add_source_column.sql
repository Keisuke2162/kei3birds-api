-- bird_species テーブルに source カラムを追加
-- 'gbif': GBIFバッチで登録された種
-- 'ai': AI判定時に自動登録された種（GBIFに存在しない）
ALTER TABLE bird_species
ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'gbif';

-- 既存レコードは全て GBIF 由来
UPDATE bird_species SET source = 'gbif' WHERE source = 'gbif';
