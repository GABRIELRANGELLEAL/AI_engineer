import logging
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.api.routes import keys, documents, question, stats

settings = get_settings()


def _configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(message)s",
    )
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


_configure_logging()

app = FastAPI(
    title="RAG PDF Q&A",
    description="Sistema de perguntas e respostas sobre documentos PDF usando RAG",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(keys.router, tags=["keys"])
app.include_router(documents.router, tags=["documents"])
app.include_router(question.router, tags=["question"])
app.include_router(stats.router, tags=["stats"])


@app.get("/health")
async def health():
    return {"status": "healthy"}


static_dir = Path(__file__).resolve().parent.parent / "static"
if static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True))
