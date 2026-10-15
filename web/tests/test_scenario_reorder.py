"""Native scenario-tab dragging preserves each scenario and comparison state."""

import copy
import json

import pytest
from playwright.sync_api import expect

from web.tests.test_browser import (
    comparison,
    new_project,
    open_file,
    project,
    save_file,
    scenario,
    select_scenario,
)
from web.tests.test_presentation import comparison_row
from web.tests.test_pricing import comparison_cell, comparison_year, condition, setup_automatic
from web.tests.test_tabs_print import clone, four_scenarios


def scenario_tab(page, scenario_id):
    return page.locator(f'#scenario-tabs [data-scenario-id="{scenario_id}"]')


def tab_order(page):
    return page.locator('#scenario-tabs [role="tab"]').evaluate_all(
        "tabs => tabs.map(tab => tab.dataset.scenarioId)"
    )


def expect_order(page, ids):
    assert [item["id"] for item in project(page)["scenarios"]] == ids
    assert tab_order(page) == ids
    expect(page.locator("#scenario-tabs .scenario-number")).to_have_text(
        [f"{index:02d}" for index in range(1, len(ids) + 1)]
    )
    for index, scenario_id in enumerate(ids, start=1):
        expect(scenario_tab(page, scenario_id)).to_have_attribute(
            "aria-label", f'{index}번 시나리오: ' + scenario_tab(page, scenario_id).locator(".scenario-name").inner_text()
        )


def native_drag(page, source_id, target_id, after=False):
    """Use actual mouse drag events rather than dispatching synthetic drops."""
    page.evaluate("""() => {
      window.__nativeScenarioDrags = [];
      document.getElementById('scenario-tabs').addEventListener('dragstart', event => {
        const tab = event.target.closest('[data-scenario-id]');
        if (tab) window.__nativeScenarioDrags.push(tab.dataset.scenarioId);
      }, {once: true});
    }""")
    source = scenario_tab(page, source_id)
    target = scenario_tab(page, target_id)
    box = target.bounding_box()
    assert box
    source.drag_to(
        target,
        target_position={"x": box["width"] * (0.75 if after else 0.25), "y": box["height"] / 2},
    )
    assert page.evaluate("window.__nativeScenarioDrags") == [source_id]


@pytest.mark.parametrize("width", [390, 1440])
def test_dragging_four_tabs_updates_comparison_order_without_mutating_scenario_data(page, width):
    page.set_viewport_size({"width": width, "height": 1000})
    ids = four_scenarios(page)
    original = project(page)
    original_by_id = {item["id"]: item for item in original["scenarios"]}
    selected = page.locator('#material-body tr input[type="checkbox"]').first
    selected.check()

    # Move the inactive first scenario to the end, then bring it back to the front.
    native_drag(page, ids[0], ids[3], after=True)
    expect_order(page, ids[1:] + ids[:1])
    assert project(page)["active_scenario_id"] == ids[3]
    expect(selected).to_be_checked()
    native_drag(page, ids[0], ids[1])
    expect_order(page, ids)

    # An adjacent move must not disappear because the source index was removed first.
    native_drag(page, ids[1], ids[2], after=True)
    expected = [ids[0], ids[2], ids[1], ids[3]]
    expect_order(page, expected)
    actual = project(page)
    assert {item["id"]: item for item in actual["scenarios"]} == original_by_id
    assert actual["active_scenario_id"] == original["active_scenario_id"]
    expect(page.locator("#manual-price")).to_have_value("400")
    expect(selected).to_be_checked()
    expect(page.locator("#delete-materials")).to_be_enabled()

    comparison(page)
    assert page.locator("#comparison-head th[data-scenario-id]").evaluate_all(
        "cells => cells.map(cell => cell.dataset.scenarioId)"
    ) == expected
    expect(comparison_row(page, "price").locator("td")).to_have_text(["100", "300", "200", "400"])
    assert comparison_row(page, "api_cost").locator('td[data-cost-basis="unit"]').evaluate_all(
        "cells => cells.map(cell => cell.dataset.scenarioId)"
    ) == expected


@pytest.mark.parametrize("source_index,target_index,after", [(0, 1, True), (1, 0, False)])
def test_two_scenario_tabs_can_swap_in_both_directions(page, source_index, target_index, after):
    before = project(page)
    ids = [item["id"] for item in before["scenarios"]]
    native_drag(page, ids[source_index], ids[target_index], after=after)
    expect_order(page, list(reversed(ids)))
    assert project(page)["active_scenario_id"] == before["active_scenario_id"]
    expect(scenario_tab(page, before["active_scenario_id"])).to_have_attribute("aria-selected", "true")
    assert sorted(project(page)["scenarios"], key=lambda item: item["id"]) == sorted(before["scenarios"], key=lambda item: item["id"])


@pytest.mark.parametrize("drop_area", ["empty_end", "wrapped_gap"])
def test_dropping_on_tab_list_blank_space_resolves_to_the_nearest_insertion(page, drop_area):
    if drop_area == "empty_end":
        page.set_viewport_size({"width": 1920, "height": 1000})
        ids = [item["id"] for item in project(page)["scenarios"]]
        source_id = ids[0]
        nav = page.locator("#scenario-tabs").bounding_box()
        last = scenario_tab(page, ids[-1]).bounding_box()
        assert nav["x"] + nav["width"] > last["x"] + last["width"] + 10
        drop_x = nav["width"] - 3
        drop_y = nav["height"] / 2
        expected = list(reversed(ids))
    else:
        page.set_viewport_size({"width": 390, "height": 1000})
        ids = four_scenarios(page)
        source_id = ids[3]
        nav = page.locator("#scenario-tabs").bounding_box()
        first = scenario_tab(page, ids[0]).bounding_box()
        second = scenario_tab(page, ids[1]).bounding_box()
        assert first["x"] + first["width"] < second["x"]
        drop_x = (first["x"] + first["width"] + second["x"]) / 2 - nav["x"]
        drop_y = first["y"] + first["height"] / 2 - nav["y"]
        expected = [ids[0], ids[3], ids[1], ids[2]]
    before = project(page)
    scenario_tab(page, source_id).drag_to(
        page.locator("#scenario-tabs"), target_position={"x": drop_x, "y": drop_y}
    )
    expect_order(page, expected)
    assert project(page)["active_scenario_id"] == before["active_scenario_id"]
    assert {item["id"]: item for item in project(page)["scenarios"]} == {item["id"]: item for item in before["scenarios"]}


def test_reordering_comparison_keeps_year_previews_attached_to_scenario_ids(page):
    setup_automatic(page, company="innovative", count="ge14")
    condition(page, "company_eligible").check()
    condition(page, "domestic_extension").check()
    first_id = scenario(page)["id"]
    second_id = clone(page, "두 번째 연차 비교안")
    page.locator("#original-price").fill("2000")
    page.locator("#batch-labor").fill("3000000")
    before = project(page)
    comparison(page)
    comparison_year(page, first_id, 5).click()
    comparison_year(page, second_id, 6).click()
    native_drag(page, second_id, first_id)
    expect_order(page, [second_id, first_id])

    for scenario_id, year, price, cost_rate in [(first_id, 5, "383", "13.1%"), (second_id, 6, "765", "7.8%")]:
        expect(comparison_cell(page, "price", scenario_id)).to_have_text(price)
        expect(comparison_cell(page, "cost_rate", scenario_id)).to_have_text(cost_rate)
        expect(comparison_cell(page, "composition", scenario_id).locator(".comparison-donut-year")).to_have_text(f"{year}년차")
        expect(comparison_year(page, scenario_id, year)).to_have_attribute("aria-pressed", "true")
    assert page.locator("#comparison-head th[data-scenario-id]").evaluate_all(
        "cells => cells.map(cell => cell.dataset.scenarioId)"
    ) == [second_id, first_id]
    assert project(page) == {**before, "scenarios": list(reversed(before["scenarios"]))}
    expect(page.locator("#tab-comparison")).to_be_visible()


@pytest.mark.parametrize("cancellation", ["outside", "self", "escape"])
def test_canceled_or_self_drag_keeps_order_and_saved_state(page, tmp_path, cancellation):
    before = save_file(page, tmp_path / "unchanged-before-drag.json")
    ids = [item["id"] for item in before["scenarios"]]
    source = scenario_tab(page, ids[0])
    if cancellation == "outside":
        source.drag_to(page.locator(".app-header h1"))
    elif cancellation == "self":
        native_drag(page, ids[0], ids[0], after=True)
    else:
        source_box = source.bounding_box()
        target_box = scenario_tab(page, ids[1]).bounding_box()
        start_x = source_box["x"] + source_box["width"] * 0.25
        start_y = source_box["y"] + source_box["height"] / 2
        page.mouse.move(start_x, start_y)
        page.mouse.down()
        page.mouse.move(start_x + 12, start_y, steps=4)
        page.mouse.move(target_box["x"] + target_box["width"] * 0.75, target_box["y"] + target_box["height"] / 2, steps=8)
        page.keyboard.press("Escape")
        page.mouse.up()
    expect_order(page, ids)
    assert project(page) == before
    expect(page.locator("#project-status")).to_have_text("프로젝트 파일")
    assert json.loads(page.evaluate("localStorage.getItem('pharma-cost-web-draft-v1')")) == before
    # Canceling one drag must leave subsequent native drags usable.
    native_drag(page, ids[1], ids[0])
    expect_order(page, list(reversed(ids)))


def test_keyboard_reordering_has_no_wrap_and_plain_arrows_still_select(page):
    ids = four_scenarios(page)
    before = project(page)
    active_id = ids[3]
    tab = scenario_tab(page, active_id)
    tab.focus()
    page.keyboard.press("Alt+Shift+ArrowLeft")
    expect_order(page, [ids[0], ids[1], ids[3], ids[2]])
    expect(scenario_tab(page, active_id)).to_be_focused()
    assert project(page)["active_scenario_id"] == active_id
    page.keyboard.press("Alt+Shift+ArrowLeft")
    page.keyboard.press("Alt+Shift+ArrowLeft")
    expect_order(page, [ids[3], ids[0], ids[1], ids[2]])
    edge = copy.deepcopy(project(page))
    page.keyboard.press("Alt+Shift+ArrowLeft")
    assert project(page) == edge
    page.keyboard.press("Alt+Shift+ArrowRight")
    expect_order(page, [ids[0], ids[3], ids[1], ids[2]])
    assert {item["id"]: item for item in project(page)["scenarios"]} == {item["id"]: item for item in before["scenarios"]}
    page.keyboard.press("ArrowRight")
    assert project(page)["active_scenario_id"] == ids[1]
    expect(scenario_tab(page, ids[1])).to_be_focused()
    expect_order(page, [ids[0], ids[3], ids[1], ids[2]])


def test_drag_order_survives_draft_reload_and_json_roundtrip(page, tmp_path):
    ids = four_scenarios(page)
    save_file(page, tmp_path / "before-order.json")
    native_drag(page, ids[3], ids[0])
    expected = project(page)
    expect(page.locator("#project-status")).to_have_text("파일 저장 필요")
    assert json.loads(page.evaluate("localStorage.getItem('pharma-cost-web-draft-v1')")) == expected
    page.reload()
    page.wait_for_function("Boolean(window.PharmaCostApp)")
    assert project(page) == expected
    expect_order(page, [ids[3], *ids[:3]])
    path = tmp_path / "reordered-scenarios.json"
    assert save_file(page, path) == expected
    new_project(page)
    open_file(page, path)
    assert project(page) == expected
    expect_order(page, [ids[3], *ids[:3]])
    comparison(page)
    assert page.locator("#comparison-head th[data-scenario-id]").evaluate_all(
        "cells => cells.map(cell => cell.dataset.scenarioId)"
    ) == [ids[3], *ids[:3]]


def test_delete_and_clone_use_reordered_scenarios_without_changing_originals(page):
    ids = four_scenarios(page)
    original_by_id = {item["id"]: item for item in project(page)["scenarios"]}
    native_drag(page, ids[2], ids[0])
    expect_order(page, [ids[2], ids[0], ids[1], ids[3]])
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#delete-scenario").click()
    expect_order(page, [ids[2], ids[0], ids[1]])
    assert project(page)["active_scenario_id"] == ids[2]
    new_id = clone(page, "순서 변경 후 복제안")
    expect_order(page, [ids[2], ids[0], ids[1], new_id])
    assert {item["id"]: item for item in project(page)["scenarios"] if item["id"] != new_id} == {
        key: value for key, value in original_by_id.items() if key != ids[3]
    }
    duplicate = scenario(page)
    original = original_by_id[ids[2]]
    assert duplicate["id"] != original["id"]
    assert duplicate["manual_price"] == original["manual_price"]
    assert duplicate["packaging_form"] == original["packaging_form"]
    page.locator("#manual-price").fill("999")
    select_scenario(page, ids[2])
    expect(page.locator("#manual-price")).to_have_value("300")


def test_single_scenario_does_not_offer_dragging_or_keyboard_reorder(page):
    new_project(page)
    before = project(page)
    only_id = before["scenarios"][0]["id"]
    only_tab = scenario_tab(page, only_id)
    assert not only_tab.evaluate("node => node.draggable")
    only_tab.focus()
    page.keyboard.press("Alt+Shift+ArrowLeft")
    page.keyboard.press("Alt+Shift+ArrowRight")
    assert project(page) == before
    expect_order(page, [only_id])
