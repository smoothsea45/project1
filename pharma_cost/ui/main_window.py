"""의약품 제조원가율 시뮬레이터의 한국어 오프라인 데스크톱 화면."""
from __future__ import annotations

import sys
from decimal import Decimal, localcontext
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..calculation import calculate
from ..examples import create_empty_project, create_example_project
from ..models import clone_scenario
from ..pricing import assess_pricing
from ..storage import ProjectFileError, load_project, save_project
from .chart import CostChart
from .material_table import MaterialTable
from .widgets import CostEditor, NumberEdit


def money(value, unit="정"):
    return "미완성" if value is None else f"{value:,.4f} 원/{unit}"


def percent(value):
    return "계산 불가" if value is None else f"{value:,.2f}%"


class MainWindow(QMainWindow):
    def __init__(self, project=None):
        super().__init__()
        self.project = project if project is not None else create_example_project()
        self.file_path: Path | None = None
        self.dirty = False
        self._loading = True
        self.number_fields: dict[str, NumberEdit] = {}
        self.product_fields = {}
        self.metadata_fields = {}
        self.result_labels = {}
        self.resize(1280, 900)
        self.setMinimumSize(900, 650)
        self._build_menu()
        self._build_ui()
        self._load_project()
        self._loading = False
        self.recalculate()
        self._update_title()

    @property
    def scenario(self):
        return self.project.active_scenario

    @property
    def unit_label(self):
        return "캡슐" if self.project.product.dosage_form == "capsule" else "정"

    def _build_menu(self):
        menu = self.menuBar().addMenu("파일(&F)")
        entries = [
            ("새 프로젝트", self.new_project, QKeySequence.StandardKey.New),
            ("열기…", self.open_project, QKeySequence.StandardKey.Open),
            ("저장", self.save_current_project, QKeySequence.StandardKey.Save),
            ("다른 이름으로 저장…", lambda: self.save_current_project(save_as=True), QKeySequence.StandardKey.SaveAs),
            ("가상 예제 열기", self.open_example, None),
            ("종료", self.close, QKeySequence.StandardKey.Quit),
        ]
        for text, callback, shortcut in entries:
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(lambda checked=False, fn=callback: fn())
            menu.addAction(action)
        help_menu = self.menuBar().addMenu("도움말")
        action = QAction("계산 기준 및 사용 안내", self)
        action.triggered.connect(self._show_help)
        help_menu.addAction(action)

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        heading = QLabel("의약품 제조원가율 시뮬레이터")
        heading.setStyleSheet("font-size: 22px; font-weight: 600; color: #24344b;")
        layout.addWidget(heading)
        self.example_banner = QLabel("가상 예제 · 실제 제품·견적·보험약가가 아닙니다. 프로젝트 전체를 JSON으로 저장할 수 있습니다.")
        self.example_banner.setWordWrap(True)
        self.example_banner.setStyleSheet("background: #fff1ce; padding: 8px; color: #634600;")
        layout.addWidget(self.example_banner)
        scenario_bar = QHBoxLayout()
        scenario_bar.addWidget(QLabel("현재 시나리오"))
        self.scenario_combo = QComboBox()
        self.scenario_combo.setMinimumWidth(240)
        self.scenario_combo.currentIndexChanged.connect(self._select_scenario)
        scenario_bar.addWidget(self.scenario_combo, 1)
        for text, callback in [("현재 입력 복제", self.duplicate_scenario), ("이름 변경", self.rename_scenario), ("시나리오 삭제", self.delete_scenario)]:
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, fn=callback: fn())
            scenario_bar.addWidget(button)
        layout.addLayout(scenario_bar)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._product_pricing_tab(), "제품·약가")
        self.material_table = MaterialTable()
        self.material_table.changed.connect(self._changed)
        self.tabs.addTab(self.material_table, "원료 입력")
        self.tabs.addTab(self._costs_tab(), "수율·고정 비용")
        self.tabs.addTab(self._results_tab(), "계산 결과")
        self.tabs.addTab(self._comparison_tab(), "시나리오 비교")
        layout.addWidget(self.tabs, 1)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("background: #eaf0f7; color: #20354c; padding: 10px; font-weight: 600;")
        layout.addWidget(self.summary)
        self.setCentralWidget(root)

    def _scroll(self, content):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(content)
        return area

    def _product_pricing_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        product_group = QGroupBox("공통 제품정보 · 모든 시나리오에 공유")
        form = QFormLayout(product_group)
        for key, label in [("project_name", "프로젝트명"), ("product_name", "제품명"), ("label_strength", "표시 함량 (설명용)")]:
            field = QLineEdit()
            field.textChanged.connect(lambda text, k=key: self._set_product(k, text))
            self.product_fields[key] = field
            form.addRow(label, field)
        self.dosage_form = QComboBox()
        self.dosage_form.addItem("정제", "tablet")
        self.dosage_form.addItem("캡슐", "capsule")
        self.dosage_form.currentIndexChanged.connect(self._dosage_changed)
        form.insertRow(2, "제형", self.dosage_form)
        memo = QPlainTextEdit()
        memo.setMaximumHeight(70)
        memo.textChanged.connect(lambda: self._set_product("memo", memo.toPlainText()))
        self.product_fields["memo"] = memo
        form.addRow("메모", memo)
        layout.addWidget(product_group)
        price_group = QGroupBox("약가 · 사용자 입력값")
        price_form = QFormLayout(price_group)
        self.price_labels = {}
        for key, label in [("insurance_price", "예상 보험약가"), ("post_addition_price", "가산 종료 후 예상 약가 (선택)"), ("target_rate", "목표 제조원가율 (%)")]:
            field = NumberEdit()
            field.value_changed.connect(lambda value, k=key: self._set_pricing(k, value))
            self.number_fields[f"pricing.{key}"] = field
            label_widget = QLabel(label)
            self.price_labels[key] = label_widget
            price_form.addRow(label_widget, field)
        self.price_source_label = QLabel("약가 출처: 사용자 입력값 · 자동 산정률을 적용하지 않습니다.")
        price_form.addRow(self.price_source_label)
        layout.addWidget(price_group)
        metadata_group = QGroupBox("향후 약가 산정용 기록 · 현재 계산에는 반영하지 않음")
        metadata_form = QFormLayout(metadata_group)
        metadata_notice = QLabel("제품 유형과 1+3 참여 형태는 독립된 항목입니다. 오리지널 현재 약가와 산정 기준금액도 별도로 기록합니다.")
        metadata_notice.setWordWrap(True)
        metadata_form.addRow(metadata_notice)
        texts = [
            ("product_type", "제품 유형 (제네릭·개량신약 등)"),
            ("development_method", "개발·자료 확보 방식"),
            ("participation_form", "1+3 참여 형태"),
            ("reference_product", "기준 제품"),
            ("addition_conditions", "가산 조건"),
            ("expected_application_date", "예상 신청 시점"),
            ("expected_listing_date", "예상 등재 시점"),
        ]
        for key, label in texts:
            field = QLineEdit()
            if key in ("expected_application_date", "expected_listing_date"):
                field.setPlaceholderText("예: 2027-03 또는 2027년 상반기")
            field.textChanged.connect(lambda text, k=key: self._set_metadata(k, text))
            self.metadata_fields[key] = field
            metadata_form.addRow(label, field)
        for key, label in [("original_current_price", "오리지널 현재 약가 (원/단위제형)"), ("reference_amount", "약가 산정 기준금액 (원/단위제형)"), ("listed_product_count", "기등재 동일제제 품목 수"), ("concurrent_application_count", "동시 신청 예상 품목 수")]:
            field = NumberEdit(integer=key.endswith("count"))
            field.value_changed.connect(lambda value, k=key: self._set_metadata(k, value))
            self.number_fields[f"pricing.metadata.{key}"] = field
            self.metadata_fields[key] = field
            metadata_form.addRow(label, field)
        for key, label in [("bioequivalence_requirement", "자체 생동 관련 요건 충족 여부"), ("registered_api_requirement", "등록 원료의약품 사용 여부")]:
            field = QComboBox()
            for text, data in [("미확인", "unknown"), ("예", "yes"), ("아니오", "no")]:
                field.addItem(text, data)
            field.currentIndexChanged.connect(lambda index, k=key, widget=field: self._set_metadata(k, widget.currentData()))
            self.metadata_fields[key] = field
            metadata_form.addRow(label, field)
        layout.addWidget(metadata_group)
        layout.addStretch()
        return self._scroll(page)

    def _costs_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("제조수율 · 원재료비에만 적용")
        form = QFormLayout(group)
        self.yield_edit = NumberEdit(positive=True, maximum=100)
        self.yield_edit.value_changed.connect(lambda value: self._set_scenario("yield_percent", value))
        self.number_fields["yield_percent"] = self.yield_edit
        self.apply_yield = QCheckBox("원재료비 전체에 수율 보정 적용")
        self.apply_yield.toggled.connect(lambda value: self._set_scenario("apply_yield", value))
        form.addRow("제조수율 (%)", self.yield_edit)
        form.addRow(self.apply_yield)
        label = QLabel("보정 후 원재료비 = 이론 원재료비 ÷ (수율 ÷ 100). 이미 손실을 반영한 경우 보정을 끄세요. 포장재비·공수비는 보정하지 않습니다.")
        label.setWordWrap(True)
        form.addRow(label)
        layout.addWidget(group)
        self.packaging_editor = CostEditor("packaging")
        self.labor_editor = CostEditor("labor")
        for editor, label in [(self.packaging_editor, "포장재비"), (self.labor_editor, "공수비")]:
            group = QGroupBox(label)
            gl = QVBoxLayout(group)
            gl.addWidget(editor)
            editor.changed.connect(self._changed)
            layout.addWidget(group)
        layout.addStretch()
        return self._scroll(page)

    def _results_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("단위제형당 계산 결과 · 내부 계산값은 중간 반올림하지 않음")
        form = QFormLayout(group)
        for key, text in [
            ("api_cost", "API 비용 합계 (이론)"), ("excipient_cost", "부형제 비용 합계 (이론)"),
            ("theoretical_material_cost", "이론 원재료비"), ("adjusted_material_cost", "수율 보정 후 원재료비"),
            ("packaging_cost", "포장재비"), ("labor_cost", "공수비"), ("total_cost", "단위제형당 제조원가"),
            ("cost_rate", "보험약가 대비 제조원가율"), ("post_addition_cost_rate", "가산 종료 후 약가 대비 원가율"),
            ("allowed_cost", "목표 원가율 기준 허용 제조원가"), ("target_gap", "목표 원가율과의 차이 (%p)"),
            ("required_saving", "목표 달성을 위한 필요 절감액"),
        ]:
            label = QLabel()
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if key in ("total_cost", "cost_rate", "required_saving"):
                label.setStyleSheet("font-weight: 600; color: #1d4c82;")
            self.result_labels[key] = label
            form.addRow(text, label)
        self.target_status = QLabel()
        form.addRow("목표 달성 여부", self.target_status)
        layout.addWidget(group)
        self.issue_list = QLabel()
        self.issue_list.setWordWrap(True)
        self.issue_list.setTextFormat(Qt.TextFormat.PlainText)
        self.issue_list.setStyleSheet("color: #a2343d; padding: 5px;")
        layout.addWidget(self.issue_list)
        self.composition = QTableWidget(4, 3)
        self.composition.setHorizontalHeaderLabels(["비용 항목", "원/단위제형", "비중 (%)"])
        self.composition.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.composition.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.composition.setMaximumHeight(160)
        layout.addWidget(self.composition)
        self.chart = CostChart()
        layout.addWidget(self.chart)
        return self._scroll(page)

    def _comparison_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        notice = QLabel("현재 입력 복제로 비교안을 만드세요. 각 시나리오의 원료·약가·환율·수율·비용은 독립적으로 보관됩니다. 금액 단위는 제품 제형에 따릅니다.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.comparison = QTableWidget()
        self.comparison.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.comparison.setWordWrap(False)
        layout.addWidget(self.comparison)
        return page

    def _load_project(self):
        self._loading = True
        product = self.project.product
        for key, field in self.product_fields.items():
            value = getattr(product, key)
            field.setPlainText(value) if isinstance(field, QPlainTextEdit) else field.setText(value)
        self.dosage_form.setCurrentIndex(self.dosage_form.findData(product.dosage_form))
        self.example_banner.setVisible(self.project.is_example)
        self._refresh_scenario_combo()
        self._load_scenario()
        self._loading = False

    def _refresh_scenario_combo(self):
        blocker = QSignalBlocker(self.scenario_combo)
        self.scenario_combo.clear()
        for scenario in self.project.scenarios:
            self.scenario_combo.addItem(scenario.name, scenario.id)
        self.scenario_combo.setCurrentIndex(self.scenario_combo.findData(self.project.active_scenario_id))
        del blocker

    def _load_scenario(self):
        previous = self._loading
        self._loading = True
        scenario = self.scenario
        for key in ["insurance_price", "post_addition_price", "target_rate"]:
            self.number_fields[f"pricing.{key}"].set_value(getattr(scenario.pricing, key))
        for key, field in self.metadata_fields.items():
            value = getattr(scenario.pricing.metadata, key)
            if isinstance(field, NumberEdit):
                field.set_value(value)
            elif isinstance(field, QComboBox):
                field.setCurrentIndex(field.findData(value))
            else:
                field.setText(value)
        self.yield_edit.set_value(scenario.yield_percent)
        self.apply_yield.setChecked(scenario.apply_yield)
        self.material_table.set_materials(scenario.materials)
        self.packaging_editor.load(scenario.packaging, self.unit_label)
        self.labor_editor.load(scenario.labor, self.unit_label)
        self._loading = previous

    def _set_product(self, key, value):
        if self._loading:
            return
        setattr(self.project.product, key, value)
        self._changed()

    def _set_pricing(self, key, value):
        if self._loading:
            return
        setattr(self.scenario.pricing, key, value)
        self._changed()

    def _set_metadata(self, key, value):
        if self._loading:
            return
        setattr(self.scenario.pricing.metadata, key, value)
        self._changed()

    def _set_scenario(self, key, value):
        if self._loading:
            return
        setattr(self.scenario, key, value)
        self._changed()

    def _dosage_changed(self):
        if self._loading:
            return
        self.project.product.dosage_form = self.dosage_form.currentData()
        for editor in [self.packaging_editor, self.labor_editor]:
            editor.unit_label = self.unit_label
            editor._update_labels()
        self._changed()

    def _changed(self):
        if self._loading:
            return
        self.dirty = True
        self.recalculate()
        self._update_title()

    def _update_title(self):
        title = self.project.product.project_name or "새 프로젝트"
        path = f" · {self.file_path.name}" if self.file_path else ""
        self.setWindowTitle(f"{'* ' if self.dirty else ''}{title}{path} — 의약품 제조원가율 시뮬레이터")

    def recalculate(self):
        self.current_result = calculate(self.scenario)
        result = self.current_result
        unit = self.unit_label
        self.material_table.set_unit_label(unit)
        self.material_table.apply_results(result.material_results, result.issues, unit)
        for path, field in self.number_fields.items():
            issue = next((i.message for i in result.issues if i.path == path), "")
            field.mark_issue(issue)
        self.packaging_editor.apply_result(result.packaging_cost, result.issues, "packaging")
        self.labor_editor.apply_result(result.labor_cost, result.issues, "labor")
        for key, label in self.result_labels.items():
            value = getattr(result, key)
            if key in ("cost_rate", "post_addition_cost_rate"):
                text = percent(value)
                if key == "post_addition_cost_rate" and self.scenario.pricing.post_addition_price is None:
                    text = "미입력 (선택 항목)"
            elif key == "target_gap":
                text = "계산 불가" if value is None else f"{value:+,.2f} %p (현재 원가율 − 목표)"
            else:
                text = money(value, unit)
            label.setText(text)
        achieved = result.target_gap is not None and result.target_gap <= 0
        self.target_status.setText("판정 불가" if result.target_gap is None else "목표 달성" if achieved else "목표 초과")
        self.target_status.setStyleSheet(f"font-weight: 600; color: {'#24744b' if achieved else '#a2343d'};")
        messages = []
        for issue in result.issues:
            prefix = "안내" if issue.severity == "warning" else "미완성/오류"
            row_prefix = ""
            if issue.path.startswith("materials."):
                mid = issue.path.split(".")[1]
                row_prefix = next((f"원료 {idx + 1} ({m.name or '이름 미입력'}): " for idx, m in enumerate(self.scenario.materials) if m.id == mid), "")
            messages.append(f"• {prefix}: {row_prefix}{issue.message}")
        self.issue_list.setText("\n".join(messages) if messages else "모든 계산 입력이 유효합니다.")
        self.issue_list.setStyleSheet(f"color: {'#a2343d' if messages else '#24744b'}; padding: 5px;")
        self.summary.setText(f"제조원가 {money(result.total_cost, unit)}   |   보험약가 대비 원가율 {percent(result.cost_rate)}   |   {self.target_status.text()}   |   필요 절감액 {money(result.required_saving, unit)}")
        assessment = assess_pricing(self.scenario.pricing)
        self.price_source_label.setText(f"약가 출처: {assessment.source} · 자동 산정률을 적용하지 않습니다.")
        self.price_labels["insurance_price"].setText(f"예상 보험약가 (원/{unit})")
        self.price_labels["post_addition_price"].setText(f"가산 종료 후 예상 약가 (원/{unit}, 선택)")
        with localcontext() as ctx:
            ctx.prec = 50
            factor = None
            if result.adjusted_material_cost is not None:
                factor = Decimal(100) / self.scenario.yield_percent if self.scenario.apply_yield else Decimal(1)
            api = result.api_cost * factor if result.api_cost is not None and factor is not None else None
            excipient = result.excipient_cost * factor if result.excipient_cost is not None and factor is not None else None
            costs = [("API (수율 보정 후)", api), ("부형제 (수율 보정 후)", excipient), ("포장재비", result.packaging_cost), ("공수비", result.labor_cost)]
            self.chart.set_costs(costs, unit)
            self.composition.setHorizontalHeaderLabels(["비용 항목", f"원/{unit}", "비중 (%)"])
            for row, (name, value) in enumerate(costs):
                share = value / result.total_cost * 100 if value is not None and result.total_cost is not None and result.total_cost > 0 else None
                for col, text in enumerate([name, "미완성" if value is None else f"{value:,.4f}", "—" if share is None else f"{share:,.2f}"]):
                    self.composition.setItem(row, col, QTableWidgetItem(text))
        self._update_comparison()

    def _update_comparison(self):
        row_labels = ["처방 · 실제 투입량", "API 제조원·적용 단가", "외화 단가·환율", "제조수율 · 보정", "예상 보험약가 (사용자 입력값)", "가산 종료 후 약가", "목표 제조원가율", "API 비용 (이론)", "부형제 비용 (이론)", "수율 보정 후 원재료비", "포장재비", "공수비", "제조원가", "보험약가 대비 제조원가율", "가산 종료 후 원가율", "목표와의 차이 (%p)", "필요 절감액", "판정"]
        self.comparison.setRowCount(len(row_labels))
        self.comparison.setColumnCount(len(self.project.scenarios))
        self.comparison.setVerticalHeaderLabels(row_labels)
        self.comparison.setHorizontalHeaderLabels([s.name for s in self.project.scenarios])
        self.comparison.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col, scenario in enumerate(self.project.scenarios):
            result = calculate(scenario)
            row_by_id = {r.material_id: r for r in result.material_results}
            formula = "; ".join(f"{m.name or '미명명'} {m.amount if m.amount is not None else '미입력'} {'mg' if m.basis == 'mass' else '개'}" for m in scenario.materials) or "원료 없음 (0원)"
            suppliers = "; ".join(f"{m.name or 'API'} / {m.supplier or '공급처 미입력'} / {row_by_id[m.id].unit_price if row_by_id[m.id].unit_price is not None else '미완성'} 원/{'kg' if m.basis == 'mass' else '개'}" for m in scenario.materials if m.kind == "api") or "API 없음"
            fx = "; ".join(f"{m.name or '원료'}: {m.foreign_price} {m.currency} × {m.exchange_rate} 원/{m.currency}" for m in scenario.materials if m.price_source == "fx") or "원화 직접 입력"
            values = [formula, suppliers, fx, f"{scenario.yield_percent if scenario.yield_percent is not None else '미입력'}% / {'적용' if scenario.apply_yield else '미적용'}", money(scenario.pricing.insurance_price, self.unit_label), "미입력" if scenario.pricing.post_addition_price is None else money(scenario.pricing.post_addition_price, self.unit_label), percent(scenario.pricing.target_rate), money(result.api_cost, self.unit_label), money(result.excipient_cost, self.unit_label), money(result.adjusted_material_cost, self.unit_label), money(result.packaging_cost, self.unit_label), money(result.labor_cost, self.unit_label), money(result.total_cost, self.unit_label), percent(result.cost_rate), percent(result.post_addition_cost_rate), "계산 불가" if result.target_gap is None else f"{result.target_gap:+,.2f} %p", money(result.required_saving, self.unit_label), "판정 불가" if result.target_gap is None else "목표 달성" if result.target_gap <= 0 else "목표 초과"]
            for row, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.comparison.setItem(row, col, item)
            self.comparison.setColumnWidth(col, 310)

    def _has_raw_errors(self):
        fields = list(self.number_fields.values()) + [self.packaging_editor.amount, self.labor_editor.amount]
        for editor in [self.packaging_editor, self.labor_editor]:
            fields.append(editor.quantity)
        return any(field.raw_error for field in fields) or self.material_table.has_raw_errors()

    def _guard_raw_errors(self):
        self.material_table.commit_pending_edit()
        if self._has_raw_errors():
            QMessageBox.warning(self, "숫자 입력 확인", "빨간색으로 표시된 숫자 형식·범위 오류를 수정하세요. 미입력 빈칸은 미완성 프로젝트로 저장할 수 있습니다.")
            return False
        return True

    def _select_scenario(self, index):
        if self._loading or index < 0:
            return
        selected = self.scenario_combo.itemData(index)
        if selected == self.project.active_scenario_id:
            return
        if not self._guard_raw_errors():
            self._refresh_scenario_combo()
            return
        self.project.active_scenario_id = selected
        self._load_scenario()
        self._changed()

    def duplicate_scenario(self, name=None):
        if not self._guard_raw_errors():
            return None
        if name is None:
            name, accepted = QInputDialog.getText(self, "시나리오 복제", "새 시나리오 이름", text=f"{self.scenario.name} 복사")
            if not accepted:
                return None
        if not name.strip():
            QMessageBox.warning(self, "이름 확인", "시나리오 이름을 입력하세요.")
            return None
        scenario = clone_scenario(self.project, self.scenario.id, name.strip())
        self._refresh_scenario_combo()
        self._load_scenario()
        self._changed()
        return scenario

    def rename_scenario(self, name=None):
        if name is None:
            name, accepted = QInputDialog.getText(self, "시나리오 이름 변경", "시나리오 이름", text=self.scenario.name)
            if not accepted:
                return
        if name.strip():
            self.scenario.name = name.strip()
            self._refresh_scenario_combo()
            self._changed()

    def delete_scenario(self):
        if len(self.project.scenarios) <= 1:
            QMessageBox.information(self, "시나리오 삭제", "프로젝트에는 시나리오가 최소 하나 필요합니다.")
            return
        reply = QMessageBox.question(self, "시나리오 삭제", f"'{self.scenario.name}' 시나리오를 삭제할까요?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.project.scenarios = [s for s in self.project.scenarios if s.id != self.project.active_scenario_id]
        self.project.active_scenario_id = self.project.scenarios[0].id
        self._refresh_scenario_combo()
        self._load_scenario()
        self._changed()

    def _confirm_discard(self):
        self.material_table.commit_pending_edit()
        if not self.dirty:
            return True
        reply = QMessageBox.question(self, "저장하지 않은 변경사항", "변경사항을 저장할까요?", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if reply == QMessageBox.StandardButton.Save:
            return self.save_current_project()
        return reply == QMessageBox.StandardButton.Discard

    def new_project(self):
        if not self._confirm_discard():
            return False
        self._replace_project(create_empty_project(), None)
        return True

    def open_example(self):
        if not self._confirm_discard():
            return False
        self._replace_project(create_example_project(), None)
        return True

    def _replace_project(self, project, path):
        self.project = project
        self.file_path = path
        self.dirty = False
        self._load_project()
        self.recalculate()
        self._update_title()

    def open_project(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "프로젝트 열기", "", "제조원가 프로젝트 (*.json)")
            if not path:
                return False
        if not self._confirm_discard():
            return False
        try:
            project = load_project(path)
        except ProjectFileError as exc:
            QMessageBox.warning(self, "파일을 열 수 없습니다", str(exc))
            return False
        self._replace_project(project, Path(path))
        self.statusBar().showMessage(f"프로젝트를 열었습니다: {Path(path).name}", 5000)
        return True

    def save_current_project(self, path=None, *, save_as=False):
        if not self._guard_raw_errors():
            return False
        target = Path(path) if path else self.file_path
        if target is None or save_as:
            initial = str(target) if target else "제조원가 프로젝트.json"
            chosen, _ = QFileDialog.getSaveFileName(self, "프로젝트 저장", initial, "제조원가 프로젝트 (*.json)")
            if not chosen:
                return False
            target = Path(chosen)
            if target.suffix.lower() != ".json":
                target = Path(str(target) + ".json")
                if target.exists():
                    reply = QMessageBox.question(self, "파일 덮어쓰기", f"'{target.name}' 파일이 이미 있습니다. 덮어쓸까요?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                    if reply != QMessageBox.StandardButton.Yes:
                        return False
        try:
            save_project(self.project, target)
        except ProjectFileError as exc:
            QMessageBox.warning(self, "저장할 수 없습니다", str(exc))
            return False
        self.file_path = target
        self.dirty = False
        self._update_title()
        self.statusBar().showMessage(f"프로젝트를 저장했습니다: {target.name}", 5000)
        return True

    def closeEvent(self, event):
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()

    def _show_help(self):
        QMessageBox.information(self, "계산 기준 및 사용 안내", "1. 제품·약가 탭에서 사용자 입력 약가를 설정합니다.\n2. 원료 입력 표에 실제 투입량과 단가를 입력합니다. 여러 API를 추가할 수 있습니다.\n3. 수율과 전달받은 포장재비·공수비를 입력합니다.\n4. 시나리오를 복제해 비교하고 JSON으로 저장합니다.\n\n질량 원료 비용 = mg × 원/kg ÷ 1,000,000\n개당 원료 비용 = 사용 개수 × 원/개\n외화 환산 = 외화 단가 × 사용자 입력 환율\n보정 원재료비 = 이론 원재료비 ÷ (수율 ÷ 100)\n제조원가율 = 제조원가 ÷ 예상 보험약가 × 100\n\nAPI 표시 함량과 실제 투입량은 별개입니다. 염·수화물·역가 보정 및 약가 자동 산정은 수행하지 않습니다. 금액은 화면에서만 반올림합니다. 원료 표는 탭 이동과 여러 셀 TSV 붙여넣기를 지원합니다.")


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("의약품 제조원가율 시뮬레이터")
    app.setOrganizationName("PharmaCostSimulator")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()
