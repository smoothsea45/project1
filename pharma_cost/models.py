"""프로젝트 데이터 모델. GUI, 저장 형식, 계산 구현과 독립적이다."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import uuid4


def new_id() -> str:
    """시나리오와 원료 행에 사용할 독립적인 식별자를 만든다."""
    return str(uuid4())


@dataclass
class ProductInfo:
    project_name: str = ""
    product_name: str = ""
    dosage_form: str = "tablet"
    label_strength: str = ""
    memo: str = ""


@dataclass
class PricingMetadata:
    product_type: str = ""
    development_method: str = ""
    participation_form: str = ""
    reference_product: str = ""
    original_current_price: Decimal | None = None
    reference_amount: Decimal | None = None
    bioequivalence_requirement: str = "unknown"
    registered_api_requirement: str = "unknown"
    listed_product_count: int | None = None
    concurrent_application_count: int | None = None
    addition_conditions: str = ""
    expected_application_date: str = ""
    expected_listing_date: str = ""


@dataclass
class PricingInput:
    insurance_price: Decimal | None = None
    post_addition_price: Decimal | None = None
    target_rate: Decimal | None = Decimal("20")
    metadata: PricingMetadata = field(default_factory=PricingMetadata)


@dataclass
class Material:
    id: str = field(default_factory=new_id)
    kind: str = "api"
    name: str = ""
    specification: str = ""
    supplier: str = ""
    basis: str = "mass"
    amount: Decimal | None = None
    price_source: str = "krw"
    krw_price: Decimal | None = None
    foreign_price: Decimal | None = None
    currency: str = "USD"
    exchange_rate: Decimal | None = None
    quotation_date: str = ""
    memo: str = ""


@dataclass
class FixedCost:
    basis: str = "unit"
    amount: Decimal | None = Decimal("0")
    quantity: Decimal | None = Decimal("1")
    memo: str = ""


@dataclass
class Scenario:
    id: str = field(default_factory=new_id)
    name: str = "기본 시나리오"
    pricing: PricingInput = field(default_factory=PricingInput)
    materials: list[Material] = field(default_factory=list)
    yield_percent: Decimal | None = Decimal("100")
    apply_yield: bool = True
    packaging: FixedCost = field(default_factory=FixedCost)
    labor: FixedCost = field(default_factory=FixedCost)


@dataclass
class Project:
    product: ProductInfo = field(default_factory=ProductInfo)
    scenarios: list[Scenario] = field(default_factory=lambda: [Scenario()])
    active_scenario_id: str = ""
    is_example: bool = False

    def __post_init__(self) -> None:
        if self.scenarios and not self.active_scenario_id:
            self.active_scenario_id = self.scenarios[0].id

    @property
    def active_scenario(self) -> Scenario:
        for scenario in self.scenarios:
            if scenario.id == self.active_scenario_id:
                return scenario
        raise ValueError("선택한 시나리오가 프로젝트에 없습니다.")


def clone_scenario(project: Project, source_id: str, name: str) -> Scenario:
    """현재 프로젝트에 독립적인 복제본을 추가하고 선택한다."""
    source = next((item for item in project.scenarios if item.id == source_id), None)
    if source is None:
        raise ValueError("복제할 시나리오가 없습니다.")
    clone = deepcopy(source)
    clone.id = new_id()
    clone.name = name
    for material in clone.materials:
        material.id = new_id()
    project.scenarios.append(clone)
    project.active_scenario_id = clone.id
    return clone
