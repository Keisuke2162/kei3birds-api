"""
GBIF日本産鳥類観察データ取得バッチスクリプト

GBIF APIから日本の鳥類観察記録を取得し、Supabaseに保存する。
- bird_species テーブルに新種を登録（upsert）
- gbif_observations テーブルに観察記録を登録（upsert）

使用方法:
    python scripts/fetch_gbif_data.py
"""

import logging
import os
import sys
import time
from datetime import datetime

import httpx
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

GBIF_API_URL = "https://api.gbif.org/v1/occurrence/search"
GBIF_PARAMS = {
    "country": "JP",
    "classKey": 212,  # Aves (鳥類)
    "hasCoordinate": "true",
    "basisOfRecord": "HUMAN_OBSERVATION",
    "limit": 300,
}

# eventDateの月から季節を判定
MONTH_TO_SEASON = {
    1: "winter", 2: "winter", 3: "spring",
    4: "spring", 5: "spring", 6: "summer",
    7: "summer", 8: "summer", 9: "autumn",
    10: "autumn", 11: "autumn", 12: "winter",
}


def get_supabase_client():
    url = os.environ.get("SUPABASE_URL")
    # バッチスクリプトではRLSをバイパスするためSecret API Keyを使用
    # bird_species, gbif_observations はRLSで読み取り専用のため、
    # Publishable Key ではINSERTできない
    key = os.environ.get("SUPABASE_SECRET_KEY")
    if not url or not key:
        logger.error("SUPABASE_URL and SUPABASE_SECRET_KEY must be set")
        sys.exit(1)
    return create_client(url, key)


def parse_season(event_date: str | None) -> str | None:
    """eventDateから季節を判定する"""
    if not event_date:
        return None
    try:
        dt = datetime.fromisoformat(event_date.replace("Z", "+00:00"))
        return MONTH_TO_SEASON.get(dt.month)
    except (ValueError, AttributeError):
        # "2024-03-15" のような日付のみの場合
        try:
            dt = datetime.strptime(event_date[:10], "%Y-%m-%d")
            return MONTH_TO_SEASON.get(dt.month)
        except (ValueError, AttributeError):
            return None


def parse_observed_at(event_date: str | None) -> str | None:
    """eventDateをdate文字列に変換する"""
    if not event_date:
        return None
    try:
        return event_date[:10]
    except (TypeError, IndexError):
        return None


def fetch_gbif_occurrences(offset: int = 0) -> dict:
    """GBIF APIから観察記録を1ページ分取得する"""
    params = {**GBIF_PARAMS, "offset": offset}
    response = httpx.get(GBIF_API_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def upsert_species(supabase, species_map: dict[int, dict]) -> dict[int, int]:
    """
    bird_speciesテーブルに種を登録/更新する。
    Returns: {gbif_taxon_key: species_id} のマッピング
    """
    if not species_map:
        return {}

    taxon_keys = list(species_map.keys())

    # 既存の種を取得
    existing = (
        supabase.table("bird_species")
        .select("id, gbif_taxon_key")
        .in_("gbif_taxon_key", taxon_keys)
        .execute()
    )
    existing_map = {row["gbif_taxon_key"]: row["id"] for row in existing.data}

    # 新規の種だけ登録
    new_species = []
    for taxon_key, info in species_map.items():
        if taxon_key not in existing_map:
            new_species.append({
                "name_ja": info.get("name_ja", ""),
                "name_en": info.get("name_en", ""),
                "scientific_name": info["scientific_name"],
                "family": info.get("family", ""),
                "order_name": info.get("order_name", ""),
                "gbif_taxon_key": taxon_key,
                "source": "gbif",
            })

    if new_species:
        result = (
            supabase.table("bird_species")
            .insert(new_species)
            .execute()
        )
        for row in result.data:
            existing_map[row["gbif_taxon_key"]] = row["id"]
        logger.info(f"  新規種登録: {len(new_species)}件")

    return existing_map


def upsert_observations(supabase, observations: list[dict]) -> tuple[int, int]:
    """
    gbif_observationsテーブルに観察記録をupsertする。
    Returns: (inserted_count, skipped_count)
    """
    if not observations:
        return 0, 0

    # 既存のoccurrence_keyを取得してスキップ判定
    occurrence_keys = [obs["gbif_occurrence_key"] for obs in observations]
    existing = (
        supabase.table("gbif_observations")
        .select("gbif_occurrence_key")
        .in_("gbif_occurrence_key", occurrence_keys)
        .execute()
    )
    existing_keys = {row["gbif_occurrence_key"] for row in existing.data}

    new_observations = [
        obs for obs in observations
        if obs["gbif_occurrence_key"] not in existing_keys
    ]
    skipped = len(observations) - len(new_observations)

    if new_observations:
        # Supabaseのinsertは一度に大量のデータを送ると失敗する可能性があるため
        # 100件ずつに分割して送信
        batch_size = 100
        inserted = 0
        for i in range(0, len(new_observations), batch_size):
            batch = new_observations[i : i + batch_size]
            supabase.table("gbif_observations").insert(batch).execute()
            inserted += len(batch)
        return inserted, skipped

    return 0, skipped


def main():
    logger.info("=== GBIF日本産鳥類データ取得バッチ 開始 ===")
    supabase = get_supabase_client()

    offset = 0
    total_fetched = 0
    total_inserted = 0
    total_skipped = 0
    total_species_new = 0
    total_errors = 0

    while True:
        try:
            logger.info(f"GBIF API取得中... offset={offset}")
            data = fetch_gbif_occurrences(offset)
        except httpx.HTTPError as e:
            logger.error(f"GBIF APIリクエストエラー: {e}")
            total_errors += 1
            break

        results = data.get("results", [])
        if not results:
            logger.info("取得データなし。終了します。")
            break

        total_fetched += len(results)
        end_of_records = data.get("endOfRecords", True)

        # 種情報を収集
        species_map: dict[int, dict] = {}
        for record in results:
            taxon_key = record.get("speciesKey")
            if taxon_key and taxon_key not in species_map:
                species_map[taxon_key] = {
                    "scientific_name": record.get("species", ""),
                    "name_en": record.get("vernacularName", ""),
                    "name_ja": "",  # GBIF APIには日本語名がないため空
                    "family": record.get("family", ""),
                    "order_name": record.get("order", ""),
                }

        # 種をupsert
        try:
            before_count = len(species_map)
            taxon_to_id = upsert_species(supabase, species_map)
        except Exception as e:
            logger.error(f"種登録エラー: {e}")
            total_errors += 1
            if end_of_records:
                break
            offset += GBIF_PARAMS["limit"]
            time.sleep(1)
            continue

        # 観察記録を組み立て
        observations = []
        for record in results:
            taxon_key = record.get("speciesKey")
            if not taxon_key or taxon_key not in taxon_to_id:
                continue

            lat = record.get("decimalLatitude")
            lng = record.get("decimalLongitude")
            if lat is None or lng is None:
                continue

            event_date = record.get("eventDate")
            observed_at = parse_observed_at(event_date)
            season = parse_season(event_date)

            observations.append({
                "gbif_occurrence_key": record["gbifID"],
                "species_id": taxon_to_id[taxon_key],
                "observed_at": observed_at,
                "location": f"POINT({lng} {lat})",
                "prefecture": record.get("stateProvince", ""),
                "season": season,
            })

        # 観察記録をupsert
        try:
            inserted, skipped = upsert_observations(supabase, observations)
            total_inserted += inserted
            total_skipped += skipped
            logger.info(
                f"  取得: {len(results)}件, "
                f"登録: {inserted}件, スキップ: {skipped}件"
            )
        except Exception as e:
            logger.error(f"観察記録登録エラー: {e}")
            total_errors += 1

        if end_of_records:
            logger.info("全レコード取得完了。")
            break

        offset += GBIF_PARAMS["limit"]
        # レート制限対応：1秒スリープ
        time.sleep(1)

    logger.info("=== バッチ完了 ===")
    logger.info(f"  総取得件数:   {total_fetched}")
    logger.info(f"  総登録件数:   {total_inserted}")
    logger.info(f"  総スキップ:   {total_skipped}")
    logger.info(f"  エラー件数:   {total_errors}")


if __name__ == "__main__":
    main()
