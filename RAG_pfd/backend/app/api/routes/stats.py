from fastapi import APIRouter, Depends

from app.api.dependencies import get_vector_store
from app.store.vector_store import VectorStore

router = APIRouter()


@router.get("/stats")
async def get_stats(
    vector_store: VectorStore = Depends(get_vector_store),
):
    return vector_store.get_stats()
