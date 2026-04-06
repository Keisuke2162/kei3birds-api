from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import birds, map, observations, upload

app = FastAPI(
    title="kei3birds API",
    description="日本の野鳥図鑑アプリ kei3birds のバックエンド API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(birds.router)
app.include_router(map.router)
app.include_router(observations.router)
app.include_router(upload.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
