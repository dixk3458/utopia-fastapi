import math
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.quick_match.request import QuickMatchRequest, QuickMatchRequestStatus
from models.quick_match.candidate import QuickMatchCandidate
from models.quick_match.result import QuickMatchResult
from models.quick_match.embedding import PartyMatchEmbedding

from models.user import User
from models.party import Party, PartyEmbedding, PartyMember

from services.quick_match.embedding_service import EmbeddingService
from core.redis_lock import redis_lock


class QuickMatchService:
    async def create_request(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        service_id: uuid.UUID,
        preferred_conditions: dict | None,
    ):
        user = await db.get(User, user_id)
        if not user:
            raise Exception("USER_NOT_FOUND")

        if not user.is_active:
            raise Exception("USER_INACTIVE")

        if user.banned_until and user.banned_until > datetime.utcnow():
            raise Exception("USER_BANNED")

        existing = await db.execute(
            select(QuickMatchRequest).where(
                QuickMatchRequest.user_id == user_id,
                QuickMatchRequest.is_active.is_(True),
            )
        )
        if existing.scalar_one_or_none():
            raise Exception("ALREADY_REQUESTED")

        active_member = await db.execute(
            select(PartyMember).where(
                PartyMember.user_id == user_id,
                PartyMember.status == "active",
            )
        )
        if active_member.scalar_one_or_none():
            raise Exception("ALREADY_IN_ACTIVE_PARTY")

        ai_profile = {
            "trust_score": float(user.trust_score),
            "preferred_conditions": preferred_conditions or {},
        }

        summary = await EmbeddingService.generate_profile_summary(ai_profile)
        embedding_vector = await EmbeddingService.generate_embedding({"text": summary})

        embedding = PartyMatchEmbedding(
            user_id=user_id,
            service_id=service_id,
            embedding_vector=embedding_vector,
            source_snapshot=ai_profile,
            last_generated_at=datetime.utcnow(),
        )
        db.add(embedding)

        request = QuickMatchRequest(
            user_id=user_id,
            service_id=service_id,
            status=QuickMatchRequestStatus.REQUESTED,
            preferred_conditions=preferred_conditions,
            ai_profile_snapshot=ai_profile,
            requested_at=datetime.utcnow(),
            expired_at=datetime.utcnow() + timedelta(minutes=5),
            is_active=True,
        )

        db.add(request)
        await db.commit()
        await db.refresh(request)
        return request

    async def find_candidates(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
    ):
        request = await db.get(QuickMatchRequest, request_id)
        if not request:
            raise Exception("REQUEST_NOT_FOUND")

        if request.status != QuickMatchRequestStatus.REQUESTED:
            raise Exception("INVALID_REQUEST_STATUS")

        user = await db.get(User, request.user_id)
        if not user:
            raise Exception("USER_NOT_FOUND")

        embedding_result = await db.execute(
            select(PartyMatchEmbedding).where(
                PartyMatchEmbedding.user_id == request.user_id,
                PartyMatchEmbedding.service_id == request.service_id,
            )
        )
        user_embedding = embedding_result.scalar_one_or_none()
        if not user_embedding or not user_embedding.embedding_vector:
            raise Exception("EMBEDDING_NOT_FOUND")

        existing_candidates = await db.execute(
            select(QuickMatchCandidate).where(
                QuickMatchCandidate.request_id == request.id
            )
        )
        for row in existing_candidates.scalars().all():
            await db.delete(row)
        await db.flush()

        party_result = await db.execute(
            select(Party).where(
                Party.status == "recruiting",
                Party.service_id == request.service_id,
            )
        )
        parties = party_result.scalars().all()

        if not parties:
            raise Exception("NO_RECRUITING_PARTY")

        preferred_conditions = request.preferred_conditions or {}
        user_trust_score = float(user.trust_score)

        scored_candidates: list[dict[str, Any]] = []

        for party in parties:
            filter_reasons: dict[str, Any] = {
                "service_match": True,
                "recruiting_status": party.status == "recruiting",
            }

            party_max_members = int(party.max_members or 0)
            party_current_members = int(party.current_members or 0)

            remaining_seat = max((party_max_members - party_current_members), 0)
            filter_reasons["remaining_seat"] = remaining_seat
            if party_current_members >= party_max_members:
                filter_reasons["excluded_reason"] = "party_full"
                continue

            min_trust_score = float(getattr(party, "min_trust_score", 0) or 0)
            filter_reasons["party_min_trust_score"] = min_trust_score
            filter_reasons["user_trust_score"] = user_trust_score
            if user_trust_score < min_trust_score:
                filter_reasons["excluded_reason"] = "trust_score_too_low"
                continue

            existing_member_result = await db.execute(
                select(PartyMember).where(
                    PartyMember.party_id == party.id,
                    PartyMember.user_id == request.user_id,
                )
            )
            if existing_member_result.scalar_one_or_none():
                filter_reasons["excluded_reason"] = "already_member"
                continue

            rule_score, rule_reason = self._calculate_rule_score(
                party=party,
                user_trust_score=user_trust_score,
                preferred_conditions=preferred_conditions,
            )
            filter_reasons["rule_reason"] = rule_reason

            party_embedding_result = await db.execute(
                select(PartyEmbedding).where(
                    PartyEmbedding.party_id == party.id
                )
            )
            party_embedding = party_embedding_result.scalar_one_or_none()

            if not party_embedding or not party_embedding.embedding_vector:
                filter_reasons["excluded_reason"] = "party_embedding_not_found"
                continue

            vector_score = self._calculate_vector_score(
                user_embedding.embedding_vector,
                party_embedding.embedding_vector,
            )

            ai_score = self._calculate_ai_score(
                rule_score=rule_score,
                vector_score=vector_score,
            )

            scored_candidates.append(
                {
                    "party": party,
                    "rule_score": rule_score,
                    "vector_score": vector_score,
                    "ai_score": ai_score,
                    "filter_reasons": filter_reasons,
                }
            )

        if not scored_candidates:
            raise Exception("NO_CANDIDATE")

        scored_candidates.sort(
            key=lambda x: (
                x["ai_score"],
                x["vector_score"],
                x["rule_score"],
            ),
            reverse=True,
        )

        created_candidates: list[QuickMatchCandidate] = []

        for idx, item in enumerate(scored_candidates, start=1):
            status = "selected" if idx == 1 else "pending"

            candidate = QuickMatchCandidate(
                request_id=request.id,
                party_id=item["party"].id,
                rule_score=item["rule_score"],
                vector_score=item["vector_score"],
                ai_score=item["ai_score"],
                rank=idx,
                status=status,
                filter_reasons=item["filter_reasons"],
            )
            db.add(candidate)
            created_candidates.append(candidate)

        await db.commit()

        for candidate in created_candidates:
            await db.refresh(candidate)

        return created_candidates

    async def select_party(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
    ):
        result = await db.execute(
            select(QuickMatchCandidate)
            .where(QuickMatchCandidate.request_id == request_id)
            .order_by(
                QuickMatchCandidate.ai_score.desc(),
                QuickMatchCandidate.vector_score.desc(),
                QuickMatchCandidate.rule_score.desc(),
            )
        )
        candidate = result.scalars().first()

        if not candidate:
            raise Exception("NO_CANDIDATE")

        request = await db.get(QuickMatchRequest, request_id)
        if not request:
            raise Exception("REQUEST_NOT_FOUND")

        party = await db.get(Party, candidate.party_id)
        if not party:
            raise Exception("PARTY_NOT_FOUND")

        party_current_members = int(party.current_members or 0)
        party_max_members = int(party.max_members or 0)

        if party.status != "recruiting":
            raise Exception("PARTY_STATUS_CHANGED")

        if party_current_members >= party_max_members:
            raise Exception("PARTY_FULL")

        request.status = QuickMatchRequestStatus.MATCHED
        request.matched_party_id = candidate.party_id
        request.matched_at = datetime.utcnow()
        request.is_active = False

        candidate.status = "selected"

        result_row = QuickMatchResult(
            request_id=request.id,
            selected_party_id=candidate.party_id,
            selected_candidate_id=candidate.id,
            request_snapshot={
                "user_id": str(request.user_id),
                "service_id": str(request.service_id),
                "preferred_conditions": request.preferred_conditions,
            },
            candidate_snapshot={
                "party_id": str(candidate.party_id),
                "rank": candidate.rank,
                "status": candidate.status,
            },
            final_scores={
                "rule_score": float(candidate.rule_score),
                "vector_score": float(candidate.vector_score),
                "ai_score": float(candidate.ai_score),
            },
            decision_reason="최고 점수 기반 자동 선택",
        )

        db.add(result_row)
        await db.commit()
        await db.refresh(result_row)
        return result_row

    async def join_party(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
    ):
        request = await db.get(QuickMatchRequest, request_id)
        if not request:
            raise Exception("REQUEST_NOT_FOUND")

        if request.status != QuickMatchRequestStatus.MATCHED:
            raise Exception("REQUEST_NOT_MATCHED")

        if not request.matched_party_id:
            raise Exception("MATCHED_PARTY_NOT_FOUND")

        party = await db.get(Party, request.matched_party_id)
        if not party:
            raise Exception("PARTY_NOT_FOUND")

        lock_key = f"quick_match_lock:{party.id}"

        async with redis_lock(lock_key=lock_key, lock_value=str(request.id), expire_seconds=30):
            await db.refresh(party)

            party_current_members = int(party.current_members or 0)
            party_max_members = int(party.max_members or 0)

            if party.status != "recruiting":
                await self.fail_request(db, request.id, "PARTY_STATUS_CHANGED")
                return await self.retry_match(db, request.id)

            if party_current_members >= party_max_members:
                await self.fail_request(db, request.id, "PARTY_FULL")
                return await self.retry_match(db, request.id)

            existing_member_result = await db.execute(
                select(PartyMember).where(
                    PartyMember.party_id == party.id,
                    PartyMember.user_id == request.user_id,
                )
            )
            existing_member = existing_member_result.scalar_one_or_none()
            if existing_member:
                await self.fail_request(db, request.id, "ALREADY_JOINED")
                return await self.retry_match(db, request.id)

            new_member = PartyMember(
                party_id=party.id,
                user_id=request.user_id,
                role="member",
                status="active",
                joined_at=datetime.utcnow(),
                join_type="quick_match",
                match_request_id=request.id,
                matched_at=request.matched_at or datetime.utcnow(),
                approved_at=datetime.utcnow(),
                leader_review_status="approved",
            )
            db.add(new_member)

            party.current_members = party_current_members + 1

            await db.commit()
            await db.refresh(new_member)

            return {
                "party_member_id": new_member.id,
                "party_id": party.id,
                "user_id": request.user_id,
                "status": new_member.status,
                "join_type": new_member.join_type,
                "current_members": party.current_members,
            }

    async def fail_request(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
        reason: str,
    ):
        request = await db.get(QuickMatchRequest, request_id)
        if not request:
            raise Exception("REQUEST_NOT_FOUND")

        request.status = QuickMatchRequestStatus.FAILED
        request.fail_reason = reason
        request.retry_count += 1
        request.is_active = False

        await db.commit()
        await db.refresh(request)
        return request

    async def retry_match(
        self,
        db: AsyncSession,
        request_id: uuid.UUID,
    ):
        request = await db.get(QuickMatchRequest, request_id)
        if not request:
            raise Exception("REQUEST_NOT_FOUND")

        if request.retry_count >= 3:
            request.status = QuickMatchRequestStatus.EXPIRED
            request.is_active = False
            request.fail_reason = "MAX_RETRY_EXCEEDED"

            await db.commit()
            await db.refresh(request)
            return request

        result = await db.execute(
            select(QuickMatchCandidate)
            .where(
                QuickMatchCandidate.request_id == request_id,
                QuickMatchCandidate.status.in_(["pending"]),
            )
            .order_by(QuickMatchCandidate.ai_score.desc())
        )

        next_candidate = result.scalars().first()

        if not next_candidate:
            request.status = QuickMatchRequestStatus.FAILED
            request.is_active = False
            request.fail_reason = "NO_MORE_CANDIDATES"

            await db.commit()
            await db.refresh(request)
            return request

        next_candidate.status = "selected"

        request.matched_party_id = next_candidate.party_id
        request.status = QuickMatchRequestStatus.MATCHED
        request.retry_count += 1
        request.is_active = False

        await db.commit()

        return {
            "request_id": request.id,
            "next_party_id": next_candidate.party_id,
            "retry_count": request.retry_count,
        }

    def _calculate_rule_score(
        self,
        party: Party,
        user_trust_score: float,
        preferred_conditions: dict[str, Any],
    ) -> tuple[float, dict[str, Any]]:
        score = 0.0
        detail: dict[str, Any] = {}

        min_trust_score = float(getattr(party, "min_trust_score", 0) or 0)
        if min_trust_score <= 0:
            trust_fit_score = 1.0
        elif user_trust_score >= min_trust_score:
            margin = min(user_trust_score - min_trust_score, 20)
            trust_fit_score = min(1.0, 0.7 + (margin / 20) * 0.3)
        else:
            trust_fit_score = 0.0

        score += trust_fit_score * 0.4
        detail["trust_fit_score"] = round(trust_fit_score, 4)

        party_max_members = float(getattr(party, "max_members", 0) or 0)
        party_current_members = float(getattr(party, "current_members", 0) or 0)

        if party_max_members <= 0:
            capacity_score = 0.0
        else:
            remaining = max((party_max_members - party_current_members), 0)
            capacity_score = min(1.0, remaining / max(party_max_members, 1))

        score += capacity_score * 0.2
        detail["capacity_score"] = round(capacity_score, 4)

        preferred_price = preferred_conditions.get("estimated_price")
        monthly_price = float(getattr(party, "monthly_per_person", 0) or 0)

        price_score = self._calculate_price_score(
            monthly_price=monthly_price,
            preferred_price=preferred_price,
        )
        score += price_score * 0.4
        detail["price_score"] = round(price_score, 4)
        detail["preferred_price"] = preferred_price
        detail["monthly_price"] = monthly_price

        return round(min(score, 1.0), 4), detail

    def _calculate_price_score(
        self,
        monthly_price: float,
        preferred_price: str | None,
    ) -> float:
        if not preferred_price:
            return 0.7

        try:
            if "-" in preferred_price:
                low_str, high_str = preferred_price.split("-", 1)
                low = float(low_str.strip())
                high = float(high_str.strip())

                if low <= monthly_price <= high:
                    return 1.0

                if monthly_price < low:
                    diff_ratio = (low - monthly_price) / max(low, 1)
                else:
                    diff_ratio = (monthly_price - high) / max(high, 1)

                if diff_ratio <= 0.1:
                    return 0.8
                if diff_ratio <= 0.2:
                    return 0.6
                if diff_ratio <= 0.3:
                    return 0.4
                return 0.2
        except Exception:
            return 0.5

        return 0.5

    def _calculate_vector_score(
        self,
        user_embedding: list[float],
        party_embedding: list[float],
    ) -> float:
        if not user_embedding or not party_embedding:
            return 0.0

        dim = min(len(user_embedding), len(party_embedding))
        if dim == 0:
            return 0.0

        a = [float(x) for x in user_embedding[:dim]]
        b = [float(x) for x in party_embedding[:dim]]

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        cosine = dot / (norm_a * norm_b)
        normalized = (cosine + 1) / 2
        return round(max(0.0, min(1.0, normalized)), 4)

    def _calculate_ai_score(
        self,
        rule_score: float,
        vector_score: float,
    ) -> float:
        ai_score = (rule_score * 0.6) + (vector_score * 0.4)
        return round(min(ai_score, 1.0), 4)