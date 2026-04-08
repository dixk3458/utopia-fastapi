import asyncio
from decimal import Decimal

from core.database import AsyncSessionLocal
from core.security import hash_password
from models.user import User
from models.party import Service
from sqlalchemy import select

import models.user  # noqa
import models.party  # noqa
import models.notification  # noqa

SERVICE_CATALOG = [
    {
        "name": "티빙",
        "category": "OTT",
        "max_members": 4,
        "monthly_price": 17000,
        "logo_image_key": "service-logos/tving.png",
    },
    {
        "name": "넷플릭스",
        "category": "OTT",
        "max_members": 4,
        "monthly_price": 17000,
        "logo_image_key": "service-logos/netflix.png",
    },
    {
        "name": "디즈니플러스",
        "category": "OTT",
        "max_members": 4,
        "monthly_price": 13900,
        "logo_image_key": "service-logos/disney-plus.png",
    },
    {
        "name": "웨이브",
        "category": "OTT",
        "max_members": 4,
        "monthly_price": 13900,
        "logo_image_key": "service-logos/wavve.png",
    },
    {
        "name": "왓챠",
        "category": "OTT",
        "max_members": 4,
        "monthly_price": 12900,
        "logo_image_key": "service-logos/watcha.jpeg",
    },
    {
        "name": "라프텔",
        "category": "OTT",
        "max_members": 4,
        "monthly_price": 14900,
        "logo_image_key": "service-logos/laftel.png",
    },
    {
        "name": "애플 TV+",
        "category": "OTT",
        "max_members": 6,
        "monthly_price": 6500,
        "logo_image_key": "service-logos/apple-tv-plus.png",
    },
    {
        "name": "슈퍼 듀오링고",
        "category": "교육/도서",
        "max_members": 6,
        "monthly_price": 13250,
        "logo_image_key": "service-logos/super-duolingo.jpeg",
    },
    {
        "name": "밀리의 서재",
        "category": "교육/도서",
        "max_members": 1,
        "monthly_price": 11900,
        "logo_image_key": "service-logos/millie.png",
    },
    {
        "name": "스포티파이",
        "category": "음악",
        "max_members": 2,
        "monthly_price": 17985,
        "logo_image_key": "service-logos/spotify.png",
    },
    {
        "name": "애플 뮤직",
        "category": "음악",
        "max_members": 6,
        "monthly_price": 13500,
        "logo_image_key": "service-logos/apple-music.png",
    },
    {
        "name": "FLO",
        "category": "음악",
        "max_members": 1,
        "monthly_price": 7900,
        "logo_image_key": "service-logos/flo.png",
    },
    {
        "name": "네이버플러스",
        "category": "생산성/기타",
        "max_members": 4,
        "monthly_price": 4900,
        "logo_image_key": "service-logos/naver-plus.png",
    },
    {
        "name": "애플 원",
        "category": "생산성/기타",
        "max_members": 6,
        "monthly_price": 20900,
        "logo_image_key": "service-logos/apple-one.png",
    },
    {
        "name": "스노우 VIP",
        "category": "생산성/기타",
        "max_members": 1,
        "monthly_price": 8900,
        "logo_image_key": "service-logos/snow-vip.png",
    },
    {
        "name": "ChatGPT Plus",
        "category": "생산성/기타",
        "max_members": 1,
        "monthly_price": 28000,
        "logo_image_key": "service-logos/chatgpt-plus.jpg",
    },
    {
        "name": "Microsoft 365",
        "category": "생산성/기타",
        "max_members": 6,
        "monthly_price": 15500,
        "logo_image_key": "service-logos/microsoft-365.jpg",
    },
]


async def seed():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == "test@partyup.kr"))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                email="test@partyup.kr",
                name="테스터",
                nickname="테스터닉",
                password_hash=hash_password("password123"),
                role="ADMIN",
                phone="010-0000-0000",
            )
            db.add(user)
            await db.flush()

        existing_services = {
            service.name: service
            for service in (await db.execute(select(Service))).scalars().all()
        }

        for item in SERVICE_CATALOG:
            service = existing_services.get(item["name"])
            if service is None:
                service = Service(
                    created_by=user.id,
                    commission_rate=Decimal("0.1"),
                    leader_discount_rate=Decimal("0.05"),
                    referral_discount_rate=Decimal("0.05"),
                    **item,
                )
                db.add(service)
                continue

            service.category = item["category"]
            service.max_members = item["max_members"]
            service.monthly_price = item["monthly_price"]
            service.logo_image_key = item["logo_image_key"]
            service.is_active = True
            service.created_by = service.created_by or user.id
            service.commission_rate = Decimal("0.1")
            service.leader_discount_rate = Decimal("0.05")
            service.referral_discount_rate = Decimal("0.05")

        await db.commit()
        print("✅ 완료! 테스트 계정: test@partyup.kr / password123")
        print(f"✅ 서비스 카탈로그 동기화: {len(SERVICE_CATALOG)}개")


if __name__ == "__main__":
    asyncio.run(seed())
