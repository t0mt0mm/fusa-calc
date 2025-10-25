from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import pytest
import sys
from types import ModuleType

from .qt_stubs import install_numpy_stub, install_qt_stubs, install_yaml_stub

install_qt_stubs()
install_yaml_stub()
install_numpy_stub()

if 'SilCalc_0004' not in sys.modules:
    silcalc_stub = ModuleType('SilCalc_0004')

    class _Placeholder:  # pragma: no cover - stub container
        pass

    silcalc_stub.CeMatrix = _Placeholder
    silcalc_stub.EeOverview = _Placeholder
    silcalc_stub.FuSa = _Placeholder
    sys.modules['SilCalc_0004'] = silcalc_stub

from PyQt5.QtCore import Qt

from sifu_core.models import Assumptions, ChannelMetrics
from sifu_gui import MainWindow


@dataclass
class FakeItem:
    text_value: str
    payload: Dict[str, Any]
    tooltip: Optional[str] = None

    def data(self, role: int) -> Any:
        if role == Qt.UserRole:
            return self.payload
        return None

    def setData(self, role: int, value: Any) -> None:
        if role == Qt.UserRole:
            self.payload = value

    def text(self) -> str:
        return self.text_value

    def setToolTip(self, value: str) -> None:
        self.tooltip = value


@dataclass
class FakeList:
    lane: str
    items: List[FakeItem]

    def count(self) -> int:
        return len(self.items)

    def item(self, index: int) -> Optional[FakeItem]:
        try:
            return self.items[index]
        except IndexError:
            return None


class SumHarness:
    _sanitize_link_color = staticmethod(MainWindow._sanitize_link_color)
    _normalize_link_group_id = staticmethod(MainWindow._normalize_link_group_id)
    _group_id_for_color = staticmethod(MainWindow._group_id_for_color)

    def __init__(self, component_metrics: Dict[str, ChannelMetrics], group_metrics: Dict[tuple[str, ...], ChannelMetrics]):
        self._component_metrics_map = component_metrics
        self._group_metrics_map = group_metrics
        self._errors: List[Any] = []

    def _current_assumptions(self) -> Assumptions:
        return Assumptions(TI=8760.0, MTTR=8.0, beta=0.1, beta_D=0.02)

    def _ratios(self, lane: str) -> tuple[float, float]:
        return (0.6, 0.4)

    def _row_lane_for_list(self, list_widget: FakeList) -> tuple[int, Optional[str]]:
        return (0, list_widget.lane)

    def _row_uid_for_index(self, index: int) -> str:
        return "row-uid"

    def _group_metrics(
        self,
        members: Iterable[Dict[str, Any]],
        du_ratio: float,
        dd_ratio: float,
        mode_key: str,
        assumptions: Assumptions,
    ):
        key = tuple(sorted(m.get("id") for m in members if isinstance(m, dict)))
        metrics = self._group_metrics_map[key]
        return metrics, "group tooltip", None, []

    def _handle_conversion_error(self, error: Exception) -> None:
        self._errors.append(error)

    def _component_metrics(
        self,
        payload: Dict[str, Any],
        du_ratio: float,
        dd_ratio: float,
        mode_key: str,
        assumptions: Assumptions,
    ):
        metrics = self._component_metrics_map[payload["id"]]
        return metrics, None, "tooltip", None


@pytest.fixture
def summation_harness() -> SumHarness:
    component_metrics = {
        "sensor-1": ChannelMetrics(0.0, 0.0, 0.0, 0.010, 1.0e-6),
        "logic-1": ChannelMetrics(0.0, 0.0, 0.0, 0.020, 2.0e-6),
        "sensor-u": ChannelMetrics(0.0, 0.0, 0.0, 0.003, 3.0e-7),
        "actuator-u": ChannelMetrics(0.0, 0.0, 0.0, 0.004, 4.0e-7),
    }
    group_metrics = {
        ("act-1", "act-2"): ChannelMetrics(0.0, 0.0, 0.0, 0.005, 5.0e-7)
    }
    return SumHarness(component_metrics, group_metrics)


def build_lane(lane: str, items: List[FakeItem]) -> FakeList:
    return FakeList(lane=lane, items=items)


def make_linked_payload(component_id: str, lane: str) -> Dict[str, Any]:
    return {
        "id": component_id,
        "code": component_id.upper(),
        "kind": lane,
        "link_color": "#FDE68A",
        "link_group_id": "row-uid:fde68a",
    }


def test_sum_lists_groups_by_colour_across_lanes(summation_harness: SumHarness) -> None:
    sensor_items = [
        FakeItem("Sensor A", make_linked_payload("sensor-1", "sensor")),
        FakeItem("Sensor B", {
            "id": "sensor-u",
            "code": "S-U",
            "kind": "sensor",
        }),
    ]
    logic_items = [
        FakeItem("Logic A", make_linked_payload("logic-1", "logic")),
    ]
    actuator_items = [
        FakeItem(
            "Redundant Output",
            {
                "group": True,
                "architecture": "1oo2",
                "members": [{"id": "act-1", "code": "A1"}, {"id": "act-2", "code": "A2"}],
                "kind": "actuator",
                "link_color": "#fde68a",
                "link_group_id": "row-uid:fde68a",
            },
        ),
        FakeItem(
            "Standalone Output",
            {
                "id": "actuator-u",
                "code": "A-U",
                "kind": "actuator",
            },
        ),
    ]

    lanes = (
        build_lane("sensor", sensor_items),
        build_lane("logic", logic_items),
        build_lane("actuator", actuator_items),
    )

    pfd_sum, pfh_sum, breakdown = MainWindow._sum_lists(summation_harness, lanes, "low_demand")

    assert pytest.approx(pfd_sum) == 0.042
    assert pytest.approx(pfh_sum) == 4.2e-6

    combined = breakdown.get("combined")
    assert combined and len(combined) == 1
    subgroup = combined[0]
    assert subgroup["count"] == 3
    assert pytest.approx(subgroup["pfd"]) == 0.035
    assert pytest.approx(subgroup["pfh"]) == 3.5e-6
    assert set(subgroup["lanes"]) == {"Sensors / Inputs", "Logic", "Outputs / Actuators"}

    residuals = breakdown.get("lane_residuals")
    assert residuals and {entry["lane"] for entry in residuals} == {"sensor", "actuator"}
    residual_map = {entry["lane"]: entry for entry in residuals}
    assert pytest.approx(residual_map["sensor"]["pfd"]) == 0.003
    assert pytest.approx(residual_map["actuator"]["pfd"]) == 0.004

    totals = breakdown.get("total")
    assert totals is not None
    assert pytest.approx(totals["pfd"]) == pfd_sum
    assert pytest.approx(totals["pfh"]) == pfh_sum
