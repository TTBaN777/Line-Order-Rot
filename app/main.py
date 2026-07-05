from fastapi import FastAPI
from app.routers import webhook
from app.models.database import init_db

app = FastAPI(title="LINE 點餐機器人")

# 啟動時建立資料表
@app.on_event("startup")
def startup():
    init_db()

app.include_router(webhook.router)

@app.get("/")
def health():
    return {"status": "ok"}
