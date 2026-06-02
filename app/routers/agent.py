from fastapi import APIRouter

from app.schemas import AgentChatRequest, AgentChatResponse, AgentMessagesResponse
from app.services.agent import answer_agent_question
from app.services.vector_store import vector_store

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/chat", response_model=AgentChatResponse)
def chat(payload: AgentChatRequest) -> AgentChatResponse:
    context = vector_store.search(source_id=payload.source_id, query=payload.message, limit=4)
    answer = answer_agent_question(payload.message, context)
    vector_store.save_agent_message(
        source_id=payload.source_id,
        role="user",
        content=payload.message,
        retrieved_context=[],
    )
    vector_store.save_agent_message(
        source_id=payload.source_id,
        role="assistant",
        content=answer,
        retrieved_context=context,
    )
    return AgentChatResponse(answer=answer, context=context)


@router.get("/messages", response_model=AgentMessagesResponse)
def list_messages(source_id: str) -> AgentMessagesResponse:
    messages = vector_store.list_agent_messages(source_id=source_id)
    return AgentMessagesResponse(source_id=source_id, messages=messages)
