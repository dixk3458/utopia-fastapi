import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuickMatchCreateRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "service_id": "11111111-1111-1111-1111-111111111111",
                "preferred_conditions": {
                    "price_range": "4000-5000",
                    "duration_preference": "long_term",
                },
            }
        }
    )

    service_id: uuid.UUID = Field(..., description="서비스 ID")
    preferred_conditions: dict[str, Any] | None = Field(
        default=None,
        description="빠른매칭 선호 조건 JSON",
    )

    @field_validator("preferred_conditions")
    @classmethod
    def normalize_preferred_conditions(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is None:
            return None

        normalized = dict(value)

        # 구버전 호환: estimated_price -> price_range
        if "estimated_price" in normalized and "price_range" not in normalized:
            normalized["price_range"] = normalized.pop("estimated_price")

        duration_preference = normalized.get("duration_preference")
        if isinstance(duration_preference, str):
            normalized["duration_preference"] = duration_preference.strip().lower()

        price_range = normalized.get("price_range")
        if isinstance(price_range, str):
            normalized["price_range"] = price_range.strip()

        return normalized


class QuickMatchCancelRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "reason": "user_cancelled",
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
    def validate_reason(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        return value or "user_cancelled"


class QuickMatchRetryRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "reason": "no_candidate_selected",
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
    def validate_reason(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        return value or "manual_retry"
