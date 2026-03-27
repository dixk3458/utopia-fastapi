import uuid
from sqlalchemy import String, DateTime, Boolean, Numeric, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base
from datetime import datetime


class User(Base):
    __tablename__ = "users"

    # ✅ Fix: PK를 UUID로 변경 (DB 실제 컬럼: id uuid)
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    nickname: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)

    # ✅ Fix: profile_image_key 추가 (DB에 존재)
    profile_image_key: Mapped[str | None] = mapped_column(String(255))

    # ✅ Fix: phone으로 컬럼명 변경 (DB: phone, 코드: phone_number)
    phone: Mapped[str | None] = mapped_column(String(50))

    # ✅ Fix: oauth→provider, oauth_id→provider_id 로 컬럼명 변경
    provider: Mapped[str] = mapped_column(String(30), nullable=False, server_default="local")
    provider_id: Mapped[str | None] = mapped_column(String(255))

    # ✅ Fix: role 추가 (DB에 존재)
    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default="user")

    # ✅ Fix: trust_score를 Numeric으로 변경 (DB: numeric)
    trust_score: Mapped[float] = mapped_column(Numeric, nullable=False, server_default="100")

    # ✅ Fix: referred_by 추가 (DB에 존재, UUID FK)
    referred_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # ✅ Fix: is_active 추가 (DB에 존재)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    # ✅ Fix: banned_until 추가 (DB에 존재)
    banned_until: Mapped[datetime | None] = mapped_column(DateTime)

    # ✅ Fix: last_login_at 추가 (DB에 존재)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    # ✅ Fix: updated_at 추가 (DB에 존재)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # ✅ Fix: 제거된 컬럼들 (DB에 없음):
    #   name, birth_data, last_login_ip, warning_count, status

    # Relationships
    hosted_parties: Mapped[list["Party"]] = relationship("Party", back_populates="host")  # noqa
    party_members: Mapped[list["PartyMember"]] = relationship("PartyMember", back_populates="user")  # noqa
    notifications: Mapped[list["Notification"]] = relationship("Notification", back_populates="user")  # noqa
