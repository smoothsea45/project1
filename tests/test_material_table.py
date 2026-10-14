"""실제 Qt 입력표의 편집·붙여넣기·오류 보존을 검증한다."""

from decimal import Decimal

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from pharma_cost.calculation import calculate
from pharma_cost.models import Material, Scenario
from pharma_cost.ui.material_table import MaterialTable


@pytest.fixture
def material_table(qapp):
    widget = MaterialTable()
    yield widget
    widget.close()
    widget.deleteLater()
    qapp.processEvents()


def example_material(name="성분 A", **kwargs):
    return Material(name=name, amount=Decimal("20"), krw_price=Decimal("1000000"), **kwargs)


def connect_calculation(widget, scenario):
    updates = []

    def refresh():
        result = calculate(scenario)
        widget.apply_results(result.material_results, result.issues, "정")
        updates.append(result)

    widget.changed.connect(refresh)
    return updates


def test_setting_materials_is_silent_and_edits_recalculate(material_table):
    materials = [example_material()]
    scenario = Scenario(materials=materials)
    updates = connect_calculation(material_table, scenario)
    material_table.set_materials(materials)
    assert material_table.materials is materials
    assert not updates

    material_table.table.item(0, 5).setText("25")
    assert materials[0].amount == Decimal("25")
    assert len(updates) == 1
    assert updates[-1].theoretical_material_cost == Decimal("25")
    assert material_table.table.item(0, 14).text() == "25"
    assert not (material_table.table.item(0, 13).flags() & Qt.ItemFlag.ItemIsEditable)
    assert not (material_table.table.item(0, 14).flags() & Qt.ItemFlag.ItemIsEditable)


@pytest.mark.parametrize("text", ["-1", "NaN", "Infinity", "숫자 아님", "1,2", "1_000", "1e10000000"])
def test_invalid_amount_remains_visible_and_blocks_completed_cost(material_table, text):
    material = example_material()
    scenario = Scenario(materials=[material])
    material_table.set_materials(scenario.materials)
    updates = connect_calculation(material_table, scenario)
    material_table.table.item(0, 5).setText(text)

    assert material.amount is None
    assert material_table.table.item(0, 5).text() == text
    assert material_table.has_raw_errors()
    assert material_table.numeric_errors()
    assert material_table.table.item(0, 5).toolTip()
    assert updates[-1].total_cost is None
    assert material_table.table.item(0, 14).text() == "미완성"


def test_blank_amount_is_incomplete_but_not_a_raw_error(material_table):
    scenario = Scenario(materials=[example_material()])
    material_table.set_materials(scenario.materials)
    updates = connect_calculation(material_table, scenario)
    material_table.table.item(0, 5).setText("")
    assert scenario.materials[0].amount is None
    assert not material_table.has_raw_errors()
    assert not material_table.numeric_errors()
    assert updates[-1].material_results[0].cost is None
    assert "입력" in material_table.table.item(0, 5).toolTip()


@pytest.mark.parametrize("source", ["krw", "fx"])
def test_entered_exchange_rate_must_be_positive_even_when_inactive(material_table, source):
    material = example_material(price_source=source, foreign_price=Decimal("2"), exchange_rate=Decimal("1400"))
    material_table.set_materials([material])
    material_table.table.item(0, 10).setText("0")
    assert material_table.has_raw_errors()
    assert material.exchange_rate is None
    assert "0보다" in material_table.table.item(0, 10).toolTip()
    material_table.table.item(0, 10).setText("1500")
    assert not material_table.has_raw_errors()
    assert material.exchange_rate == Decimal("1500")
    # 비활성 입력도 수정할 수 있고 현재 계산에 쓰는 방식은 콤보로 구분한다.
    assert material_table.table.item(0, 10).flags() & Qt.ItemFlag.ItemIsEditable


def test_add_buttons_preserve_invalid_input(material_table):
    materials = [example_material()]
    material_table.set_materials(materials)
    material_table.table.item(0, 5).setText("-5")
    material_table.add_api_button.click()
    material_table.add_excipient_button.click()
    assert [material.kind for material in materials] == ["api", "api", "excipient"]
    assert material_table.table.item(0, 5).text() == "-5"
    assert material_table.has_raw_errors()


def test_multiple_row_delete_preserves_other_raw_text_and_combo_bindings(material_table):
    materials = [example_material(name) for name in ("A", "B", "C", "D")]
    material_table.set_materials(materials)
    material_table.table.item(1, 5).setText("-9")
    selection = material_table.table.selectionModel()
    material_table.table.clearSelection()
    for row in (0, 2):
        selection.select(material_table.table.model().index(row, 1), QItemSelectionModel.SelectionFlag.Select)
    changes = []
    material_table.changed.connect(lambda: changes.append(1))
    material_table.delete_button.click()
    assert [material.name for material in materials] == ["B", "D"]
    assert material_table.table.item(0, 5).text() == "-9"
    assert material_table.has_raw_errors()
    assert len(changes) == 1

    material_table.table.cellWidget(1, 0).setCurrentIndex(1)
    material_table.table.cellWidget(1, 4).setCurrentIndex(1)
    assert materials[1].kind == "excipient"
    assert materials[1].basis == "piece"
    assert materials[0].kind == "api"
    material_table.table.item(0, 5).setText("20")
    assert not material_table.has_raw_errors()


def test_tsv_paste_adds_rows_and_emits_once_with_costs_recalculated(material_table):
    scenario = Scenario(materials=[])
    material_table.set_materials(scenario.materials)
    updates = connect_calculation(material_table, scenario)
    material_table.paste_tsv(
        "API\t성분 A\t규격\t공급처 A\tmg\t20\t원화\t1,000,000\t\tUSD\t\t2026-10-14\t메모\t999\t999\n"
        "부형제\t캡슐 기제\t\t공급처 B\t개\t1\t외화\t\t0.002\tUSD\t1500\t\t"
    )
    assert len(updates) == 1
    assert len(scenario.materials) == 2
    assert scenario.materials[0].amount == Decimal("20")
    assert scenario.materials[0].krw_price == Decimal("1000000")
    assert scenario.materials[1].basis == "piece"
    assert scenario.materials[1].price_source == "fx"
    assert updates[0].api_cost == Decimal("20")
    assert updates[0].excipient_cost == Decimal("3")
    assert material_table.table.item(0, 14).text() == "20"
    assert material_table.table.item(1, 14).text() == "3"
    assert not material_table.has_raw_errors()


def test_keyboard_copy_paste_round_trip(material_table):
    material_table.set_materials([example_material()])
    selection = material_table.table.selectionModel()
    for column in range(8):
        selection.select(material_table.table.model().index(0, column), QItemSelectionModel.SelectionFlag.Select)
    QTest.keyClick(material_table.table, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    copied = QApplication.clipboard().text()
    assert "성분 A" in copied and "1000000" in copied

    material_table.add_material()
    material_table.table.setCurrentCell(1, 0)
    QTest.keyClick(material_table.table, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    original, duplicate = material_table.materials
    assert duplicate.name == original.name
    assert duplicate.amount == original.amount
    assert duplicate.krw_price == original.krw_price
    assert duplicate.id != original.id


@pytest.mark.parametrize("text,expected", [("35", Decimal("35")), ("-5", None)])
def test_pending_delegate_text_is_committed_before_save_guard(material_table, qapp, text, expected):
    material = example_material()
    material_table.set_materials([material])
    material_table.show()
    qapp.processEvents()
    material_table.table.setCurrentCell(0, 5)
    material_table.table.editItem(material_table.table.item(0, 5))
    qapp.processEvents()
    editors = [editor for editor in material_table.table.viewport().findChildren(QLineEdit) if editor.isVisible()]
    assert len(editors) == 1
    editors[0].setText(text)
    # Enter를 누르거나 포커스를 옮기기 전에는 모델에 원래 값이 남아 있다.
    assert material.amount == Decimal("20")
    material_table.commit_pending_edit()
    assert material.amount == expected
    assert material_table.table.item(0, 5).text() == text
    assert material_table.has_raw_errors() == (expected is None)


def test_delete_commits_pending_edit_on_a_retained_row(material_table, qapp):
    materials = [example_material("A"), example_material("B")]
    material_table.set_materials(materials)
    material_table.show()
    qapp.processEvents()
    material_table.table.editItem(material_table.table.item(1, 5))
    qapp.processEvents()
    editor = next(editor for editor in material_table.table.viewport().findChildren(QLineEdit) if editor.isVisible())
    editor.setText("-9")
    # 명시적으로 다른 행만 선택하되 열려 있는 편집기를 아직 종료하지 않는다.
    material_table.table.clearSelection()
    material_table.table.selectionModel().select(
        material_table.table.model().index(0, 1), QItemSelectionModel.SelectionFlag.Select,
    )
    material_table.delete_selected_rows()
    assert [material.name for material in materials] == ["B"]
    assert material_table.table.item(0, 5).text() == "-9"
    assert material_table.has_raw_errors()
