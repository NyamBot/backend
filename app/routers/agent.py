from fastapi import APIRouter

from app.schemas import AgentChatRequest, AgentChatResponse
from app.services.agent import answer_agent_question
from app.services.vector_store import vector_store

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/chat", response_model=AgentChatResponse)
def chat(payload: AgentChatRequest) -> AgentChatResponse:
    context = vector_store.search(source_id=payload.source_id, query=payload.message, limit=4)
    return AgentChatResponse(answer=answer_agent_question(payload.message, context), context=context)
