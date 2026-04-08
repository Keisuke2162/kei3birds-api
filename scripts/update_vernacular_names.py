"""
bird_species テーブルの name_ja / name_en を GBIF Vernacular Names API から取得して更新する。

GBIF API: https://api.gbif.org/v1/species/{taxonKey}/vernacularNames

使用方法:
    python scripts/update_vernacular_names.py
"""

import logging
import os
import sys
import time

import httpx
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def get_supabase_client():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY")
    if not url or not key:
        logger.error("SUPABASE_URL and SUPABASE_SECRET_KEY must be set")
        sys.exit(1)
    return create_client(url, key)


def fetch_vernacular_names(taxon_key: int) -> dict[str, str]:
    """GBIF APIから日本語名・英語名を取得する。"""
    url = f"https://api.gbif.org/v1/species/{taxon_key}/vernacularNames"
    try:
        response = httpx.get(url, timeout=15)
        response.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning(f"  taxon_key={taxon_key}: API error: {e}")
        return {}

    data = response.json()
    results = data.get("results", [])

    names = {}
    for entry in results:
        lang = entry.get("language", "")
        name = entry.get("vernacularName", "")
        if not name:
            continue
        # 日本語名
        if lang == "jpn" and "name_ja" not in names:
            names["name_ja"] = name
        elif lang == "ja" and "name_ja" not in names:
            names["name_ja"] = name
        # 英語名
        elif lang == "eng" and "name_en" not in names:
            names["name_en"] = name
        elif lang == "en" and "name_en" not in names:
            names["name_en"] = name

    return names


def main():
    logger.info("=== bird_species 日本語名・英語名 更新バッチ 開始 ===")
    supabase = get_supabase_client()

    # name_ja が空のレコードを取得
    result = (
        supabase.table("bird_species")
        .select("id, gbif_taxon_key, scientific_name, name_ja, name_en")
        .or_("name_ja.eq.,name_ja.is.null")
        .order("id")
        .execute()
    )
    species_list = result.data
    logger.info(f"更新対象: {len(species_list)}件")

    updated = 0
    skipped = 0
    errors = 0

    for i, species in enumerate(species_list):
        taxon_key = species.get("gbif_taxon_key")
        if not taxon_key:
            skipped += 1
            continue

        names = fetch_vernacular_names(taxon_key)

        if not names:
            skipped += 1
            if (i + 1) % 50 == 0:
                logger.info(f"  進捗: {i + 1}/{len(species_list)} (updated={updated}, skipped={skipped})")
            time.sleep(0.3)
            continue

        update_data = {}
        if "name_ja" in names:
            update_data["name_ja"] = names["name_ja"]
        if "name_en" in names:
            update_data["name_en"] = names["name_en"]

        if update_data:
            try:
                supabase.table("bird_species").update(update_data).eq("id", species["id"]).execute()
                updated += 1
            except Exception as e:
                logger.error(f"  id={species['id']}: update error: {e}")
                errors += 1

        if (i + 1) % 50 == 0:
            logger.info(f"  進捗: {i + 1}/{len(species_list)} (updated={updated}, skipped={skipped})")

        # レート制限対応
        time.sleep(0.3)

    logger.info("=== バッチ完了 ===")
    logger.info(f"  更新: {updated}件")
    logger.info(f"  スキップ: {skipped}件")
    logger.info(f"  エラー: {errors}件")


if __name__ == "__main__":
    main()
