"""
bird_species テーブルの name_ja が空のレコードに対し、
Claude API で英語名・学名から日本語名を取得して更新する。

使用方法:
    python scripts/translate_bird_names.py
"""

import json
import logging
import os
import sys

import anthropic
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 50  # 1回のClaude API呼び出しで処理する件数


def get_supabase_client():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY")
    if not url or not key:
        logger.error("SUPABASE_URL and SUPABASE_SECRET_KEY must be set")
        sys.exit(1)
    return create_client(url, key)


def translate_batch(client: anthropic.Anthropic, birds: list[dict]) -> dict[int, str]:
    """Claude APIで英語名・学名から日本語名を一括取得する。"""
    bird_list = "\n".join(
        f"- id={b['id']}, name_en=\"{b['name_en']}\", scientific_name=\"{b['scientific_name']}\""
        for b in birds
    )

    prompt = f"""以下の鳥の日本語名（和名）を返してください。
日本の野鳥図鑑で使われる標準和名を使ってください。
わからない場合は英語名をカタカナ表記してください。

JSON形式で返してください。形式: {{"results": [{{"id": 1, "name_ja": "スズメ"}}]}}
JSON以外のテキストは一切含めないでください。

{bird_list}"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = message.content[0].text.strip()
    # ```json ... ``` 囲みを除去
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw_text = "\n".join(lines).strip()

    try:
        parsed = json.loads(raw_text)
        results = parsed.get("results", [])
        return {r["id"]: r["name_ja"] for r in results if r.get("name_ja")}
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"JSON parse error: {e}")
        logger.error(f"Raw response: {raw_text[:500]}")
        return {}


def main():
    logger.info("=== bird_species 日本語名翻訳バッチ 開始 ===")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY must be set")
        sys.exit(1)

    supabase = get_supabase_client()
    claude = anthropic.Anthropic(api_key=api_key)

    # name_ja が空で name_en がある（翻訳元がある）レコードを取得
    result = (
        supabase.table("bird_species")
        .select("id, name_en, scientific_name, name_ja")
        .eq("name_ja", "")
        .neq("name_en", "")
        .order("id")
        .execute()
    )
    birds = result.data
    logger.info(f"翻訳対象: {len(birds)}件")

    total_updated = 0
    total_errors = 0

    for i in range(0, len(birds), BATCH_SIZE):
        batch = birds[i:i + BATCH_SIZE]
        logger.info(f"バッチ {i // BATCH_SIZE + 1}: {len(batch)}件を翻訳中...")

        try:
            translations = translate_batch(claude, batch)
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            total_errors += len(batch)
            continue

        for bird_id, name_ja in translations.items():
            try:
                supabase.table("bird_species").update({"name_ja": name_ja}).eq("id", bird_id).execute()
                total_updated += 1
            except Exception as e:
                logger.error(f"  id={bird_id}: update error: {e}")
                total_errors += 1

        logger.info(f"  翻訳完了: {len(translations)}件更新")

    logger.info("=== バッチ完了 ===")
    logger.info(f"  更新: {total_updated}件")
    logger.info(f"  エラー: {total_errors}件")


if __name__ == "__main__":
    main()
