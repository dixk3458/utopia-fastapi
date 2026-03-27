import uuid
import enum
from sqlalchemy import Text, Boolean, DateTime, ForeignKey, Enum as SAEnum, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base
from datetime import datetime


class NotificationTypeEnum(str, enum.Enum):
    SECURITY = "SECURITY"
    PAYMENT = "PAYMENT"
    PARTY = "PARTY"
    SYSTEM = "SYSTEM"


class Notification(Base):
    __tablename__ = "notifications"

    # ✅ Fix: PK를 UUID로 변경 (DB: id uuid)
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # ✅ Fix: user_id 타입 UUID로 변경
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    type: Mapped[NotificationTypeEnum | None] = mapped_column(
        SAEnum(NotificationTypeEnum, name="notification_type_enum", create_type=False)
    )
    content: Mapped[str | None] = mapped_column(Text)
    is_read: Mapped[bool | None] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="notifications")  # noqa
