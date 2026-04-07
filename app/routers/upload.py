import base64
import json
import uuid
from pathlib import Path

import anthropic
import boto3
from botocore.config import Config
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from app.auth import get_current_user_id
from app.config import get_settings, get_supabase
from app.models.schemas import IdentifyCandidate, IdentifyResponse, UploadPhotoResponse

router = APIRouter(prefix="/upload", tags=["upload"])

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png"}

IDENTIFY_PROMPT = """\
この画像に写っている鳥の種類を日本産鳥類から特定してください。
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

    public_url = f"{settings.cloudflare_r2_endpoint}/{settings.cloudflare_r2_bucket}/{key}"
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

    media_type = file.content_type  # "image/jpeg" or "image/png"
    image_b64 = base64.standard_b64encode(contents).decode("utf-8")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
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

    raw_text = message.content[0].text.strip()
    try:
        parsed = json.loads(raw_text)
        raw_candidates: list[dict] = parsed.get("candidates", [])
    except json.JSONDecodeError:
        raw_candidates = []

    # bird_species テーブルで species_id を解決する
    supabase = get_supabase()
    candidates: list[IdentifyCandidate] = []
    for c in raw_candidates:
        species_id = None
        name_ja = c.get("name_ja", "")
        if name_ja:
            res = (
                supabase.table("bird_species")
                .select("id")
                .eq("name_ja", name_ja)
                .limit(1)
                .execute()
            )
            if res.data:
                species_id = res.data[0]["id"]

        candidates.append(
            IdentifyCandidate(
                species_id=species_id,
                name_ja=name_ja,
                scientific_name=c.get("scientific_name"),
                confidence=float(c.get("confidence", 0)),
            )
        )

    identified = bool(candidates) and candidates[0].confidence >= 0.5
    return IdentifyResponse(identified=identified, candidates=candidates)
