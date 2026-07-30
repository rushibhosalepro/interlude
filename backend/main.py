from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from routes.backblaze import router as backblaze_router
from routes.projects import router as projects_router
from routes.samples import router as samples_router

import logging
import os
import uvicorn
import worker

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # one background worker for the whole process. do NOT run uvicorn with
    # --workers > 1: each process would get its own private queue.
    worker.start()
    yield
    await worker.stop()


# comma separated list, e.g. "http://localhost:3000,https://interlude.app"
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]
app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


URL_PREFIX = "/api"


app.include_router(router=backblaze_router, prefix=URL_PREFIX)
app.include_router(router=projects_router, prefix=URL_PREFIX)
app.include_router(router=samples_router, prefix=URL_PREFIX)


if __name__ == "__main__":
    # configurable because a killed uvicorn can leave an orphaned listener on
    # windows: the port still answers, from the old code, and a new server binds
    # alongside it but never receives traffic. moving port is the quick way out,
    # a reboot is the real fix. keep API_PORT in step with BUN_PUBLIC_API_URL.
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=int(os.getenv("API_PORT", "3001")),
        reload=True,
    )
