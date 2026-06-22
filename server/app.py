import logging

from fastapi import FastAPI
from server.webhook import router as webhook_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI(title="PR Autogen Agent")
app.include_router(webhook_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
