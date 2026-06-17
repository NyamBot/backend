from __future__ import annotations

from enum import Enum
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class ErrorCode(str, Enum):
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    INVALID_TOKEN = "INVALID_TOKEN"
    INVALID_TOKEN_SUBJECT = "INVALID_TOKEN_SUBJECT"
    ADMIN_REQUIRED = "ADMIN_REQUIRED"
    USER_NOT_FOUND = "USER_NOT_FOUND"
    RESTAURANT_NOT_FOUND = "RESTAURANT_NOT_FOUND"
    CHAT_SESSION_NOT_FOUND = "CHAT_SESSION_NOT_FOUND"
    INVALID_AUTH_CODE = "INVALID_AUTH_CODE"
    AUTH_PROVIDER_ERROR = "AUTH_PROVIDER_ERROR"
    KAKAO_LOCAL_ERROR = "KAKAO_LOCAL_ERROR"
    MISSING_CANCEL_TARGET = "MISSING_CANCEL_TARGET"
    LEGACY_CHAT_SESSION_DELETE_FORBIDDEN = "LEGACY_CHAT_SESSION_DELETE_FORBIDDEN"
    UNSUPPORTED_LEVEL_EVENT = "UNSUPPORTED_LEVEL_EVENT"

    @property
    def default_message(self) -> str:
        return {
            ErrorCode.LOGIN_REQUIRED: "로그인이 필요합니다.",
            ErrorCode.INVALID_TOKEN: "로그인이 만료되었거나 토큰이 올바르지 않습니다.",
            ErrorCode.INVALID_TOKEN_SUBJECT: "토큰 사용자 정보가 올바르지 않습니다.",
            ErrorCode.ADMIN_REQUIRED: "관리자 권한이 필요합니다.",
            ErrorCode.USER_NOT_FOUND: "사용자를 찾을 수 없습니다.",
            ErrorCode.RESTAURANT_NOT_FOUND: "맛집을 찾을 수 없습니다.",
            ErrorCode.CHAT_SESSION_NOT_FOUND: "채팅 세션을 찾을 수 없습니다.",
            ErrorCode.INVALID_AUTH_CODE: "인증 코드가 만료되었거나 올바르지 않습니다.",
            ErrorCode.AUTH_PROVIDER_ERROR: "외부 인증 처리에 실패했습니다.",
            ErrorCode.KAKAO_LOCAL_ERROR: "카카오 장소 검색 처리에 실패했습니다.",
            ErrorCode.MISSING_CANCEL_TARGET: "중지할 채팅 요청 정보가 필요합니다.",
            ErrorCode.LEGACY_CHAT_SESSION_DELETE_FORBIDDEN: "이전 채팅 기록은 여기서 삭제할 수 없습니다.",
            ErrorCode.UNSUPPORTED_LEVEL_EVENT: "지원하지 않는 레벨 이벤트입니다.",
        }[self]


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        status_code: int,
        *,
        message: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message or code.default_message
        self.status_code = status_code
        self.extra = extra or {}
        super().__init__(self.message)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    _ = request
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.message,
            "error": {
                "code": exc.code.value,
                "message": exc.message,
                **exc.extra,
            },
        },
    )
