"""추가 차트 라이브러리 없이 Qt로 그리는 비용 구성 막대."""
from decimal import Decimal

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


class CostChart(QWidget):
    COLORS = ["#2666b3", "#43a6a0", "#e9ae39", "#9262b3"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.costs = []
        self.unit_label = "정"
        self.setMinimumHeight(170)
        self.setAccessibleName("수율 보정 후 비용 구성 차트")

    def set_costs(self, costs, unit_label):
        self.costs = costs
        self.unit_label = unit_label
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor("#24344b"))
        if not self.costs or any(v is None for _, v in self.costs):
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "필수 비용 입력을 완료하면 비용 구성이 표시됩니다.")
            return
        total = sum((v for _, v in self.costs), Decimal(0))
        if total == 0:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "전체 제조원가가 0원입니다.")
            return
        painter.drawText(12, 22, "비용 구성 · 원재료는 수율 보정 후 금액")
        width = max(1, self.width() - 24)
        left = 12.0
        for index, (name, value) in enumerate(self.costs):
            segment = float(value / total) * width
            painter.fillRect(QRectF(left, 35, segment, 35), QColor(self.COLORS[index]))
            left += segment
        for index, (name, value) in enumerate(self.costs):
            x = 12 + (index % 2) * max(1, self.width() // 2)
            y = 94 + (index // 2) * 30
            painter.fillRect(QRectF(x, y - 10, 12, 12), QColor(self.COLORS[index]))
            painter.drawText(x + 20, y, f"{name}: {value:,.2f} 원/{self.unit_label} ({value / total * 100:,.2f}%)")
