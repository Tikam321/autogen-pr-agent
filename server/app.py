from fastapi import FastAPI
from server.webhook import router as webhook_router

app = FastAPI(title="PR Autogen Agent")
app.include_router(webhook_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
