import uuid
import enum
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Enum as SAEnum, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base
from datetime import datetime


class PartyStatusEnum(str, enum.Enum):
    RECRUITING = "RECRUITING"
    FULL = "FULL"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


class Service(Base):
    """DB의 services 테이블 (실제 컬럼 기반)"""
    __tablename__ = "services"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    max_members: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_price: Mapped[int] = mapped_column(Integer, nullable=False)
    logo_image_key: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    parties: Mapped[list["Party"]] = relationship("Party", back_populates="service")


class Party(Base):
    __tablename__ = "parties"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    leader_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    service_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("services.id"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[PartyStatusEnum | None] = mapped_column(
        SAEnum(PartyStatusEnum, name="party_status_enum", create_type=False)
    )

    host: Mapped["User"] = relationship("User", back_populates="hosted_parties", foreign_keys=[leader_id])  # noqa
    service: Mapped["Service"] = relationship("Service", back_populates="parties")
    members: Mapped[list["PartyMember"]] = relationship("PartyMember", back_populates="party")
    chat_room: Mapped["ChatRoom"] = relationship("ChatRoom", back_populates="party", uselist=False)  # noqa


class PartyMember(Base):
    __tablename__ = "party_members"

    party_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("parties.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    payment_status: Mapped[int | None] = mapped_column(Integer, server_default="0")
    receipt_img_url: Mapped[str | None] = mapped_column(String(255))

    party: Mapped["Party"] = relationship("Party", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="party_members")  # noqa
