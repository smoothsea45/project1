"""수동 약가의 출처와 향후 규정 기반 산정의 결과 계약.

첫 버전은 어떤 자동 산정률도 적용하지 않는다. 개발·참여·요건 정보는
PricingMetadata에 기록하고, 검증된 규정 구현이 추가될 때만 사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .models import PricingInput


@dataclass(frozen=True)
class PricingAssessment:
    amount: Decimal | None
    source: str = "사용자 입력값"
    regulation: str | None = None
    basis_date: str | None = None
    steps: list[str] = field(default_factory=list)


def assess_pricing(pricing: PricingInput) -> PricingAssessment:
    """기록한 조건으로 추정률을 만들지 않고 입력 약가를 반환한다."""
    return PricingAssessment(
        amount=pricing.insurance_price,
        steps=["예상 보험약가는 사용자가 직접 입력했습니다."],
    )
