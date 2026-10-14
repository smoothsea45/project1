"""원료를 표로 편집하는 오프라인 입력 화면."""

from __future__ import annotations

import csv
import io
import re
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pharma_cost.calculation import MaterialResult, ValidationIssue
from pharma_cost.models import Material


FIELDS = (
    "kind", "name", "specification", "supplier", "basis", "amount",
    "price_source", "krw_price", "foreign_price", "currency", "exchange_rate",
    "quotation_date", "memo", "resolved_price", "resolved_cost",
)
NUMERIC_COLUMNS = {5, 7, 8, 10}
COMBO_OPTIONS = {
    0: (("API", "api"), ("부형제", "excipient")),
    4: (("질량 (mg)", "mass"), ("개당 구매 (개)", "piece")),
    6: (("원화 직접 입력", "krw"), ("외화 환산", "fx")),
}
COMBO_ALIASES = {
    0: {"api": "api", "excipient": "excipient", "부형제": "excipient"},
    4: {
        "mass": "mass", "질량": "mass", "mg": "mass", "질량 (mg)": "mass",
        "piece": "piece", "개": "piece", "개당 구매": "piece", "개당 구매 (개)": "piece",
    },
    6: {
        "krw": "krw", "원화": "krw", "원화 직접": "krw", "원화 직접 입력": "krw",
        "fx": "fx", "외화": "fx", "외화 환산": "fx",
    },
}


def _decimal_text(value: Decimal | None) -> str:
    return "" if value is None else str(value)


def _result_text(value: Decimal | None) -> str:
    if value is None or not value.is_finite():
        return "미완성"
    return f"{value:,.4f}".rstrip("0").rstrip(".")


class _MaterialGrid(QTableWidget):
    """Qt의 셀 편집에 표 범위 복사·붙여넣기를 추가한다."""

    paste_requested = Signal(str)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste_requested.emit(QApplication.clipboard().text())
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Copy):
            indexes = self.selectedIndexes()
            if indexes:
                selected = {(index.row(), index.column()) for index in indexes}
                first_row = min(row for row, _ in selected)
                last_row = max(row for row, _ in selected)
                first_column = min(column for _, column in selected)
                last_column = max(column for _, column in selected)
                output = io.StringIO()
                writer = csv.writer(output, delimiter="\t", lineterminator="\n")
                for row in range(first_row, last_row + 1):
                    values = []
                    for column in range(first_column, last_column + 1):
                        if (row, column) not in selected:
                            values.append("")
                            continue
                        combo = self.cellWidget(row, column)
                        item = self.item(row, column)
                        values.append(combo.currentText() if isinstance(combo, QComboBox) else item.text() if item else "")
                    writer.writerow(values)
                QApplication.clipboard().setText(output.getvalue().rstrip("\n"))
            event.accept()
            return
        super().keyPressEvent(event)


class MaterialTable(QWidget):
    """Material 목록을 직접 편집하며, 변경 한 번에 changed를 한 번 보낸다.

    숫자 입력 원문은 표에 남기고, 계산 가능한 값만 모델에 반영한다.
    숫자 오류가 있는 상태에서 다른 시나리오로 이동하거나 저장할 때는
    부모 화면이 has_raw_errors()를 확인해야 한다.
    """

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._materials: list[Material] = []
        self._unit_label = "정"
        self._updating = 0
        self._raw_errors: dict[tuple[int, int], str] = {}
        self._domain_errors: dict[tuple[int, int], list[str]] = {}
        self._results: dict[str, MaterialResult] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        guide = QLabel(
            "표를 직접 편집하거나 엑셀의 셀 범위를 복사해 붙여넣으세요 (Ctrl+C / Ctrl+V). "
            "실제 투입량은 표시 함량과 별개이며, 염·역가 보정은 하지 않습니다.\n"
            "질량: mg × 원/kg ÷ 1,000,000 · 개당 구매: 사용 개수 × 원/개. "
            "외화 환산: 외화 단가 × 입력 환율 (환율 자동 조회 없음)."
        )
        guide.setWordWrap(True)
        layout.addWidget(guide)

        controls = QHBoxLayout()
        self.add_api_button = QPushButton("API 추가")
        self.add_excipient_button = QPushButton("부형제 추가")
        self.delete_button = QPushButton("선택 행 삭제")
        self.add_api_button.setObjectName("add_api_button")
        self.add_excipient_button.setObjectName("add_excipient_button")
        self.delete_button.setObjectName("delete_material_button")
        self.add_api_button.clicked.connect(lambda: self.add_material("api"))
        self.add_excipient_button.clicked.connect(lambda: self.add_material("excipient"))
        self.delete_button.clicked.connect(self.delete_selected_rows)
        controls.addWidget(self.add_api_button)
        controls.addWidget(self.add_excipient_button)
        controls.addWidget(self.delete_button)
        controls.addStretch()
        layout.addLayout(controls)

        self.table = _MaterialGrid(0, len(FIELDS))
        self.table.setObjectName("materials_table")
        self.table.setAlternatingRowColors(False)
        self.table.setSortingEnabled(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        self.table.setTabKeyNavigation(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.itemChanged.connect(self._item_changed)
        self.table.paste_requested.connect(self.paste_tsv)
        layout.addWidget(self.table)
        self.set_unit_label("정")
        widths = (100, 160, 135, 160, 130, 125, 145, 150, 135, 80, 110, 110, 190, 155, 135)
        for column, width in enumerate(widths):
            self.table.setColumnWidth(column, width)

    @property
    def materials(self) -> list[Material]:
        return self._materials

    @contextmanager
    def _suspend(self):
        self._updating += 1
        try:
            yield
        finally:
            self._updating -= 1

    def set_materials(self, materials: list[Material]) -> None:
        """전달받은 목록을 복제하지 않고 편집 대상으로 사용한다."""
        self._materials = materials
        self._raw_errors.clear()
        self._domain_errors.clear()
        self._results.clear()
        self._rebuild()

    def set_unit_label(self, unit_label: str) -> None:
        self._unit_label = unit_label
        self.table.setHorizontalHeaderLabels((
            "구분", "원료명", "등급·규격", "제조원·공급처", "계산 기준",
            f"실제 투입량\n(mg/{unit_label}·개/{unit_label})", "단가 입력 방식",
            "원화 직접 단가\n(원/kg·원/개)", "외화 단가\n(통화/kg·통화/개)",
            "통화", "환율\n(원/통화)", "견적일", "메모",
            "적용 원화 단가\n(원/kg·원/개)", f"원료 비용\n(원/{unit_label})",
        ))
        with self._suspend():
            self._refresh_styles()

    def _rebuild(self, preserve_text: bool = False) -> None:
        snapshots: dict[tuple[int, int], str] = {}
        if preserve_text:
            # 삭제 전과 새 목록의 행 위치가 다르므로 모델 객체 식별자를 사용한다.
            for row in range(self.table.rowCount()):
                for column in range(len(FIELDS)):
                    item = self.table.item(row, column)
                    if item is not None and column < 13:
                        snapshots[(item.data(Qt.ItemDataRole.UserRole), column)] = item.text()
        self._raw_errors.clear()
        with self._suspend():
            self.table.clearContents()
            self.table.setRowCount(len(self._materials))
            for row, material in enumerate(self._materials):
                for column, field_name in enumerate(FIELDS):
                    if column in COMBO_OPTIONS:
                        combo = QComboBox()
                        combo.setObjectName(f"material_{row}_{field_name}")
                        combo.setProperty("material_identity", id(material))
                        combo.setProperty("material_column", column)
                        combo.installEventFilter(self)
                        for label, value in COMBO_OPTIONS[column]:
                            combo.addItem(label, value)
                        combo.setCurrentIndex(combo.findData(getattr(material, field_name)))
                        combo.currentIndexChanged.connect(
                            lambda index, target=material, col=column: self._combo_changed(target, col)
                        )
                        self.table.setCellWidget(row, column, combo)
                        continue
                    if column >= 13:
                        text = "미완성"
                    elif (id(material), column) in snapshots:
                        text = snapshots[(id(material), column)]
                    elif column in NUMERIC_COLUMNS:
                        text = _decimal_text(getattr(material, field_name))
                    else:
                        text = getattr(material, field_name)
                    item = QTableWidgetItem(text)
                    item.setData(Qt.ItemDataRole.UserRole, id(material))
                    if column in NUMERIC_COLUMNS or column >= 13:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.table.setItem(row, column, item)
                self._parse_row(row)
            self._render_results()
            self._refresh_styles()

    def add_material(self, kind: str = "api") -> None:
        if kind not in ("api", "excipient"):
            raise ValueError("원료 구분은 API 또는 부형제여야 합니다.")
        self.commit_pending_edit()
        self._materials.append(Material(kind=kind))
        self._rebuild(preserve_text=True)
        self.table.setCurrentCell(len(self._materials) - 1, 1)
        self.changed.emit()

    def delete_selected_rows(self) -> None:
        self.commit_pending_edit()
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            return
        for row in rows:
            del self._materials[row]
        self._domain_errors.clear()
        self._rebuild(preserve_text=True)
        self.changed.emit()

    def _parse_number(self, row: int, column: int) -> Decimal | None:
        item = self.table.item(row, column)
        text = item.text().strip() if item else ""
        self._raw_errors.pop((row, column), None)
        if not text:
            return None
        try:
            # 천 단위 쉼표는 표시·붙여넣기 편의를 위해 허용한다.
            if "," in text and not re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d*)?(?:[eE][+-]?\d+)?", text):
                raise InvalidOperation
            normalized_text = text.replace(",", "")
            if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", normalized_text):
                raise InvalidOperation
            value = Decimal(normalized_text)
        except (InvalidOperation, ValueError):
            self._raw_errors[(row, column)] = "숫자를 입력해 주세요."
            return None
        if not value.is_finite():
            self._raw_errors[(row, column)] = "유한한 숫자를 입력해 주세요."
            return None
        if len(str(value)) > 128 or abs(value.adjusted()) > 1000:
            self._raw_errors[(row, column)] = "숫자가 너무 크거나 작습니다. 일반적인 범위의 값을 입력해 주세요."
            return None
        if value < 0:
            self._raw_errors[(row, column)] = "음수는 입력할 수 없습니다."
            return None
        if column == 10 and value == 0:
            self._raw_errors[(row, column)] = "환율은 0보다 커야 합니다."
            return None
        return value

    def _parse_row(self, row: int) -> None:
        for column in NUMERIC_COLUMNS:
            setattr(self._materials[row], FIELDS[column], self._parse_number(row, column))

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating or item.row() >= len(self._materials):
            return
        row, column = item.row(), item.column()
        if column >= 13 or column in COMBO_OPTIONS:
            return
        if column in NUMERIC_COLUMNS:
            setattr(self._materials[row], FIELDS[column], self._parse_number(row, column))
        else:
            setattr(self._materials[row], FIELDS[column], item.text())
        self._domain_errors.clear()
        with self._suspend():
            self._refresh_styles()
        self.changed.emit()

    def _combo_changed(self, material: Material, column: int) -> None:
        if self._updating:
            return
        row = next((index for index, candidate in enumerate(self._materials) if candidate is material), None)
        if row is None:
            return
        combo = self.table.cellWidget(row, column)
        setattr(material, FIELDS[column], combo.currentData())
        self._parse_row(row)
        self._domain_errors.clear()
        with self._suspend():
            self._refresh_styles()
        self.changed.emit()

    def eventFilter(self, watched, event) -> bool:
        # 콤보를 클릭한 뒤 붙여넣어도 이전에 선택한 셀이 아닌 해당 셀에서 시작한다.
        if isinstance(watched, QComboBox) and event.type() == QEvent.Type.FocusIn:
            identity = watched.property("material_identity")
            row = next((index for index, material in enumerate(self._materials) if id(material) == identity), None)
            if row is not None and not self._updating:
                self.table.setCurrentCell(row, watched.property("material_column"))
        return super().eventFilter(watched, event)

    def has_raw_errors(self) -> bool:
        """빈칸을 제외한 잘못된 숫자 원문이 현재 표에 있는지 반환한다."""
        return bool(self._raw_errors)

    def commit_pending_edit(self) -> None:
        """아직 Enter를 누르지 않은 셀 편집 내용도 모델에 반영한다."""
        for editor in self.table.viewport().findChildren(QLineEdit):
            if editor.isVisible() and editor.parent() is self.table.viewport():
                self.table.commitData(editor)
                self.table.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)

    def numeric_errors(self) -> list[str]:
        return [
            f"원료 {row + 1}행 · {self.table.horizontalHeaderItem(column).text().splitlines()[0]}: {message}"
            for (row, column), message in sorted(self._raw_errors.items())
        ]

    def apply_results(
        self,
        material_results: list[MaterialResult],
        issues: list[ValidationIssue],
        unit_label: str,
    ) -> None:
        self._results = {result.material_id: result for result in material_results}
        self._domain_errors.clear()
        for row, material in enumerate(self._materials):
            prefix = f"materials.{material.id}."
            for issue in issues:
                if issue.path.startswith(prefix):
                    field_name = issue.path[len(prefix):]
                    if field_name in FIELDS:
                        self._domain_errors.setdefault((row, FIELDS.index(field_name)), []).append(issue.message)
        with self._suspend():
            self.set_unit_label(unit_label)
            self._render_results()
            self._refresh_styles()

    def _render_results(self) -> None:
        for row, material in enumerate(self._materials):
            result = self._results.get(material.id)
            for column, value in ((13, result.unit_price if result else None), (14, result.cost if result else None)):
                item = self.table.item(row, column)
                if item:
                    item.setText(_result_text(value))
                    item.setToolTip("계산에 필요한 입력이 미완성입니다." if value is None else str(value))

    def _refresh_styles(self) -> None:
        for row, material in enumerate(self._materials):
            inactive = {8, 9, 10} if material.price_source == "krw" else {7}
            required = {5, 7} if material.price_source == "krw" else {5, 8, 9, 10}
            for column in range(len(FIELDS)):
                item = self.table.item(row, column)
                messages = list(self._domain_errors.get((row, column), []))
                if (row, column) in self._raw_errors:
                    messages.insert(0, self._raw_errors[(row, column)])
                if item is not None and column in required and not item.text().strip():
                    messages.insert(0, "계산에 필요한 입력값이 비어 있습니다.")
                combo = self.table.cellWidget(row, column)
                if isinstance(combo, QComboBox):
                    combo.setToolTip("\n".join(dict.fromkeys(messages)))
                    combo.setStyleSheet("QComboBox { background: #fff1f1; color: #b00020; }" if messages else "")
                    continue
                if item is None:
                    continue
                flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
                if column < 13:
                    flags |= Qt.ItemFlag.ItemIsEditable
                item.setFlags(flags)
                item.setBackground(QColor("#eef6fb" if column >= 13 else "#f1f3f5" if column in inactive else "#ffffff"))
                item.setForeground(QColor("#7a838e" if column in inactive else "#20262e"))
                if column < 13:
                    unit = "원/kg" if material.basis == "mass" else "원/개"
                    tooltip = ""
                    if column in inactive:
                        tooltip = "현재 단가 입력 방식에서는 계산에 사용하지 않는 보관값입니다. 수정하거나 비워둘 수 있습니다."
                    elif column == 5:
                        tooltip = f"{'mg' if material.basis == 'mass' else '개'}/{self._unit_label} 기준 실제 투입량"
                    elif column == 7:
                        tooltip = f"직접 입력한 구매단가 ({unit})를 사용합니다."
                    elif column == 8:
                        tooltip = "외화 구매단가 × 입력 환율로 원화 구매단가를 계산합니다."
                    elif column == 11:
                        tooltip = "견적일은 자유 입력입니다. 예: 2026-10-14"
                    item.setToolTip(tooltip)
                if messages:
                    item.setBackground(QColor("#fff1f1"))
                    item.setForeground(QColor("#b00020"))
                    item.setToolTip("\n".join(dict.fromkeys(messages)))

    def paste_tsv(self, text: str) -> None:
        """현재 셀부터 TSV를 붙이고 전체 입력에 changed를 한 번 보낸다."""
        if not text:
            return
        self.commit_pending_edit()
        try:
            rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
        except csv.Error:
            QMessageBox.warning(self, "붙여넣기 오류", "표 내용을 읽을 수 없습니다. 탭으로 구분된 셀을 복사해 주세요.")
            return
        if not rows:
            return
        first_row = max(0, self.table.currentRow())
        first_column = max(0, self.table.currentColumn())
        if first_column >= 13:
            return
        # 선택 항목은 적용 전에 전체 확인하여 잘못된 값이 조용히 유실되지 않게 한다.
        combo_values: dict[tuple[int, int], str] = {}
        for offset, values in enumerate(rows):
            for column_offset, text_value in enumerate(values):
                column = first_column + column_offset
                if column in COMBO_OPTIONS:
                    value = COMBO_ALIASES[column].get(text_value.strip().lower())
                    if value is None:
                        QMessageBox.warning(
                            self, "붙여넣기 오류",
                            f"{offset + 1}행의 ‘{text_value}’는 지원하는 선택값이 아닙니다.\n"
                            f"가능한 값: {', '.join(label for label, _ in COMBO_OPTIONS[column])}",
                        )
                        return
                    combo_values[(first_row + offset, column)] = value
        with self._suspend():
            needed_rows = first_row + len(rows)
            if needed_rows > len(self._materials):
                self._materials.extend(Material() for _ in range(needed_rows - len(self._materials)))
                self._rebuild(preserve_text=True)
            # 단가 입력 방식을 먼저 적용해야 외화/원화의 보관값도 함께 붙일 수 있다.
            for (row, column), value in combo_values.items():
                self.table.cellWidget(row, column).setCurrentIndex(
                    self.table.cellWidget(row, column).findData(value)
                )
                setattr(self._materials[row], FIELDS[column], value)
            for offset, values in enumerate(rows):
                row = first_row + offset
                for column_offset, text_value in enumerate(values):
                    column = first_column + column_offset
                    if column >= 13 or column in COMBO_OPTIONS:
                        continue
                    item = self.table.item(row, column)
                    if item is not None:
                        item.setText(text_value)
                        if column not in NUMERIC_COLUMNS:
                            setattr(self._materials[row], FIELDS[column], text_value)
                self._parse_row(row)
            self._domain_errors.clear()
            self._refresh_styles()
        self.changed.emit()
