import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuickMatchCreateRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "service_id": "11111111-1111-1111-1111-111111111111",
                "preferred_conditions": {
                    "estimated_price": "4000-5000",
                    "preferred_time": "evening",
                },
            }
        }
    )

    service_id: uuid.UUID = Field(..., description="서비스 ID")
    preferred_conditions: dict[str, Any] | None = Field(
        default=None,
        description="빠른매칭 선호 조건 JSON",
    )


class QuickMatchCancelRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "reason": "user_cancelled"
            }
        }
    )

    reason: str | None = Field(
        default="user_cancelled",
        max_length=255,
        description="빠른매칭 취소 사유",
    )

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        return v or "user_cancelled"


class QuickMatchRetryRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "reason": "no_candidate_selected"
            }
        }
    )

    reason: str | None = Field(
        default="manual_retry",
        max_length=255,
        description="재탐색 요청 사유",
    )

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        return v or "manual_retry"