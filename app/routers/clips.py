from fastapi import APIRouter

from app.schemas import ClipGenerateRequest, ClipIdea, ClipIdeasResponse, ScriptPack, ScriptRequest
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
    ideas = vector_store.save_clip_ideas(payload.source_id, ideas)
    return ClipIdeasResponse(source_id=payload.source_id, ideas=ideas)


@router.get("", response_model=ClipIdeasResponse)
def list_clips(source_id: str) -> ClipIdeasResponse:
    ideas: list[ClipIdea] = vector_store.list_clip_ideas(source_id)
    return ClipIdeasResponse(source_id=source_id, ideas=ideas)


@router.post("/script", response_model=ScriptPack)
def generate_script(payload: ScriptRequest) -> ScriptPack:
    pack = generate_script_pack(payload.idea)
    return vector_store.save_campaign_pack(
        source_id=payload.source_id,
        clip_idea_id=payload.idea.id,
        pack=pack,
    )


@router.get("/packs", response_model=list[ScriptPack])
def list_campaign_packs(source_id: str, clip_idea_id: str | None = None) -> list[ScriptPack]:
    return vector_store.list_campaign_packs(source_id=source_id, clip_idea_id=clip_idea_id)
