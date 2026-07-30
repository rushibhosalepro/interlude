from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from routes.backblaze import router as backblaze_router

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


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=3001, reload=True)
