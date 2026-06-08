from fastapi import APIRouter

from app.schemas import ClipGenerateRequest, ClipIdeasResponse, ScriptPack, ScriptRequest
from app.services.agent import build_retrieval_query, generate_clip_ideas, generate_script_pack
from app.services.vector_store import vector_store

router = APIRouter(prefix="/api/clips", tags=["clips"])


@router.post("/generate", response_model=ClipIdeasResponse)
def generate_clips(payload: ClipGenerateRequest) -> ClipIdeasResponse:
    query = build_retrieval_query(
        platform=payload.platform,
        audience=payload.audience,
        goal=payload.goal,
    )
    context = vector_store.search(source_id=payload.source_id, query=query, limit=5)
    ideas = generate_clip_ideas(
        source_id=payload.source_id,
        title=payload.title,
        context=context,
        platform=payload.platform,
        audience=payload.audience,
        goal=payload.goal,
        count=payload.count,
    )
    return ClipIdeasResponse(source_id=payload.source_id, ideas=ideas)


@router.post("/script", response_model=ScriptPack)
def generate_script(payload: ScriptRequest) -> ScriptPack:
    return generate_script_pack(payload.idea)
