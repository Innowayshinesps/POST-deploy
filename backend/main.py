from dotenv import load_dotenv
load_dotenv()
import os
import logging
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


from routes.chat import router as chat_router
from routes.ghostscan import router as ghostscan_router
from routes.geocheck import router as geocheck_router



# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)-24s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("deploylens.main")

app = FastAPI(title="DeployLens API", version="1.1.0")

# ── CORS ──────────────────────────────────────────────────────────────────────
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
origins = ["*"] if allowed_origins_env == "*" else [o.strip() for o in allowed_origins_env.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(ghostscan_router)
app.include_router(geocheck_router)


@app.on_event("startup")
async def startup():
    logger.info("DeployLens API started — CORS origins: %s", origins)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "DeployLens", "version": "1.1.0"}
