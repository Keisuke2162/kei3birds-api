"""
JWT検証モジュール
Supabase の JWKSエンドポイントから公開鍵を取得してトークンを検証する。
"""
import httpx
import jwt
from functools import lru_cache
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.algorithms import RSAAlgorithm, ECAlgorithm

from app.config import get_settings

bearer_scheme = HTTPBearer()


@lru_cache(maxsize=1)
def _fetch_jwks() -> dict:
    """JWKSエンドポイントから公開鍵セットを取得してキャッシュする。"""
    settings = get_settings()
    url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    response = httpx.get(url, timeout=10)
    response.raise_for_status()
    return response.json()


def _get_public_key(kid: str, alg: str):
    """kid に一致する JWK から公開鍵オブジェクトを返す。"""
    jwks = _fetch_jwks()
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            if alg.startswith("ES"):
                return ECAlgorithm.from_jwk(key)
            else:
                return RSAAlgorithm.from_jwk(key)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Matching public key not found in JWKS",
    )


def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    """
    Authorization: Bearer <token> を検証し、JWTペイロードを返す。
    検証に失敗した場合は 401 を返す。
    """
    token = credentials.credentials
    try:
        # kid を取得してから対応する公開鍵で検証
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        alg = unverified_header.get("alg", "RS256")
        public_key = _get_public_key(kid, alg)

        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256", "ES256"],
            options={"verify_aud": False},
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )


def get_raw_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str:
    """生のアクセストークン文字列を返す。"""
    return credentials.credentials


def get_current_user_id(payload: dict = Depends(verify_token)) -> str:
    """JWTペイロードから Supabase の user_id (sub) を取り出す。"""
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user_id not found in token",
        )
    return user_id
