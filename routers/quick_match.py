import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.security import require_user
from models.user import User

from schemas.quick_match.request import (
    QuickMatchCreateRequest,
    QuickMatchCancelRequest,
    QuickMatchRetryRequest,
)
from schemas.quick_match.response import (
    QuickMatchCreateResponse,
    QuickMatchDetailResponse,
    QuickMatchRequestResponse,
    QuickMatchResultResponse,
    QuickMatchCandidateResponse,
)

from services.quick_match.quick_match_service import QuickMatchService
from models.quick_match.request import QuickMatchRequest, QuickMatchRequestStatus


router = APIRouter(
    prefix="/quick-match",
    tags=["Quick Match"],
)

quick_match_service = QuickMatchService()

error_map = {
    "USER_NOT_FOUND": (404, "사용자를 찾을 수 없습니다."),
    "USER_INACTIVE": (403, "비활성 사용자입니다."),
    "USER_BANNED": (403, "정지된 사용자입니다."),
    "ALREADY_REQUESTED": (409, "이미 진행 중인 빠른매칭 요청이 있습니다."),
    "GPU_EMBEDDING_CONNECT_TIMEOUT": (504, "임베딩 서버 연결 시간이 초과되었습니다."),
    "GPU_EMBEDDING_CONNECT_ERROR": (502, "임베딩 서버에 연결할 수 없습니다."),
    "GPU_EMBEDDING_HTTP_ERROR": (502, "임베딩 서버가 오류 응답을 반환했습니다."),
}
@router.post(
    "",
    response_model=QuickMatchCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_quick_match_request(
    payload: QuickMatchCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    try:
        request = await quick_match_service.create_request(
            db=db,
            user_id=current_user.id,
            service_id=payload.service_id,
            preferred_conditions=payload.preferred_conditions,
        )

        return QuickMatchCreateResponse(
            message="빠른매칭 요청이 생성되었습니다.",
            request_id=request.id,
            status=request.status.value if hasattr(request.status, "value") else str(request.status),
        )

    except Exception as e:
        error_map = {
            "USER_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "사용자를 찾을 수 없습니다."),
            "USER_INACTIVE": (status.HTTP_403_FORBIDDEN, "비활성 사용자입니다."),
            "USER_BANNED": (status.HTTP_403_FORBIDDEN, "정지된 사용자입니다."),
            "ALREADY_REQUESTED": (status.HTTP_409_CONFLICT, "이미 진행 중인 빠른매칭 요청이 있습니다."),
        }
        code, message = error_map.get(str(e), (status.HTTP_400_BAD_REQUEST, str(e)))
        raise HTTPException(status_code=code, detail=message)


@router.post(
    "/{request_id}/candidates",
    response_model=list[QuickMatchCandidateResponse],
    status_code=status.HTTP_200_OK,
)
async def generate_quick_match_candidates(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    try:
        return await quick_match_service.find_candidates(
            db=db,
            request_id=request_id,
        )
    except Exception as e:
        error_map = {
            "REQUEST_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "빠른매칭 요청을 찾을 수 없습니다."),
            "INVALID_REQUEST_STATUS": (status.HTTP_400_BAD_REQUEST, "요청 상태가 올바르지 않습니다."),
            "NO_RECRUITING_PARTY": (status.HTTP_404_NOT_FOUND, "모집 중인 파티가 없습니다."),
        }
        code, message = error_map.get(str(e), (status.HTTP_400_BAD_REQUEST, str(e)))
        raise HTTPException(status_code=code, detail=message)


@router.post(
    "/{request_id}/select",
    response_model=QuickMatchResultResponse,
    status_code=status.HTTP_200_OK,
)
async def select_quick_match_party(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    try:
        return await quick_match_service.select_party(
            db=db,
            request_id=request_id,
        )
    except Exception as e:
        error_map = {
            "NO_CANDIDATE": (status.HTTP_404_NOT_FOUND, "선택 가능한 후보가 없습니다."),
            "REQUEST_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "빠른매칭 요청을 찾을 수 없습니다."),
            "PARTY_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "파티를 찾을 수 없습니다."),
            "PARTY_STATUS_CHANGED": (status.HTTP_409_CONFLICT, "파티 상태가 변경되었습니다."),
            "PARTY_FULL": (status.HTTP_409_CONFLICT, "파티 정원이 마감되었습니다."),
        }
        code, message = error_map.get(str(e), (status.HTTP_400_BAD_REQUEST, str(e)))
        raise HTTPException(status_code=code, detail=message)


@router.post(
    "/{request_id}/join",
    status_code=status.HTTP_200_OK,
)
async def join_quick_match_party(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    request = await db.get(QuickMatchRequest, request_id)

    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="빠른매칭 요청을 찾을 수 없습니다.",
        )

    if request.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인 요청만 처리할 수 있습니다.",
        )

    try:
        return await quick_match_service.join_party(
            db=db,
            request_id=request_id,
        )
    except RuntimeError as e:
        if str(e) == "LOCK_NOT_ACQUIRED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="동시 처리 중입니다. 잠시 후 다시 시도해주세요.",
            )
        raise
    except Exception as e:
        error_map = {
            "REQUEST_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "빠른매칭 요청을 찾을 수 없습니다."),
            "REQUEST_NOT_MATCHED": (status.HTTP_400_BAD_REQUEST, "아직 매칭 완료 상태가 아닙니다."),
            "MATCHED_PARTY_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "매칭된 파티가 없습니다."),
            "PARTY_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "파티를 찾을 수 없습니다."),
            "PARTY_STATUS_CHANGED": (status.HTTP_409_CONFLICT, "파티 상태가 변경되었습니다."),
            "PARTY_FULL": (status.HTTP_409_CONFLICT, "파티 정원이 마감되었습니다."),
            "ALREADY_JOINED": (status.HTTP_409_CONFLICT, "이미 참여 중인 파티입니다."),
        }
        code, message = error_map.get(str(e), (status.HTTP_400_BAD_REQUEST, str(e)))
        raise HTTPException(status_code=code, detail=message)


@router.post(
    "/{request_id}/cancel",
    response_model=QuickMatchRequestResponse,
    status_code=status.HTTP_200_OK,
)
async def cancel_quick_match_request(
    request_id: uuid.UUID,
    payload: QuickMatchCancelRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    request = await db.get(QuickMatchRequest, request_id)

    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="빠른매칭 요청을 찾을 수 없습니다.",
        )

    if request.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인 요청만 취소할 수 있습니다.",
        )

    if request.status in {
        QuickMatchRequestStatus.MATCHED,
        QuickMatchRequestStatus.FAILED,
        QuickMatchRequestStatus.EXPIRED,
        QuickMatchRequestStatus.CANCELLED,
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 종료된 요청입니다.",
        )

    request.status = QuickMatchRequestStatus.CANCELLED
    request.fail_reason = payload.reason
    request.cancelled_at = datetime.utcnow()
    request.is_active = False

    await db.commit()
    await db.refresh(request)

    return request


@router.post(
    "/{request_id}/retry",
    response_model=QuickMatchRequestResponse,
    status_code=status.HTTP_200_OK,
)
async def retry_quick_match_request(
    request_id: uuid.UUID,
    payload: QuickMatchRetryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    request = await db.get(QuickMatchRequest, request_id)

    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="빠른매칭 요청을 찾을 수 없습니다.",
        )

    if request.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인 요청만 재시도할 수 있습니다.",
        )

    try:
        return await quick_match_service.fail_request(
            db=db,
            request_id=request_id,
            reason=payload.reason or "manual_retry",
        )
    except Exception as e:
        error_map = {
            "REQUEST_NOT_FOUND": (status.HTTP_404_NOT_FOUND, "빠른매칭 요청을 찾을 수 없습니다."),
        }
        code, message = error_map.get(str(e), (status.HTTP_400_BAD_REQUEST, str(e)))
        raise HTTPException(status_code=code, detail=message)


@router.get(
    "/{request_id}",
    response_model=QuickMatchDetailResponse,
    status_code=status.HTTP_200_OK,
)
async def get_quick_match_detail(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
):
    request = await db.get(QuickMatchRequest, request_id)

    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="빠른매칭 요청을 찾을 수 없습니다.",
        )

    if request.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인 요청만 조회할 수 있습니다.",
        )

    candidates = list(request.candidates) if request.candidates else []
    result = request.result

    return QuickMatchDetailResponse(
        request=request,
        candidates=candidates,
        result=result,
    )