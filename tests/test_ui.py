"""실제 Qt 위젯을 통한 계산·프로젝트·시나리오 동작 검증."""
from decimal import Decimal

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QLineEdit, QMessageBox

from pharma_cost.models import Project
from pharma_cost.storage import load_project
from pharma_cost.ui.main_window import MainWindow


@pytest.fixture
def window(qapp):
    window = MainWindow()
    window.show()
    qapp.processEvents()
    yield window
    window.material_table.commit_pending_edit()
    window.dirty = False
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_example_and_comparison_are_real_results(window):
    assert window.project.is_example
    assert window.example_banner.isVisible()
    assert window.current_result.total_cost == Decimal("80")
    assert "26.67%" in window.result_labels["cost_rate"].text()
    assert "20.0000" in window.result_labels["required_saving"].text()
    assert window.comparison.columnCount() == 2
    assert "60.0000" in window.comparison.item(12, 1).text()
    assert window.comparison.item(17, 1).text() == "목표 달성"
    assert window.material_table.table.rowCount() == 3


def test_manual_price_change_refreshes_without_button(window):
    window.number_fields["pricing.insurance_price"].setText("400")
    assert window.current_result.cost_rate == Decimal("20")
    assert window.target_status.text() == "목표 달성"
    assert "사용자 입력값" in window.price_source_label.text()
    assert window.dirty
    window.number_fields["pricing.insurance_price"].setText("0")
    assert window.current_result.total_cost == Decimal("80")
    assert window.result_labels["cost_rate"].text() == "계산 불가"
    window.number_fields["pricing.insurance_price"].clear()
    assert window.current_result.total_cost == Decimal("80")
    assert window.current_result.cost_rate is None


def test_yield_and_cost_editing(window):
    window.yield_edit.setText("80")
    assert window.current_result.theoretical_material_cost == Decimal("50")
    assert window.current_result.adjusted_material_cost == Decimal("62.5")
    assert window.current_result.total_cost == Decimal("92.5")
    assert window.current_result.packaging_cost == Decimal("10")
    window.apply_yield.setChecked(False)
    assert window.current_result.adjusted_material_cost == Decimal("50")
    window.packaging_editor.amount.setText("600")
    assert window.current_result.packaging_cost == Decimal("20")
    assert window.current_result.total_cost == Decimal("90")
    window.packaging_editor.quantity.clear()
    assert window.current_result.packaging_cost is None
    assert window.result_labels["total_cost"].text() == "미완성"


def test_table_edit_add_delete_and_capsule_units(window):
    table = window.material_table.table
    table.item(0, 5).setText("40")
    assert window.current_result.api_cost == Decimal("60")
    assert window.current_result.total_cost == Decimal("100")
    window.material_table.add_excipient_button.click()
    assert table.rowCount() == 4
    assert window.current_result.total_cost is None
    table.cellWidget(3, 4).setCurrentIndex(table.cellWidget(3, 4).findData("piece"))
    table.item(3, 1).setText("캡슐 기제")
    table.item(3, 5).setText("1")
    table.item(3, 7).setText("15")
    assert window.current_result.total_cost == Decimal("115")
    window.dosage_form.setCurrentIndex(window.dosage_form.findData("capsule"))
    assert "원/캡슐" in window.summary.text()
    assert "캡슐" in table.horizontalHeaderItem(14).text()
    table.clearSelection()
    table.selectRow(3)
    window.material_table.delete_button.click()
    assert table.rowCount() == 3
    assert window.current_result.total_cost == Decimal("100")


def test_foreign_currency_source_is_explicit(window):
    table = window.material_table.table
    table.item(0, 8).setText("1000")
    table.item(0, 10).setText("1500")
    assert window.scenario.materials[0].krw_price == Decimal("1000000")
    assert window.current_result.material_results[0].cost == Decimal("20")
    table.cellWidget(0, 6).setCurrentIndex(table.cellWidget(0, 6).findData("fx"))
    assert window.current_result.material_results[0].unit_price == Decimal("1500000")
    assert window.current_result.material_results[0].cost == Decimal("30")
    assert window.current_result.total_cost == Decimal("90")


def test_duplicate_edit_keeps_original_and_scenario_switch(window):
    original = window.scenario
    clone = window.duplicate_scenario("API 변경안")
    assert clone is not None and clone.id != original.id
    window.material_table.table.item(0, 7).setText("500000")
    window.number_fields["pricing.insurance_price"].setText("400")
    assert clone.materials[0].krw_price == Decimal("500000")
    assert original.materials[0].krw_price == Decimal("1000000")
    assert original.pricing.insurance_price == Decimal("300")
    assert window.comparison.columnCount() == 3
    assert "70.0000" in window.comparison.item(12, 2).text()
    window.scenario_combo.setCurrentIndex(window.scenario_combo.findData(original.id))
    assert window.scenario is original
    assert window.number_fields["pricing.insurance_price"].text() == "300"


def test_save_open_all_scenarios_and_metadata(window, tmp_path, monkeypatch):
    window.metadata_fields["participation_form"].setText("자료 공동 확보")
    window.metadata_fields["product_type"].setText("개량신약")
    window.product_fields["memo"].setPlainText("공통 제품정보 메모")
    window.duplicate_scenario("복제 저장안")
    path = tmp_path / "복합제 프로젝트.json"
    assert window.save_current_project(path)
    assert not window.dirty
    assert load_project(path).active_scenario.pricing.metadata.product_type == "개량신약"
    assert window.new_project()
    assert window.material_table.table.rowCount() == 0
    assert not window.example_banner.isVisible()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))
    assert window.open_project()
    assert window.comparison.columnCount() == 3
    assert window.metadata_fields["participation_form"].text() == "자료 공동 확보"
    assert window.product_fields["memo"].toPlainText() == "공통 제품정보 메모"
    another = tmp_path / "다른 이름.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(another), ""))
    assert window.save_current_project(save_as=True)
    assert another.exists() and path.exists()
    assert window.file_path == another


def test_uncommitted_editor_is_saved_by_ctrl_s(window, qapp, tmp_path):
    path = tmp_path / "편집중.json"
    window.file_path = path
    window.tabs.setCurrentIndex(1)
    table = window.material_table.table
    table.setCurrentCell(0, 5)
    table.editItem(table.item(0, 5))
    qapp.processEvents()
    editor = next(e for e in table.findChildren(QLineEdit) if e.isVisible())
    editor.selectAll()
    QTest.keyClicks(editor, "30")
    QTest.keyClick(editor, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    qapp.processEvents()
    assert load_project(path).active_scenario.materials[0].amount == Decimal("30")
    assert window.current_result.total_cost == Decimal("90")
    assert not window.dirty


def test_invalid_input_is_visible_and_cannot_silently_save(window, tmp_path, monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: messages.append(a[2]))
    table = window.material_table.table
    table.item(0, 5).setText("-1")
    assert table.item(0, 5).text() == "-1"
    assert window.current_result.total_cost is None
    assert table.item(0, 5).toolTip()
    assert not window.save_current_project(tmp_path / "不保存.json")
    original_id = window.project.active_scenario_id
    window.scenario_combo.setCurrentIndex(1)
    assert window.project.active_scenario_id == original_id
    assert table.item(0, 5).text() == "-1"
    assert messages
    table.item(0, 5).setText("")
    assert window.save_current_project(tmp_path / "미완성.json")
    assert load_project(tmp_path / "미완성.json").active_scenario.materials[0].amount is None


@pytest.mark.parametrize("bad", ["0", "-1", "101", "문자", "NaN", "1e10000000"])
def test_yield_invalid_range_marks_incomplete(window, bad):
    window.yield_edit.setText(bad)
    assert window.yield_edit.raw_error
    assert window.current_result.total_cost is None


def test_dirty_close_cancel_and_save(window, tmp_path, monkeypatch):
    window.product_fields["project_name"].setText("새 이름")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
    assert not window.new_project()
    path = tmp_path / "종료 전 저장.json"
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Save)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()
    assert load_project(path).product.project_name == "새 이름"


def test_dirty_open_cancel_and_bad_file_preserve_project(window, tmp_path, monkeypatch):
    original = window.project
    window.product_fields["project_name"].setText("저장 안 된 이름")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    assert not window.open_project(tmp_path / "없음.json")
    assert window.project is original
    window.dirty = False
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    bad = tmp_path / "잘못된.json"
    bad.write_text('{"schema_version":99}', encoding="utf-8")
    assert not window.open_project(bad)
    assert window.project is original
    assert warnings


def test_empty_project_missing_price_does_not_hide_cost(qapp):
    window = MainWindow(Project())
    assert window.current_result.total_cost == Decimal("0")
    assert window.result_labels["cost_rate"].text() == "계산 불가"
    window.close()


def test_extension_added_target_requires_overwrite_confirmation(window, tmp_path, monkeypatch):
    target = tmp_path / "기존 파일.json"
    target.write_text("기존 내용", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / "기존 파일"), ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    assert not window.save_current_project(save_as=True)
    assert target.read_text(encoding="utf-8") == "기존 내용"
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    assert window.save_current_project(save_as=True)
    assert load_project(target).is_example
