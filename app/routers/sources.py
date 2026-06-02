from fastapi import APIRouter, HTTPException

from app.schemas import SourceCreate, SourceDetail, SourceResponse
from app.services.vector_store import vector_store

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("", response_model=list[SourceDetail])
def list_sources(user_id: str | None = None) -> list[SourceDetail]:
    return [SourceDetail(**source) for source in vector_store.list_sources(user_id=user_id)]


@router.post("", response_model=SourceResponse)
def create_source(payload: SourceCreate) -> SourceResponse:
    source_id, chunk_count = vector_store.add_source(
        title=payload.title,
        transcript=payload.transcript,
        metadata={
            "audience": payload.audience,
            "platform": payload.platform,
            "tone": payload.tone,
            "goal": payload.goal,
            "user_id": payload.user_id or "",
        },
    )
    return SourceResponse(id=source_id, title=payload.title, chunk_count=chunk_count)


@router.get("/{source_id}", response_model=SourceDetail)
def get_source(source_id: str) -> SourceDetail:
    source = vector_store.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return SourceDetail(**source)
