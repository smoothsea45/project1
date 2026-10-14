"""JSON persistence and schema safety checks without any Qt dependency."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from pharma_cost.examples import create_empty_project, create_example_project
from pharma_cost.models import FixedCost, Material, Project, clone_scenario
from pharma_cost.storage import (
    FORMAT_MARKER,
    FORMAT_VERSION,
    ProjectFileError,
    load_project,
    project_from_dict,
    project_to_dict,
    save_project,
)


class StorageTests(unittest.TestCase):
    def test_roundtrip_retains_all_metadata_scenarios_and_decimal_precision(self) -> None:
        project = create_example_project()
        scenario = project.active_scenario
        scenario.pricing.metadata.bioequivalence_requirement = "yes"
        scenario.pricing.metadata.registered_api_requirement = "no"
        scenario.pricing.insurance_price = Decimal("300.12345678901234567890123456789")
        scenario.pricing.target_rate = None
        scenario.yield_percent = Decimal("98.7654321")
        scenario.apply_yield = False
        scenario.materials.append(Material(
            kind="excipient", name="가상 캡슐 기제", specification="0호", supplier="제조사",
            basis="piece", amount=Decimal("1.0000"), price_source="fx",
            krw_price=Decimal("99"), foreign_price=Decimal("0.00234567890123456789"),
            currency="EUR", exchange_rate=Decimal("1500.123456789"),
            quotation_date="2026-10-14", memo="외화 환산을 사용; 원화값은 참고용",
        ))
        project.product.dosage_form = "capsule"
        project.product.memo = "한글과 줄바꿈\n저장 유지"
        scenario.packaging = FixedCost("unit", Decimal("1.23456789"), None, "QC 포함")
        scenario.labor = FixedCost("batch", Decimal("2000000"), Decimal("100000"), "간접비 포함")
        duplicate = clone_scenario(project, scenario.id, "독립 복제 시나리오")
        duplicate.materials[0].supplier = "새 공급처"
        duplicate.materials[0].amount = None
        duplicate.pricing.metadata.original_current_price = None
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "한글 프로젝트.json"
            save_project(project, path)
            restored = load_project(path)
            self.assertEqual(restored, project)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["format"], FORMAT_MARKER)
            self.assertEqual(payload["schema_version"], FORMAT_VERSION)
            self.assertEqual(payload["scenarios"][0]["pricing"]["insurance_price"], str(scenario.pricing.insurance_price))
            self.assertEqual(payload["scenarios"][0]["materials"][-1]["amount"], "1.0000")
            self.assertIsNone(payload["scenarios"][0]["packaging"]["quantity"])
            self.assertIsNone(payload["scenarios"][0]["pricing"]["target_rate"])

    def test_incomplete_project_is_saved_without_fabricating_values(self) -> None:
        project = create_empty_project()
        project.active_scenario.materials.append(Material())
        project.active_scenario.packaging.amount = None
        project.active_scenario.labor.quantity = None
        project.active_scenario.yield_percent = None
        restored = project_from_dict(project_to_dict(project))
        self.assertEqual(restored, project)
        self.assertIsNone(restored.active_scenario.materials[0].amount)
        self.assertIsNone(restored.active_scenario.pricing.insurance_price)

    def test_scenario_clone_does_not_mutate_original_and_persists(self) -> None:
        project = create_example_project()
        original = project.active_scenario
        snapshot = deepcopy(original)
        clone = clone_scenario(project, original.id, "복제")
        clone.materials[0].amount = Decimal("999")
        clone.pricing.metadata.reference_amount = Decimal("400")
        clone.packaging.memo = "새 메모"
        self.assertEqual(original, snapshot)
        self.assertNotEqual(clone.materials[0].id, original.materials[0].id)
        self.assertEqual(project_from_dict(project_to_dict(project)), project)

    def test_file_identity_and_version_are_required(self) -> None:
        payload = project_to_dict(create_empty_project())
        variants = [[], {}, {**payload, "format": "other"}, {**payload, "schema_version": 999}, {**payload, "schema_version": "1"}, {**payload, "schema_version": True}]
        for malformed in variants:
            with self.subTest(malformed=malformed), self.assertRaises(ProjectFileError):
                project_from_dict(malformed)

    def test_unknown_missing_and_wrong_typed_fields_are_rejected(self) -> None:
        original = project_to_dict(create_example_project())
        cases = [
            ("bool_string", lambda data: data.update(is_example="false")),
            ("bool_int", lambda data: data.update(is_example=0)),
            ("product_type", lambda data: data.update(product=[])),
            ("text_type", lambda data: data["product"].update(product_name=123)),
            ("list_type", lambda data: data.update(scenarios={})),
            ("numeric_type", lambda data: data["scenarios"][0]["pricing"].update(insurance_price=300)),
            ("unknown", lambda data: data["product"].update(extra="lost")),
            ("missing", lambda data: data["product"].pop("memo")),
            ("count_bool", lambda data: data["scenarios"][0]["pricing"]["metadata"].update(listed_product_count=True)),
            ("count_float", lambda data: data["scenarios"][0]["pricing"]["metadata"].update(listed_product_count=1.5)),
        ]
        for name, change in cases:
            data = deepcopy(original)
            change(data)
            with self.subTest(name=name), self.assertRaises(ProjectFileError):
                project_from_dict(data)

    def test_invalid_decimal_values_are_rejected_with_field_message(self) -> None:
        original = project_to_dict(create_example_project())
        for invalid in ("-1", "NaN", "Infinity", "-Infinity", "", "not a number", "1_000", "1e999999"):
            data = deepcopy(original)
            data["scenarios"][0]["materials"][0]["krw_price"] = invalid
            with self.subTest(value=invalid), self.assertRaisesRegex(ProjectFileError, "원화 구매단가"):
                project_from_dict(data)

    def test_yield_exchange_rate_and_conversion_quantity_must_be_valid(self) -> None:
        original = project_to_dict(create_example_project())
        cases = [
            ("yield0", lambda data: data["scenarios"][0].update(yield_percent="0")),
            ("yield101", lambda data: data["scenarios"][0].update(yield_percent="101")),
            ("exchange0", lambda data: data["scenarios"][0]["materials"][0].update(exchange_rate="0")),
            ("package0", lambda data: data["scenarios"][0]["packaging"].update(quantity="0")),
            ("labor_negative", lambda data: data["scenarios"][0]["labor"].update(amount="-1")),
            ("count_negative", lambda data: data["scenarios"][0]["pricing"]["metadata"].update(listed_product_count=-1)),
        ]
        for name, change in cases:
            data = deepcopy(original)
            change(data)
            with self.subTest(name=name), self.assertRaises(ProjectFileError):
                project_from_dict(data)

    def test_unknown_enum_values_are_rejected(self) -> None:
        original = project_to_dict(create_example_project())
        paths = [
            ("product", "dosage_form"),
            ("scenarios", 0, "materials", 0, "kind"),
            ("scenarios", 0, "materials", 0, "basis"),
            ("scenarios", 0, "materials", 0, "price_source"),
            ("scenarios", 0, "packaging", "basis"),
            ("scenarios", 0, "pricing", "metadata", "bioequivalence_requirement"),
        ]
        for path in paths:
            data = deepcopy(original)
            target = data
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = "invalid"
            with self.subTest(path=path), self.assertRaises(ProjectFileError):
                project_from_dict(data)

    def test_scenario_and_material_id_constraints(self) -> None:
        original = project_to_dict(create_example_project())
        cases = [
            ("no_scenarios", lambda data: data.update(scenarios=[])),
            ("active_missing", lambda data: data.update(active_scenario_id="missing")),
            ("active_empty", lambda data: data.update(active_scenario_id="")),
            ("scenario_id_empty", lambda data: data["scenarios"][0].update(id="")),
            ("duplicate_scenario", lambda data: data["scenarios"][1].update(id=data["scenarios"][0]["id"])),
            ("duplicate_material", lambda data: data["scenarios"][0]["materials"][1].update(id=data["scenarios"][0]["materials"][0]["id"])),
        ]
        for name, change in cases:
            data = deepcopy(original)
            change(data)
            with self.subTest(name=name), self.assertRaises(ProjectFileError):
                project_from_dict(data)

    def test_bad_json_and_duplicate_keys_have_readable_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            for content in (b"not json", b'{"format":"a","format":"b"}', b'{"value":NaN}', b"\xff"):
                path.write_bytes(content)
                with self.subTest(content=content), self.assertRaises(ProjectFileError):
                    load_project(path)
            with self.assertRaisesRegex(ProjectFileError, "열 수 없습니다"):
                load_project(Path(directory) / "missing.json")

    def test_file_size_limit_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.json"
            path.write_bytes(b"x" * 101)
            with patch("pharma_cost.storage.MAX_FILE_BYTES", 100), self.assertRaisesRegex(ProjectFileError, "초과"):
                load_project(path)
            with patch("pharma_cost.storage.MAX_FILE_BYTES", 100), self.assertRaisesRegex(ProjectFileError, "초과"):
                save_project(create_empty_project(), path)
            self.assertEqual(path.read_bytes(), b"x" * 101)

    def test_oversized_json_integer_has_readable_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversized-integer.json"
            path.write_text('{"huge":' + "9" * 5000 + "}", encoding="utf-8")
            with self.assertRaisesRegex(ProjectFileError, "JSON 형식이 올바르지 않습니다"):
                load_project(path)

    def test_failed_atomic_save_keeps_previous_file_and_removes_temporary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.json"
            path.write_text("기존 사용자 파일", encoding="utf-8")
            with patch("pharma_cost.storage.os.replace", side_effect=PermissionError("파일 사용 중")):
                with self.assertRaisesRegex(ProjectFileError, "저장할 수 없습니다"):
                    save_project(create_example_project(), path)
            self.assertEqual(path.read_text(encoding="utf-8"), "기존 사용자 파일")
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_validation_failure_never_overwrites_previous_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.json"
            path.write_text("기존 파일", encoding="utf-8")
            project = Project()
            project.active_scenario.yield_percent = Decimal("0")
            with self.assertRaises(ProjectFileError):
                save_project(project, path)
            self.assertEqual(path.read_text(encoding="utf-8"), "기존 파일")


if __name__ == "__main__":
    unittest.main()
