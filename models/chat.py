import uuid
from sqlalchemy import ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.database import Base


class ChatRoom(Base):
    __tablename__ = "chat_rooms"

    # ✅ Fix: PK UUID (DB 일관성 유지)
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )

    # ✅ Fix: party_id 타입 UUID로 변경
    party_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parties.id")
    )

    party: Mapped["Party"] = relationship("Party", back_populates="chat_room")  # noqa
