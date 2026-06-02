from fastapi import APIRouter

from app.schemas import ClipIdeasResponse, ScriptPack, ScriptRequest
from app.services.agent import generate_clip_ideas, generate_script_pack
from app.services.vector_store import vector_store

router = APIRouter(prefix="/api/clips", tags=["clips"])


@router.post("/generate", response_model=ClipIdeasResponse)
def generate_clips(source_id: str, title: str = "Untitled source", platform: str = "shorts") -> ClipIdeasResponse:
    context = vector_store.search(source_id=source_id, query="best insight hook lesson story", limit=5)
    ideas = generate_clip_ideas(source_id=source_id, title=title, context=context, platform=platform)
    return ClipIdeasResponse(source_id=source_id, ideas=ideas)


@router.post("/script", response_model=ScriptPack)
def generate_script(payload: ScriptRequest) -> ScriptPack:
    return generate_script_pack(payload.idea)
