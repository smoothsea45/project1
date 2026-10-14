"""Qt 화면용 숫자 입력과 고정비 입력. 계산 규칙은 도메인 모듈에 둔다."""
from decimal import Decimal, InvalidOperation
import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QLabel, QLineEdit, QPlainTextEdit, QWidget,
)


class NumberEdit(QLineEdit):
    value_changed = Signal(object)

    def __init__(self, *, positive=False, integer=False, maximum=None, parent=None):
        super().__init__(parent)
        self.positive = positive
        self.integer = integer
        self.maximum = Decimal(str(maximum)) if maximum is not None else None
        self.raw_error = ""
        self.setPlaceholderText("미입력")
        self.setToolTip("숫자를 입력하세요. 천 단위 쉼표 없이 입력합니다. 빈칸은 미입력으로 저장됩니다.")
        self.textChanged.connect(self._parse)

    def _parse(self, text):
        self.raw_error = ""
        value = None
        stripped = text.strip()
        if stripped:
            try:
                if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", stripped):
                    raise InvalidOperation
                value = Decimal(stripped)
                if len(stripped) > 128 or not value.is_finite() or abs(value.adjusted()) > 1000:
                    self.raw_error = "숫자가 지원 범위를 벗어났습니다 (128자, 지수 ±1000 이내)."
                elif value < 0:
                    self.raw_error = "0 이상의 유한한 숫자를 입력하세요."
                elif self.positive and value <= 0:
                    self.raw_error = "0보다 큰 숫자를 입력하세요."
                elif self.maximum is not None and value > self.maximum:
                    self.raw_error = f"{self.maximum} 이하의 숫자를 입력하세요."
                elif self.integer and value != value.to_integral_value():
                    self.raw_error = "정수로 입력하세요."
                if self.raw_error:
                    value = None
                elif self.integer:
                    value = int(value)
            except (InvalidOperation, ValueError, OverflowError):
                self.raw_error = "올바른 숫자를 입력하세요."
                value = None
        self.mark_issue(self.raw_error)
        self.value_changed.emit(value)

    def set_value(self, value):
        self.setText("" if value is None else str(value))

    def mark_issue(self, message=""):
        message = self.raw_error or message
        self.setStyleSheet("QLineEdit { border: 1px solid #bc3540; background: #fff1f2; }" if message else "")
        self.setToolTip(message or "숫자를 입력하세요. 빈칸은 미입력으로 저장됩니다.")


class CostEditor(QWidget):
    changed = Signal()

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.cost = None
        self._loading = False
        self.unit_label = "정"
        layout = QFormLayout(self)
        self.basis = QComboBox()
        for text, data in [("원/단위제형", "unit"), ("원/포장", "package"), ("원/배치", "batch")]:
            self.basis.addItem(text, data)
        self.amount = NumberEdit()
        self.quantity = NumberEdit(positive=True)
        self.quantity_label = QLabel("환산 수량")
        self.amount_label = QLabel("전달받은 금액")
        self.memo = QPlainTextEdit()
        self.memo.setMaximumHeight(80)
        self.memo.setPlaceholderText("QC 비용·제조간접비 등이 포함되어 있는지 기록하세요.")
        self.converted = QLabel("미완성")
        self.converted.setObjectName(name + "_converted")
        layout.addRow("입력 방식", self.basis)
        layout.addRow(self.amount_label, self.amount)
        layout.addRow(self.quantity_label, self.quantity)
        layout.addRow("포함 비용·근거 메모", self.memo)
        layout.addRow("단위제형 환산 비용", self.converted)
        self.basis.currentIndexChanged.connect(self._basis_changed)
        self.amount.value_changed.connect(lambda value: self._set("amount", value))
        self.quantity.value_changed.connect(lambda value: self._set("quantity", value))
        self.memo.textChanged.connect(lambda: self._set("memo", self.memo.toPlainText()))

    def load(self, cost, unit_label):
        self._loading = True
        self.cost = cost
        self.unit_label = unit_label
        self.basis.setCurrentIndex(self.basis.findData(cost.basis))
        self.amount.set_value(cost.amount)
        self.quantity.set_value(cost.quantity)
        self.memo.setPlainText(cost.memo)
        self._update_labels()
        self._loading = False

    def _set(self, field, value):
        if self._loading or self.cost is None:
            return
        setattr(self.cost, field, value)
        self.changed.emit()

    def _basis_changed(self):
        self._update_labels()
        self._set("basis", self.basis.currentData())

    def _update_labels(self):
        basis = self.basis.currentData()
        self.quantity.setEnabled(basis != "unit")
        suffix = {"unit": self.unit_label, "package": "포장", "batch": "배치"}.get(basis, "정")
        self.amount_label.setText(f"전달받은 금액 (원/{suffix})")
        self.quantity_label.setText(f"{'포장당 수량' if basis == 'package' else '배치당 양품 수량'} ({self.unit_label})")

    def apply_result(self, value, issues, prefix):
        self.converted.setText("미완성" if value is None else f"{value:,.4f} 원/{self.unit_label}")
        for field in ["amount", "quantity"]:
            message = next((i.message for i in issues if i.path == f"{prefix}.{field}"), "")
            getattr(self, field).mark_issue(message)
