"""가상 예제와 빈 프로젝트 생성. 실제 제품·약가 자료는 포함하지 않는다."""

from decimal import Decimal

from .models import (
    FixedCost,
    Material,
    PricingInput,
    PricingMetadata,
    ProductInfo,
    Project,
    Scenario,
    clone_scenario,
)


def create_empty_project() -> Project:
    return Project()


def create_example_project() -> Project:
    """두 API의 비용과 독립적인 절감 시나리오를 보여 주는 가상 프로젝트."""
    scenario = Scenario(
        name="가상 예제 · 기본안",
        pricing=PricingInput(
            insurance_price=Decimal("300"),
            post_addition_price=Decimal("250"),
            target_rate=Decimal("20"),
            metadata=PricingMetadata(
                product_type="제네릭",
                development_method="가상 예제: 공동 개발 검토",
                participation_form="가상 예제: 참여 형태 미정",
                reference_product="가상 기준 제품",
                original_current_price=Decimal("600"),
                reference_amount=Decimal("500"),
                bioequivalence_requirement="unknown",
                registered_api_requirement="unknown",
                listed_product_count=10,
                concurrent_application_count=3,
                addition_conditions="가상 참고정보. 약가 자동 산정에 사용하지 않습니다.",
                expected_application_date="2027년 상반기(가상)",
                expected_listing_date="2027년 하반기(가상)",
            ),
        ),
        materials=[
            Material(
                kind="api", name="가상 API A", specification="예제 규격 A",
                supplier="가상 공급처 A", amount=Decimal("20"),
                krw_price=Decimal("1000000"), memo="표시 함량과 실제 투입량은 별도입니다.",
            ),
            Material(
                kind="api", name="가상 API B", specification="예제 규격 B",
                supplier="가상 공급처 B", amount=Decimal("10"),
                krw_price=Decimal("2000000"),
            ),
            Material(
                kind="excipient", name="가상 부형제", supplier="가상 공급처 C",
                amount=Decimal("100"), krw_price=Decimal("100000"),
            ),
        ],
        yield_percent=Decimal("100"),
        apply_yield=True,
        packaging=FixedCost(basis="package", amount=Decimal("300"), quantity=Decimal("30"), memo="가상 예제: 30정 포장 비용"),
        labor=FixedCost(basis="batch", amount=Decimal("2000000"), quantity=Decimal("100000"), memo="가상 예제: QC·제조간접비 포함 여부는 별도 확인"),
    )
    project = Project(
        product=ProductInfo(
            project_name="가상 예제 프로젝트", product_name="가상 복합정",
            dosage_form="tablet", label_strength="API A 20 mg / API B 10 mg",
            memo="학습용 가상 데이터입니다. 실제 제품·견적·보험약가와 관계가 없습니다.",
        ),
        scenarios=[scenario], active_scenario_id=scenario.id, is_example=True,
    )
    alternative = clone_scenario(project, scenario.id, "가상 예제 · API 단가 절감안")
    alternative.materials[0].krw_price = Decimal("500000")
    alternative.materials[1].krw_price = Decimal("1000000")
    alternative.materials[0].supplier = "가상 대체 공급처 A"
    alternative.materials[1].supplier = "가상 대체 공급처 B"
    project.active_scenario_id = scenario.id
    return project
