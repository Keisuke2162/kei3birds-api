import base64
import io
import json
import uuid
from pathlib import Path

import anthropic
import boto3
from botocore.config import Config
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from PIL import Image

from app.auth import get_current_user_id
from app.config import get_settings, get_supabase
from app.models.schemas import IdentifyCandidate, IdentifyResponse, UploadPhotoResponse

router = APIRouter(prefix="/upload", tags=["upload"])

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png"}

IDENTIFY_PROMPT = """\
この画像に写っている鳥の種類を特定してください。
画像の中に小さく写っている場合も、拡大して注意深く観察し、体型・色・模様・くちばしの形などから判断してください。
候補を最大3つ、確信度（0〜1）とともに JSON 形式だけで返してください。
形式：{"candidates": [{"name_ja": "スズメ", "scientific_name": "Passer montanus", "confidence": 0.92}]}
判定できない場合は candidates を空配列にしてください。
JSON 以外のテキストは一切含めないでください。
"""


def _get_r2_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.cloudflare_r2_endpoint,
        aws_access_key_id=settings.cloudflare_r2_access_key,
        aws_secret_access_key=settings.cloudflare_r2_secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


@router.post("/photo", response_model=UploadPhotoResponse)
async def upload_photo(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    """画像を Cloudflare R2 にアップロードして公開 URL を返す。"""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="JPEG または PNG のみ対応しています")

    settings = get_settings()
    ext = Path(file.filename or "photo.jpg").suffix or ".jpg"
    key = f"{user_id}/{uuid.uuid4()}{ext}"

    contents = await file.read()
    r2 = _get_r2_client()
    r2.put_object(
        Bucket=settings.cloudflare_r2_bucket,
        Key=key,
        Body=contents,
        ContentType=file.content_type,
    )

    public_url = f"{settings.cloudflare_r2_public_url}/{key}"
    return UploadPhotoResponse(url=public_url)


@router.post("/identify", response_model=IdentifyResponse)
async def identify_bird(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    """画像を Claude Vision API に送信して鳥の種類を判定する。"""
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="JPEG または PNG のみ対応しています")

    settings = get_settings()
    contents = await file.read()

    # Claude API の 5MB 制限に収まるようリサイズ
    MAX_IMAGE_BYTES = 4_000_000  # 余裕を持って4MB
    if len(contents) > MAX_IMAGE_BYTES:
        img = Image.open(io.BytesIO(contents))
        img_format = "JPEG" if file.content_type == "image/jpeg" else "PNG"
        for max_dim, quality in [(2000, 85), (1600, 75), (1200, 65)]:
            img_copy = img.copy()
            img_copy.thumbnail((max_dim, max_dim), Image.LANCZOS)
            buf = io.BytesIO()
            img_copy.save(buf, format=img_format, quality=quality)
            contents = buf.getvalue()
            if len(contents) <= MAX_IMAGE_BYTES:
                break

    media_type = file.content_type  # "image/jpeg" or "image/png"
    image_b64 = base64.standard_b64encode(contents).decode("utf-8")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": IDENTIFY_PROMPT},
                    ],
                }
            ],
        )
    except anthropic.APIError as e:
        print(f"[identify] Claude API error: {e}")
        return IdentifyResponse(identified=False, candidates=[])

    raw_text = message.content[0].text.strip()
    # Claude が ```json ... ``` で囲むことがあるので除去する
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw_text = "\n".join(lines).strip()
    try:
        parsed = json.loads(raw_text)
        raw_candidates: list[dict] = parsed.get("candidates", [])
    except json.JSONDecodeError:
        raw_candidates = []

    # 1. bird_species (GBIF) で学名照合 → マッチすれば species_id + DB側 name_ja を使用
    # 2. マッチしなければ ai_species で学名照合 → あればその ai_species_id + name_ja を使用
    # 3. どちらにもなければ ai_species に新規登録して ai_species_id を返す
    supabase = get_supabase()
    candidates: list[IdentifyCandidate] = []
    for c in raw_candidates:
        species_id = None
        ai_species_id = None
        scientific_name = c.get("scientific_name", "")
        name_ja = c.get("name_ja", "")

        if scientific_name:
            # 1. bird_species (GBIF) を検索
            res = (
                supabase.table("bird_species")
                .select("id, name_ja")
                .eq("scientific_name", scientific_name)
                .limit(1)
                .execute()
            )
            if res.data:
                species_id = res.data[0]["id"]
                db_name_ja = res.data[0].get("name_ja")
                if db_name_ja:
                    name_ja = db_name_ja
            else:
                # 2. ai_species を検索
                ai_res = (
                    supabase.table("ai_species")
                    .select("id, name_ja")
                    .eq("scientific_name", scientific_name)
                    .limit(1)
                    .execute()
                )
                if ai_res.data:
                    ai_species_id = ai_res.data[0]["id"]
                    name_ja = ai_res.data[0]["name_ja"]
                else:
                    # 3. ai_species に新規登録
                    try:
                        insert_res = (
                            supabase.table("ai_species")
                            .insert({"scientific_name": scientific_name, "name_ja": name_ja})
                            .execute()
                        )
                        if insert_res.data:
                            ai_species_id = insert_res.data[0]["id"]
                    except Exception as e:
                        print(f"[identify] Failed to register ai_species: {e}")

        candidates.append(
            IdentifyCandidate(
                species_id=species_id,
                ai_species_id=ai_species_id,
                name_ja=name_ja,
                scientific_name=c.get("scientific_name"),
                confidence=float(c.get("confidence", 0)),
            )
        )

    identified = bool(candidates) and candidates[0].confidence >= 0.5
    return IdentifyResponse(identified=identified, candidates=candidates)
