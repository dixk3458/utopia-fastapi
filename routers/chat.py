import json
import asyncio
import uuid
import httpx
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import redis.asyncio as aioredis
from core.config import settings
from core.database import get_db
from models.party import Party, PartyMember
from models.chat import ChatRoom
from models.user import User

router = APIRouter(prefix="/chat", tags=["chat"])

redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

REDIS_TTL = 60 * 60 * 24 * 3
OLLAMA_URL = settings.OLLAMA_URL
OLLAMA_MODEL = settings.OLLAMA_MODEL


def warn_key(room_id: str, user_id: str) -> str:
    return f"warn:{room_id}:{user_id}"

def redis_key(room_id: str) -> str:
    return f"chat:room:{room_id}:messages"

def blocked_key(room_id: str, user_id: str) -> str:
    return f"blocked:{room_id}:{user_id}"


async def check_message(content: str) -> dict:
    prompt = f"""채팅 메시지에 욕설, 비속어, 혐오 표현이 있는지 판단하세요.

메시지: "{content}"

JSON으로만 응답하세요:
{{"violation": true/false, "severe": true/false, "reason": "이유"}}"""

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
            )
            text = resp.json()["message"]["content"].strip()
            if "```" in text:
                text = text.split("```")[1].replace("json", "").strip()
            parsed = json.loads(text)
            return {
                "violation": parsed.get("violation", False),
                "severe": parsed.get("severe", False),
                "reason": parsed.get("reason", ""),
            }
    except Exception:
        return {"violation": False, "severe": False, "reason": ""}


class ConnectionManager:
    def __init__(self):
        self.active: dict[str, list[WebSocket]] = {}

    async def connect(self, room_id: str, ws: WebSocket):
        await ws.accept()
        self.active.setdefault(room_id, []).append(ws)

    def disconnect(self, room_id: str, ws: WebSocket):
        if room_id in self.active:
            try:
                self.active[room_id].remove(ws)
            except ValueError:
                pass

    async def broadcast(self, room_id: str, message: dict):
        msg_str = json.dumps(message, ensure_ascii=False)
        for ws in list(self.active.get(room_id, [])):
            try:
                await ws.send_text(msg_str)
            except Exception:
                pass

    async def send_personal(self, ws: WebSocket, message: dict):
        try:
            await ws.send_text(json.dumps(message, ensure_ascii=False))
        except Exception:
            pass


manager = ConnectionManager()


async def moderate_in_background(room_id: str, user_id: str, content: str, ws: WebSocket):
    moderation = await check_message(content)

    if moderation["severe"]:
        await redis_client.set(blocked_key(room_id, user_id), "1", ex=REDIS_TTL)
        await manager.send_personal(ws, {
            "type": "error",
            "content": f"🚫 심각한 욕설이 감지되어 차단되었습니다. ({moderation['reason']})",
            "created_at": datetime.now().isoformat(),
        })
        await redis_client.rpop(redis_key(room_id))
        await manager.broadcast(room_id, {
            "type": "system",
            "content": "부적절한 메시지가 삭제되었습니다.",
            "created_at": datetime.now().isoformat(),
        })

    elif moderation["violation"]:
        key = warn_key(room_id, user_id)
        warn_count = await redis_client.incr(key)
        await redis_client.expire(key, REDIS_TTL)

        if warn_count >= 3:
            await redis_client.set(blocked_key(room_id, user_id), "1", ex=REDIS_TTL)
            await manager.send_personal(ws, {
                "type": "error",
                "content": "🚫 경고 3회 누적으로 채팅이 차단되었습니다.",
                "created_at": datetime.now().isoformat(),
            })
            await redis_client.rpop(redis_key(room_id))
            await manager.broadcast(room_id, {
                "type": "system",
                "content": "부적절한 메시지가 삭제되었습니다.",
                "created_at": datetime.now().isoformat(),
            })
        else:
            await manager.send_personal(ws, {
                "type": "warning",
                "content": f"⚠️ 경고 {warn_count}/3회: 부적절한 표현이 감지되었습니다.",
                "created_at": datetime.now().isoformat(),
            })


# ✅ Fix: party_id 타입 uuid.UUID로 변경
@router.post("/rooms/{party_id}")
async def get_or_create_room(party_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    party = await db.get(Party, party_id)
    if not party:
        raise HTTPException(status_code=404, detail="파티를 찾을 수 없습니다.")

    result = await db.execute(select(ChatRoom).where(ChatRoom.party_id == party_id))
    room = result.scalar_one_or_none()

    if not room:
        room = ChatRoom(party_id=party_id)
        db.add(room)
        await db.commit()
        await db.refresh(room)

    # ✅ Fix: chat_room_id → id (UUID)
    return {"chat_room_id": str(room.id), "party_id": str(party_id)}


@router.get("/rooms/{room_id}/messages")
async def get_messages(room_id: str):
    messages = await redis_client.lrange(redis_key(room_id), 0, -1)
    return [json.loads(m) for m in messages]


@router.get("/rooms/{party_id}/info")
async def get_room_info(party_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PartyMember, User)
        .join(User, PartyMember.user_id == User.id)
        .where(PartyMember.party_id == party_id)
    )
    rows = result.all()
    party = await db.get(Party, party_id)
    if not party:
        raise HTTPException(status_code=404, detail="파티를 찾을 수 없습니다.")

    members = []
    for member, user in rows:
        members.append({
            "user_id": str(user.id),
            "nickname": user.nickname,
            # ✅ Fix: host_id → leader_id
            "role": "리더" if user.id == party.leader_id else "멤버",
            "payment_status": member.payment_status,
        })
    return {"party_id": str(party_id), "title": party.title, "members": members}


# ✅ Fix: room_id를 str 타입으로 (UUID 문자열)
@router.websocket("/ws/{room_id}")
async def websocket_chat(
    room_id: str,
    ws: WebSocket,
    nickname: str = "익명",
    user_id: str = "guest",
):
    await manager.connect(room_id, ws)

    await manager.broadcast(room_id, {
        "type": "system",
        "content": f"{nickname}님이 입장했습니다.",
        "created_at": datetime.now().isoformat(),
    })

    try:
        while True:
            data = await ws.receive_text()

            is_blocked = await redis_client.get(blocked_key(room_id, user_id))
            if is_blocked:
                await manager.send_personal(ws, {
                    "type": "error",
                    "content": "채팅이 차단되어 메시지를 보낼 수 없습니다.",
                    "created_at": datetime.now().isoformat(),
                })
                continue

            message = {
                "type": "message",
                "room_id": room_id,
                "user_id": user_id,
                "nickname": nickname,
                "content": data,
                "created_at": datetime.now().isoformat(),
            }

            key = redis_key(room_id)
            await redis_client.rpush(key, json.dumps(message, ensure_ascii=False))
            await redis_client.ltrim(key, -200, -1)
            await redis_client.expire(key, REDIS_TTL)
            await manager.broadcast(room_id, message)

            asyncio.create_task(
                moderate_in_background(room_id, user_id, data, ws)
            )

    except WebSocketDisconnect:
        manager.disconnect(room_id, ws)
        await manager.broadcast(room_id, {
            "type": "system",
            "content": f"{nickname}님이 퇴장했습니다.",
            "created_at": datetime.now().isoformat(),
        })
