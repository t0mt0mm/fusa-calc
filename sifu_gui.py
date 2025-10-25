#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SIFU GUI (PyQt5) — UI/UX rework per preferences
- Theme: Light
- Type accents: YES (sensor/logic/actuator)
- Selection: Single-select
- Language: English (UI only; math/logic untouched)
"""

import os
import sys
import re
import uuid
import copy
import json
from typing import Dict, Tuple, List, Optional, Union, Any, Set
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTableWidget, QTableWidgetItem, QListWidget, QListWidgetItem, QLabel, QDockWidget, QLineEdit, QToolBar, QAction, QActionGroup, QToolButton, QFileDialog, QMessageBox, QHBoxLayout, QVBoxLayout, QFrame, QStyle, QDialog, QFormLayout, QDialogButtonBox, QDoubleSpinBox, QAbstractSpinBox, QComboBox, QSpinBox, QShortcut, QSizePolicy, QHeaderView, QAbstractItemView, QGridLayout, QColorDialog
)
from PyQt5.QtGui import QPainter, QColor, QFont, QPen, QKeySequence, QPixmap, QImage, QCursor, QIcon
from datetime import datetime
import yaml
import numpy as np
import html
from pathlib import Path

from sifu_core import (
    Assumptions,
    ChannelMetrics,
    ConversionError,
    calculate_one_out_of_two,
    calculate_single_channel,
    compute_lambda_total,
)
# ==========================


def new_instance_id() -> str:
    return uuid.uuid4().hex

# ==========================
# Tooltip helper (HTML)
# ==========================

def make_html_tooltip(title: str, pfd: Optional[float], pfh: Optional[float], syscap: Any,
                      pdm_code: str = "", pfh_entered_fit: Optional[float] = None,
                      pfd_entered_fit: Optional[float] = None,
                      extra_fields: Optional[Dict[str, Any]] = None,
                      note: Optional[str] = None) -> str:
    def esc(x: Any) -> str:
        return html.escape("" if x is None else str(x))

    def fmt_pfd(x): return "–" if x is None else f"{float(x):.6f}"
    def fmt_pfh(x): return "–" if x is None else f"{float(x):.3e} 1/h"

    rows = [
        f"<tr><td>PFDavg:</td><td>{fmt_pfd(pfd)}</td></tr>",
        f"<tr><td>PFHavg:</td><td>{fmt_pfh(pfh)}</td></tr>",
        f"<tr><td>SIL capability:</td><td>{esc(syscap)}</td></tr>"
    ]

    if pdm_code:
        rows.append(f"<tr><td>PDM code:</td><td>{esc(pdm_code)}</td></tr>")
    if pfh_entered_fit is not None:
        rows.append(f"<tr><td>PFH note:</td><td>{float(pfh_entered_fit):.1f} FIT</td></tr>")
    if pfd_entered_fit is not None:
        rows.append(f"<tr><td>PFD note:</td><td>{float(pfd_entered_fit):.1f} FIT</td></tr>")

    # Neue Felder aus YAML anzeigen
    if extra_fields:
        for key, val in extra_fields.items():
            if key in ("name", "code", "pfd", "pfh", "syscap", "pdm_code", "pfh_fit", "pfd_fit"):
                continue  # bereits dargestellt
            rows.append(f"<tr><td>{esc(key)}:</td><td>{esc(val)}</td></tr>")

    note_html = ""
    if note:
        note_html = f"<div style='margin-top:6px; font-size:11px; color:#555;'>{esc(note)}</div>"

    return f"<html><b>{esc(title)}</b><br><table>{''.join(rows)}</table>{note_html}</html>"

# ==========================
# ConfigDialog (modern, Tabs)
# ==========================
class ConfigDialog(QDialog):
    """
    Moderner Konfigurationsdialog:
      - Tab "Assumptions" für globale Parameter (mit Einheiten, Tooltips).
      - Tab "DU/DD ratios" mit DU-Spinbox (in %) und automatisch berechnetem DD (read-only),
        plus "Restore defaults".
      - Rückgabeformat bleibt kompatibel: (values, du_dd_ratios).
    """
    def __init__(self, assumptions: Dict[str, Any], du_dd_ratios: Dict[str, Tuple[float, float]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuration")
        self.setObjectName("ModernConfigDialog")

        self._defaults = {
            'TI': 8760.0,
            'MTTR': 8.0,
            'beta': 0.1,
            'beta_D': 0.02,
        }

        vroot = QVBoxLayout(self)
        vroot.setContentsMargins(14, 14, 14, 14)
        vroot.setSpacing(12)

        tabs = QtWidgets.QTabWidget(self)
        tabs.setObjectName("ConfigTabs")
        vroot.addWidget(tabs)

        # --- Tab 1: Assumptions ---
        pg_ass = QWidget(self)
        frm = QFormLayout(pg_ass)
        frm.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        frm.setFormAlignment(Qt.AlignTop)
        frm.setVerticalSpacing(10)
        self.fields: Dict[str, QDoubleSpinBox] = {}

        def add_param(key, label, minimum, maximum, decimals, step, tooltip, suffix=""):
            spin = QDoubleSpinBox()
            spin.setDecimals(decimals)
            spin.setRange(minimum, maximum)
            spin.setSingleStep(step)
            spin.setValue(float(assumptions.get(key, self._defaults.get(key, 0.0))))
            if suffix:
                spin.setSuffix(f" {suffix}")
            lbl = QLabel(label)
            lbl.setObjectName("FormLabel")
            lbl.setToolTip(tooltip)
            spin.setToolTip(tooltip)
            frm.addRow(lbl, spin)
            self.fields[key] = spin

        add_param('TI',   "TI — Proof-test interval", 0, 1e7, 2, 1.0,  "Duration between proof tests.", "h")
        add_param('MTTR', "MTTR — Mean time to repair", 0, 1e6, 2, 0.5,"Average repair time.", "h")
        add_param('beta',  "β — Common-cause fraction (DU)", 0, 1.0, 4, 0.001, "Common-cause share for DU.")
        add_param('beta_D',"β_D — Common-cause fraction (DD)",0, 1.0, 4, 0.001, "Common-cause share for DD.")
        tabs.addTab(pg_ass, "Assumptions")

        # --- Tab 2: DU/DD ratios ---
        pg_ratio = QWidget(self)
        grid = QtWidgets.QGridLayout(pg_ratio)
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(10)

        hdr_kind = QLabel("Group"); hdr_kind.setObjectName("TableHeader")
        hdr_du   = QLabel("DU [%]"); hdr_du.setObjectName("TableHeader")
        hdr_dd   = QLabel("DD [%]"); hdr_dd.setObjectName("TableHeader")
        grid.addWidget(hdr_kind, 0, 0); grid.addWidget(hdr_du, 0, 1); grid.addWidget(hdr_dd, 0, 2)

        self.du_dd_fields: Dict[str, Tuple[QDoubleSpinBox, QDoubleSpinBox]] = {}
        groups = ["sensor", "logic", "actuator"]
        for r, group in enumerate(groups, start=1):
            grid.addWidget(QLabel(group.capitalize()), r, 0)
            du_spin = QDoubleSpinBox(); dd_spin = QDoubleSpinBox()
            for sp in (du_spin, dd_spin):
                sp.setDecimals(2); sp.setRange(0.0, 100.0); sp.setSingleStep(0.5); sp.setSuffix(" %")
            dd_spin.setReadOnly(True)
            dd_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
            dd_spin.setFocusPolicy(Qt.NoFocus)

            du_f, dd_f = du_dd_ratios.get(group, (0.6, 0.4))
            du_spin.setValue(100.0 * float(du_f))
            dd_spin.setValue(100.0 * float(dd_f))

            def bind(du_sp=du_spin, dd_sp=dd_spin):
                def on_du(val: float):
                    dd_sp.blockSignals(True)
                    try:
                        dd_sp.setValue(max(0.0, min(100.0, 100.0 - float(val))))
                    finally:
                        dd_sp.blockSignals(False)
                on_du(du_sp.value())
                du_sp.valueChanged.connect(on_du)
            bind()

            grid.addWidget(du_spin, r, 1)
            grid.addWidget(dd_spin, r, 2)
            self.du_dd_fields[group] = (du_spin, dd_spin)

        # Reset-Button
        btn_reset = QtWidgets.QPushButton("Restore defaults")
        btn_reset.setObjectName("LinkButton")
        btn_reset.setCursor(Qt.PointingHandCursor)

        def do_reset():
            self.fields['TI'].setValue(self._defaults['TI'])
            self.fields['MTTR'].setValue(self._defaults['MTTR'])
            self.fields['beta'].setValue(self._defaults['beta'])
            self.fields['beta_D'].setValue(self._defaults['beta_D'])
            for g, (du_sp, dd_sp) in self.du_dd_fields.items():
                du, dd = (0.7, 0.3) if g == "sensor" else (0.6, 0.4)
                du_sp.setValue(du * 100.0)
                dd_sp.setValue(dd * 100.0)

        btn_reset.clicked.connect(do_reset)
        grid.addWidget(btn_reset, grid.rowCount(), 0, 1, 3, alignment=Qt.AlignLeft)

        tabs.addTab(pg_ratio, "DU/DD ratios")

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        vroot.addWidget(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    def get_values(self) -> Tuple[Dict[str, float], Dict[str, Tuple[float, float]]]:
        values = {key: spin.value() for key, spin in self.fields.items()}
        du_dd: Dict[str, Tuple[float, float]] = {}
        for group, (du_sp, dd_sp) in self.du_dd_fields.items():
            du = float(du_sp.value()) / 100.0
            dd = float(dd_sp.value()) / 100.0
            tot = du + dd
            du_dd[group] = ((du / tot, dd / tot) if tot > 0 else (0.6, 0.4))
        return values, du_dd

class NumpySafeDumper(yaml.SafeDumper):
    def represent_data(self, data):
        if isinstance(data, (np.integer, np.floating)):
            return super().represent_data(data.item())
        return super().represent_data(data)

# ==========================
# Data access via existing classes (unchanged)
# ==========================

try:
    from SilCalc_0004 import CeMatrix, EeOverview, FuSa  # type: ignore
except Exception as e:
    raise SystemExit(f"Failed to import SilCalc_0004.py: {e}")

def load_sifu_dataframe():
    """Use the existing classes to get the DataFrame with SIFU + components. Expects config.yaml."""
    ce_matrix = CeMatrix("config.yaml")
    ee_overview = EeOverview("config.yaml")
    fusa = FuSa("config.yaml")
    data = ce_matrix.get_content()
    ee_overview.get_pdm_codes(data)
    fusa.get_fusa_data(data)
    return data

# ==========================
# SIL helpers (unchanged math)
# ==========================

def classify_sil_from_pfh(pfh_sum: float) -> str:
    if 1e-9 <= pfh_sum < 1e-8: return "SIL 4"
    if 1e-8 <= pfh_sum < 1e-7: return "SIL 3"
    if 1e-7 <= pfh_sum < 1e-6: return "SIL 2"
    if 1e-6 <= pfh_sum < 1e-5: return "SIL 1"
    return "n.a."

def classify_sil_from_pfd(pfd_sum: float) -> str:
    if 1e-5 <= pfd_sum < 1e-4: return "SIL 4"
    if 1e-4 <= pfd_sum < 1e-3: return "SIL 3"
    if 1e-3 <= pfd_sum < 1e-2: return "SIL 2"
    if 1e-2 <= pfd_sum < 1e-1: return "SIL 1"
    return "n.a."

def sil_rank(s: str) -> int:
    s = (s or "").strip().upper()
    m = re.search(r"\b([1-4])\b", s)
    if not m: return 0
    n = int(m.group(1))
    return n if 1 <= n <= 4 else 0

def normalize_required_sil(val: Union[str, int, float]) -> Tuple[str, int]:
    if isinstance(val, (int, float)):
        n = int(val)
        return (f"SIL {n}", n) if 1 <= n <= 4 else ("n.a.", 0)
    if isinstance(val, str):
        r = sil_rank(val)
        return (f"SIL {r}", r) if r else ("n.a.", 0)
    return ("n.a.", 0)

# ==========================
# Row metadata
# ==========================

class RowMeta(dict):
    """Per-row metadata: sifu_name, sil_required, demand_mode_required, demand_mode_override(optional), source('df'/'user')."""
    pass

# ==========================
# Result cell (summary + subtext + demand-mode combo)
# ==========================

SIL_BADGE_STYLES: Dict[str, Tuple[str, str, str]] = {
    "met": ("#0f5132", "#d1f7e1", "#2ecc71"),
    "not_met": ("#7f1d1d", "#fde2e1", "#f87171"),
    "neutral": ("#374151", "#f3f4f6", "#d1d5db"),
}


class ResultCell(QWidget):
    override_changed = QtCore.pyqtSignal(str)  # 'High demand' or 'Low demand'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ResultCell")

        self.lbl_summary = QLabel("")
        self.lbl_summary.setObjectName("ResultSummary")
        self.lbl_summary.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.lbl_summary.hide()

        self.sil_badge = QLabel("SIL –")
        self.sil_badge.setObjectName("SilBadge")
        self.sil_badge.setAlignment(Qt.AlignCenter)
        self.sil_badge.setMinimumWidth(64)
        self.sil_badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # Demand-mode selector (kompakt)
        self.combo = QComboBox()
        self.combo.addItems(["High demand", "Low demand"])
        self.combo.setObjectName("DemandCombo")
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.combo.setMinimumContentsLength(0)

        # Breite dynamisch auf Inhalt begrenzen
        def _shrink_to_content():
            # +10 px für Innenabstand / Rahmen
            self.combo.setMaximumWidth(self.combo.sizeHint().width() + 10)

        _shrink_to_content()
        self.combo.currentTextChanged.connect(
            lambda _t: (_shrink_to_content(), self.override_changed.emit(self.combo.currentText()))
        )

        # Caption + value labels
        self.demand_caption = QLabel("Demand mode")
        self.demand_caption.setObjectName("ResultCaption")

        self.req_caption = QLabel("Required SIL")
        self.req_caption.setObjectName("ResultCaption")
        self.calc_caption = QLabel("Calculated SIL")
        self.calc_caption.setObjectName("ResultCaption")
        self.metric_caption = QLabel("Metric")
        self.metric_caption.setObjectName("ResultCaption")

        self.req_value = QLabel("–")
        self.calc_value = QLabel("–")
        self.metric_value = QLabel("–")
        for lbl in (self.req_value, self.calc_value, self.metric_value):
            lbl.setObjectName("ResultValue")
            lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            lbl.setWordWrap(False)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.metric_value.setProperty("variant", "metric")
        self.metric_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        card = QFrame()
        card.setObjectName("ResultCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 18)
        card_layout.setSpacing(12)

        summary_row = QHBoxLayout()
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.setSpacing(12)
        summary_row.addWidget(self.sil_badge, 0, Qt.AlignLeft)
        summary_row.addStretch(1)
        card_layout.addLayout(summary_row)

        demand_row = QHBoxLayout()
        demand_row.setContentsMargins(0, 0, 0, 0)
        demand_row.setSpacing(8)
        demand_row.addWidget(self.demand_caption)
        demand_row.addWidget(self.combo)
        demand_row.addStretch(1)
        card_layout.addLayout(demand_row)

        info_grid = QGridLayout()
        info_grid.setContentsMargins(0, 0, 0, 0)
        info_grid.setHorizontalSpacing(16)
        info_grid.setVerticalSpacing(8)
        info_grid.addWidget(self.req_caption, 0, 0, Qt.AlignLeft | Qt.AlignTop)
        info_grid.addWidget(self.req_value, 0, 1)
        info_grid.addWidget(self.calc_caption, 1, 0, Qt.AlignLeft | Qt.AlignTop)
        info_grid.addWidget(self.calc_value, 1, 1)
        info_grid.addWidget(self.metric_caption, 2, 0, Qt.AlignLeft | Qt.AlignTop)
        info_grid.addWidget(self.metric_value, 2, 1)
        info_grid.setColumnStretch(1, 1)
        card_layout.addLayout(info_grid)
        card_layout.addStretch(1)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(card, 1)

        self.set_sil_badge("n.a.", None)

    def set_sil_badge(self, sil_text: str, requirement_met: Optional[bool]) -> None:
        sil_normalized = (sil_text or "").strip().upper()
        if sil_rank(sil_normalized) == 0:
            sil_normalized = "SIL –"

        if requirement_met is True:
            palette_key = "met"
        elif requirement_met is False:
            palette_key = "not_met"
        else:
            palette_key = "neutral"

        fg, bg, border = SIL_BADGE_STYLES[palette_key]
        self.sil_badge.setText(sil_normalized)
        self.sil_badge.setStyleSheet(
            f"QLabel#SilBadge{{"
            f"padding:4px 16px; border-radius:18px; font-weight:600;"
            f"text-transform:uppercase; letter-spacing:0.05em;"
            f"color:{fg}; background:{bg}; border:1px solid {border};"
            f"}}"
        )

# ==========================
# Chip lists with kind constraints (visual accents + drag highlight)
# ==========================
class ChipList(QListWidget):
    """ Drag&Drop list for component chips.
    • Reorder within same list → Move
    • Drop into different list → Copy
    • Enforces column kind constraints via allowed_kind.
    • Visual: light theme, accent border-left via item widget with property kind.
    """
    def __init__(self, parent=None, placeholder: str = "Drop components here …", allowed_kind: str = ""):
        super().__init__(parent)
        self.setSelectionMode(QListWidget.SingleSelection)  # as requested: Single-Select
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setDragDropMode(QListWidget.DragDrop)
        self.setAlternatingRowColors(False)
        self.setMinimumHeight(64)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._open_ctx)
        self._placeholder = placeholder
        self.allowed_kind = allowed_kind  # "sensor" \ "logic" \ "actuator"
        self.setToolTip("Drag components here or between lanes. Single selection; drop from libraries to add items.")

    # ----- Item presentation helper -----
    def attach_chip(self, item: QListWidgetItem) -> None:
        d = item.data(Qt.UserRole) or {}
        kind = d.get("kind", self.allowed_kind)
        text = d.get("code") or d.get("name") or item.text()

        if d.get("group") and d.get("architecture") == "1oo2":
            widget = QWidget()
            widget.setProperty("kind", kind)
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(8, 4, 8, 4)
            layout.setSpacing(8)

            indicator = self._make_link_indicator()
            layout.addWidget(indicator)
            widget._link_indicator = indicator  # type: ignore[attr-defined]

            members = [m for m in d.get("members", []) if isinstance(m, dict)]
            member_labels: List[str] = []
            for idx, member in enumerate(members):
                label = member.get("code") or member.get("name") or f"Member {idx + 1}"
                member_labels.append(str(label))

            primary_label = member_labels[0] if member_labels else str(text)
            secondary_label = member_labels[1] if len(member_labels) > 1 else None

            layout.addWidget(self._make_chip_label(primary_label))

            badge = QLabel("← 1oo2 →")
            badge.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            badge.setStyleSheet(
                "QLabel{color:#555; background:#eee; border:1px solid #ddd; "
                "border-radius:10px; padding:4px 10px; font-size:11px; font-weight:bold;}"
            )
            layout.addWidget(badge)

            if secondary_label:
                layout.addWidget(self._make_chip_label(secondary_label))

            widget.setMinimumHeight(30)
            size_hint = widget.sizeHint()
            try:
                size_hint.setHeight(max(size_hint.height(), 38))
            except Exception:
                pass

            item.setText(" + ".join(lbl for lbl in member_labels[:2] if lbl) or primary_label)
            item.setSizeHint(size_hint)
            self.setItemWidget(item, widget)

            window = self.window()
            if window and hasattr(window, "_tooltip_for_1oo2"):
                try:
                    m1 = members[0] if len(members) > 0 else {}
                    m2 = members[1] if len(members) > 1 else {}
                    tooltip = window._tooltip_for_1oo2(m1, m2, kind)
                    if tooltip:
                        item.setToolTip(tooltip)
                except Exception:
                    pass
        else:
            widget = QWidget()
            widget.setProperty("kind", kind)
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(8, 4, 8, 4)
            layout.setSpacing(6)

            indicator = self._make_link_indicator()
            layout.addWidget(indicator)
            widget._link_indicator = indicator  # type: ignore[attr-defined]

            label = QLabel(str(text))
            label.setObjectName("ChipLabel")
            label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            label.adjustSize()
            layout.addWidget(label)

            widget.setMinimumHeight(30)
            size_hint = widget.sizeHint()
            try:
                size_hint.setHeight(max(size_hint.height(), 38))
            except Exception:
                pass
            item.setText(str(text))
            item.setSizeHint(size_hint)
            self.setItemWidget(item, widget)

        self._apply_link_properties(self.itemWidget(item), d)

    # ----- Painting placeholder -----
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count() == 0 and self._placeholder:
            p = QPainter(self.viewport())
            p.setRenderHints(QPainter.Antialiasing)
            p.setPen(QPen(QColor("#9aa0a6")))
            f = QFont(self.font()); f.setPointSize(9)
            p.setFont(f)
            text = self._placeholder
            p.drawText(self.viewport().rect(), Qt.AlignCenter, text)

    def setPlaceholder(self, text: str):
        self._placeholder = text
        self.viewport().update()

    # ----- Context menu -----
    def _open_ctx(self, pos):
        m = QtWidgets.QMenu(self)
        act_add = m.addAction("Add Component…")
        act_del = m.addAction("Remove")
        window = self.window()
        row_idx = -1
        lane = None
        if window and hasattr(window, "_row_lane_for_list"):
            try:
                row_idx, lane = window._row_lane_for_list(self)
            except Exception:
                row_idx, lane = -1, None

        act_start_link = act_stop_link = act_choose_color = act_clear_lane = act_clear_sifu = None
        if lane is not None and isinstance(row_idx, int) and row_idx >= 0:
            m.addSeparator()
            is_active = bool(window and hasattr(window, "_is_link_active_for") and window._is_link_active_for(row_idx, lane))
            if is_active:
                act_choose_color = m.addAction("Choose link colour…")
                act_stop_link = m.addAction("Stop link mode")
            else:
                act_start_link = m.addAction("Start link mode here")
                act_choose_color = m.addAction("Choose link colour…")
            act_clear_lane = m.addAction("Clear lane links")
            act_clear_sifu = m.addAction("Clear SIFU links")

        action = m.exec_(self.mapToGlobal(pos))
        if action == act_del:
            for item in self.selectedItems():
                self.takeItem(self.row(item))
            self.window().statusBar().showMessage("Removed component", 2000)
            self.window().recalculate_all()
        elif action == act_add:
            self.window().open_add_component_dialog(pref_kind=self.allowed_kind, insert_into_row=True)
        elif action == act_start_link and window:
            window._activate_link_mode_for(row_idx, lane, self)
        elif action == act_stop_link and window:
            window._end_link_session()
        elif action == act_choose_color and window:
            window._popup_link_color_menu(QCursor.pos())
        elif action == act_clear_lane and window:
            window._clear_lane_links(row_idx, lane)
        elif action == act_clear_sifu and window:
            window._clear_sifu_links(row_idx)

    # ----- Kind constraint -----
    def _can_accept_item(self, qitem: QListWidgetItem) -> bool:
        d = qitem.data(Qt.UserRole) or {}
        return (not self.allowed_kind) or (d.get("kind", "") == self.allowed_kind)

    # ----- Drag highlight -----
    def dragEnterEvent(self, event):
        super().dragEnterEvent(event)
        self.setProperty("dragTarget", True)
        self.style().unpolish(self); self.style().polish(self)

    def dragLeaveEvent(self, event):
        super().dragLeaveEvent(event)
        self.setProperty("dragTarget", False)
        self.style().unpolish(self); self.style().polish(self)

    def dropEvent(self, event):
        src = event.source()
        # Early reject if kinds mismatch
        if isinstance(src, ChipList):
            items = src.selectedItems()
            if items and not all(self._can_accept_item(it) for it in items):
                event.ignore()
                self.setProperty("dragTarget", False)
                self.style().unpolish(self); self.style().polish(self)
                return

        if isinstance(src, ChipList) and src is not self:
            items = src.selectedItems()
            if items:
                insert_row = self.indexAt(event.pos()).row()
                for it in items:
                    new_it = QListWidgetItem(it)
                    base_data = it.data(Qt.UserRole) or {}
                    window = self.window()
                    clone_func = getattr(window, "_clone_chip_data", None)
                    if callable(clone_func):
                        new_data = clone_func(base_data, preserve_id=False)
                    else:
                        new_data = copy.deepcopy(base_data)
                        new_data["instance_id"] = new_instance_id()
                    new_it.setData(Qt.UserRole, new_data)
                    if insert_row < 0:
                        self.addItem(new_it)
                    else:
                        self.insertItem(insert_row, new_it)
                    # ensure visual widget
                    self.attach_chip(new_it)
                event.acceptProposedAction()
        else:
            # internal drop (same list): distinguish Copy vs Move
            items = self.selectedItems()
            if items and not all(self._can_accept_item(it) for it in items):
                event.ignore()
                self.setProperty("dragTarget", False)
                self.style().unpolish(self); self.style().polish(self)
                return
            if event.dropAction() == Qt.CopyAction:
                insert_row = self.indexAt(event.pos()).row()
                for it in items:
                    new_it = QListWidgetItem(it)
                    base_data = it.data(Qt.UserRole) or {}
                    window = self.window()
                    clone_func = getattr(window, "_clone_chip_data", None)
                    if callable(clone_func):
                        new_data = clone_func(base_data, preserve_id=False)
                    else:
                        new_data = copy.deepcopy(base_data)
                        new_data["instance_id"] = new_instance_id()
                    new_it.setData(Qt.UserRole, new_data)
                    if insert_row < 0:
                        self.addItem(new_it)
                    else:
                        self.insertItem(insert_row, new_it)
                    self.attach_chip(new_it)
                event.acceptProposedAction()
            else:
                super().dropEvent(event)

        self.setProperty("dragTarget", False)
        self.style().unpolish(self); self.style().polish(self)
        self.window().statusBar().showMessage("Moved component", 1500)
        self.window().recalculate_all()

    def mousePressEvent(self, event):
        window = self.window()
        if window:
            setattr(window, "_last_focused_list", self)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if item:
                window = self.window()
                handler = getattr(window, "_handle_link_click", None)
                if callable(handler):
                    handler(self, item)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        window = self.window()
        if window:
            setattr(window, "_last_focused_list", self)

    def _apply_link_properties(self, widget: Optional[QWidget], data: Dict[str, Any]) -> None:
        if widget is None:
            return
        window = self.window()
        color_value = data.get("link_color") if isinstance(data, dict) else None
        sanitized = None
        if window and color_value and hasattr(window, "_sanitize_link_color"):
            sanitized = window._sanitize_link_color(color_value)
        elif isinstance(color_value, str):
            sanitized = color_value

        indicator = getattr(widget, "_link_indicator", None)
        if isinstance(indicator, QLabel):
            if sanitized:
                indicator.setVisible(True)
                indicator.setStyleSheet(
                    "QLabel{background:%s; border-radius:5px; border:1px solid rgba(15,23,42,0.18);}" % sanitized
                )
            else:
                indicator.setVisible(False)
                indicator.setStyleSheet(
                    "QLabel{background: transparent; border-radius:5px; border:1px solid rgba(148,163,184,0.45);}"  # noqa: E501
                )

        widget.setProperty("linkTag", None)

    def refresh_chip(self, item: QListWidgetItem) -> None:
        if not item:
            return
        widget = self.itemWidget(item)
        if widget is None:
            self.attach_chip(item)
        else:
            self._apply_link_properties(widget, item.data(Qt.UserRole) or {})

    @staticmethod
    def _make_chip_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFrameShape(QFrame.NoFrame)
        lbl.setStyleSheet(
            "QLabel{border:1px solid #e6e6e6;border-radius:10px;padding:4px 8px;"
            "background:#f6f6f6;font-size:10px; color:#333;}"
        )
        lbl.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        lbl.adjustSize()
        return lbl

    @staticmethod
    def _make_link_indicator() -> QLabel:
        indicator = QLabel()
        indicator.setObjectName("ChipLinkDot")
        indicator.setFixedSize(10, 10)
        indicator.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        indicator.setStyleSheet(
            "QLabel{background: transparent; border-radius:5px; border:1px solid rgba(148,163,184,0.45);}"  # noqa: E501
        )
        indicator.setVisible(False)
        return indicator


class ActuatorList(ChipList):
    """Specialized list: drop on existing item can form a 1oo2 group."""
    def dropEvent(self, event):
        src = event.source()
        pos = event.pos()
        target_row = self.indexAt(pos).row()

        # Global constraint check
        if isinstance(src, ChipList):
            items = src.selectedItems()
            if items and not all(self._can_accept_item(it) for it in items):
                event.ignore()
                self.setProperty("dragTarget", False)
                self.style().unpolish(self); self.style().polish(self)
                return

        if target_row >= 0 and isinstance(src, ChipList):
            t_item = self.item(target_row)
            t_data = (t_item.data(Qt.UserRole) or {}) if t_item else {}
            if t_item and not t_data.get('group'):
                src_items = src.selectedItems()
                if not src_items:
                    return super().dropEvent(event)
                s_item = src_items[0]
                s_data = s_item.data(Qt.UserRole) or {}
                if s_data.get('group'):
                    return super().dropEvent(event)

                t_name = str(t_data.get('code', '?'))
                s_name = str(s_data.get('code', '?'))
                reply = QMessageBox.question(
                    self, "Create 1oo2 group?",
                    f"Combine actuators • {t_name} • {s_name} as a 1oo2 group?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if reply == QMessageBox.Yes:
                    members: List[dict] = []
                    for payload in (t_data, s_data):
                        member = copy.deepcopy(payload)
                        if not isinstance(member.get('instance_id'), str):
                            member['instance_id'] = new_instance_id()
                        members.append(member)

                    grp_item = QListWidgetItem(f"{t_name} + {s_name}")
                    grp_item.setData(Qt.UserRole, {
                        'group': True,
                        'architecture': '1oo2',
                        'members': members,
                        'kind': 'actuator',
                        'instance_id': new_instance_id(),
                    })

                    self.takeItem(target_row)
                    self.insertItem(target_row, grp_item)
                    self.attach_chip(grp_item)

                    if src is self:
                        qrow = self.row(s_item)
                        if qrow != -1:
                            self.takeItem(qrow)

                    event.acceptProposedAction()
                    self.window().statusBar().showMessage("Created 1oo2 actuator group", 2000)
                    self.window().recalculate_all()
                    return

        super().dropEvent(event)
        self.setProperty("dragTarget", False)
        self.style().unpolish(self); self.style().polish(self)
        self.window().recalculate_all()




class SensorList(ChipList):
    """Specialized list: drop on existing item can form a 1oo2 group for sensors."""
    def dropEvent(self, event):
        src = event.source()
        pos = event.pos()
        target_row = self.indexAt(pos).row()

        if isinstance(src, ChipList):
            items = src.selectedItems()
            if items and not all(self._can_accept_item(it) for it in items):
                event.ignore()
                self.setProperty("dragTarget", False)
                self.style().unpolish(self); self.style().polish(self)
                return

        if target_row >= 0 and isinstance(src, ChipList):
            t_item = self.item(target_row)
            t_data = (t_item.data(Qt.UserRole) or {}) if t_item else {}
            if t_item and not t_data.get('group'):
                src_items = src.selectedItems()
                if not src_items:
                    return super().dropEvent(event)
                s_item = src_items[0]
                s_data = s_item.data(Qt.UserRole) or {}
                if s_data.get('group'):
                    return super().dropEvent(event)

                t_name = str(t_data.get('code', '?'))
                s_name = str(s_data.get('code', '?'))
                reply = QMessageBox.question(
                    self, "Create 1oo2 group?",
                    f"Combine sensors • {t_name} • {s_name} as a 1oo2 group?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if reply == QMessageBox.Yes:
                    members: List[dict] = []
                    for payload in (t_data, s_data):
                        member = copy.deepcopy(payload)
                        if not isinstance(member.get('instance_id'), str):
                            member['instance_id'] = new_instance_id()
                        members.append(member)

                    grp_item = QListWidgetItem(f"{t_name} + {s_name}")
                    grp_item.setData(Qt.UserRole, {
                        'group': True,
                        'architecture': '1oo2',
                        'members': members,
                        'kind': 'sensor',
                        'instance_id': new_instance_id(),
                    })

                    self.takeItem(target_row)
                    self.insertItem(target_row, grp_item)
                    self.attach_chip(grp_item)

                    if src is self:
                        qrow = self.row(s_item)
                        if qrow != -1:
                            self.takeItem(qrow)

                    event.acceptProposedAction()
                    self.window().statusBar().showMessage("Created 1oo2 sensor group", 2000)
                    self.window().recalculate_all()
                    return

        super().dropEvent(event)
        self.setProperty("dragTarget", False)
        self.style().unpolish(self); self.style().polish(self)
        self.window().recalculate_all()

class SifuRowWidgets:
    """Container of column lists + result cell."""
    def __init__(self):
        self.in_list = SensorList(placeholder="Drop sensors here …\n(Double-click a library item to add)", allowed_kind="sensor")
        self.logic_list = ChipList(placeholder="Drop logic items here …\n(Double-click a library item to add)", allowed_kind="logic")
        self.out_list = ActuatorList(placeholder="Drop actuators here …\n(Double-click a library item to add)", allowed_kind="actuator")
        self.result = ResultCell()

# ==========================
# Generic Component Library Dock
# ==========================
class _DockHeader(QWidget):
    """Kompakter Header mit Titel, Suchfeld, Zähler und 'Add…'."""
    def __init__(self, title: str, parentDock: 'ComponentLibraryDock'):
        super().__init__(parentDock)
        self.setObjectName("DockHeader")
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(8)
        self.lbl = QLabel(title)
        self.lbl.setObjectName("DockTitle")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter…")
        self.search.setClearButtonEnabled(True)
        self.search.setObjectName("DockSearch")
        self.count = QLabel("0")
        self.count.setObjectName("DockCount")
        self.btnAdd = QtWidgets.QToolButton()
        self.btnAdd.setText("Add…")
        self.btnAdd.setCursor(Qt.PointingHandCursor)
        self.btnAdd.setObjectName("DockAdd")
        self.btnAdd.setToolButtonStyle(Qt.ToolButtonTextOnly)
        h.addWidget(self.lbl)
        h.addStretch(1)
        h.addWidget(self.search, 2)
        h.addWidget(self.count)
        h.addWidget(self.btnAdd)

class _LibCard(QWidget):
    """Zweizeilige Karte für einen Komponenten-Eintrag (robuste Größe, Eliding, keine Überlappungen)."""
    def __init__(self, name: str, pfd: float, pfh: float, syscap: str, pdm: str, kind: str):
        super().__init__()
        self.setObjectName("LibCard")
        self.setProperty("kind", kind)

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(6)

        # Titel einzeilig + Tooltip; Eliding pragmatisch (kein Umbruch)
        title = QLabel(name)
        title.setObjectName("LibCardTitle")
        title.setWordWrap(False)
        title.setToolTip(name)
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        v.addWidget(title)

        # Info-Badges
        row = QHBoxLayout()
        row.setSpacing(6)
        row.setContentsMargins(0, 0, 0, 0)

        def pill(text: str):
            l = QLabel(text)
            l.setObjectName("Pill")
            l.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            return l

        row.addWidget(pill(f"PFD {float(pfd):.6f}"))
        row.addWidget(pill(f"PFH {float(pfh):.3e} 1/h"))
        if syscap:
            row.addWidget(pill(f"SIL {syscap}"))
        if pdm:
            row.addWidget(pill(f"PDM {pdm}"))
        row.addStretch(1)
        v.addLayout(row)

        # Stabile Mindesthöhe (gegen Überlappungen)
        self._min_h = 56
        self.setMinimumHeight(self._min_h)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def sizeHint(self) -> QtCore.QSize:
        sh = super().sizeHint()
        return QtCore.QSize(sh.width(), max(self._min_h, sh.height()))
        
class ComponentLibraryDock(QDockWidget):
    """
    Moderne Component Library:
      - Eigener Header mit Suchfeld, Zähler, Add-Button.
      - Karten-Ansicht mit stabiler Höhe (keine Überlappungen).
      - Persistenz identisch zu vorher (YAML).
    """
    modified = QtCore.pyqtSignal()

    def __init__(self, title: str, kind: str, yaml_file: str, parent=None):
        super().__init__(title, parent)
        self.kind = kind
        self.yaml_file = yaml_file
        self.setObjectName(f"{kind.capitalize()}LibraryDock")

        # Custom Titlebar
        self._header = _DockHeader(title, self)
        self.setTitleBarWidget(self._header)

        # Body
        self.widget = QWidget()
        self.setWidget(self.widget)
        self.vbox = QtWidgets.QVBoxLayout(self.widget)
        self.vbox.setContentsMargins(8, 6, 8, 6)
        self.vbox.setSpacing(6)

        # Liste
        self.list = QListWidget()
        self.list.setObjectName("LibList")
        self.list.setSelectionMode(QListWidget.SingleSelection)

        # >>> Kritische List-Flags gegen Überlappung
        from PyQt5.QtWidgets import QListView, QAbstractItemView
        self.list.setViewMode(QListView.ListMode)            # einspaltig
        self.list.setWrapping(False)                          # kein Spaltenumbruch
        self.list.setResizeMode(QListView.Adjust)             # Layout passt sich an
        self.list.setUniformItemSizes(False)                  # unterschiedliche Höhen zulassen
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setSpacing(8)

        self.vbox.addWidget(self.list)

        # Events
        self.list.itemActivated.connect(self._on_double_clicked)  # Enter/Doppelklick
        self._header.search.textChanged.connect(self._apply_filter)
        self._header.btnAdd.clicked.connect(lambda: self.window().open_add_component_dialog(pref_kind=self.kind))

        # Data
        self._all_items_cache: List[Dict[str, Any]] = []
        self.items_data: List[dict] = []
        self.on_add_requested: Optional[callable] = None

        # Optional: GridSize-Minimum stabilisiert Darstellung bei extrem schmalem Dock
        self._sync_liblist_grid()
        old_resize = self.list.viewport().resizeEvent
        def _res(ev):
            if callable(old_resize):
                old_resize(ev)
            self._sync_liblist_grid()
        self.list.viewport().resizeEvent = _res  # type: ignore

    # ---- Persistenz (unverändert inhaltlich) ----
    def load_from_yaml(self) -> bool:
        """Load YAML if present. Returns True if parsed (even if 0 components), else False."""
        if not os.path.exists(self.yaml_file):
            return False
        try:
            with open(self.yaml_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            QMessageBox.critical(self, "Load YAML", f"Could not load '{self.yaml_file}': {e}")
            return False
        comps = data.get('components', [])
        self.populate_from_components(comps)
        return True  # file existed and parsed

    def is_empty(self) -> bool:
        """Return True if the dock list currently holds no items."""
        return self.list.count() == 0

    def save_to_yaml(self) -> None:
        comps = []
        for it in self._all_items_cache:
            d = dict(it["data"])  # komplette Daten inkl. Zusatzfelder
            # Für YAML schöne Keys: pfd/pfh als pfd_avg/pfh_avg mappen (optional)
            if "pfd" in d and "pfd_avg" not in d:
                d["pfd_avg"] = float(d["pfd"])
            if "pfh" in d and "pfh_avg" not in d:
                d["pfh_avg"] = float(d["pfh"])
            # ggf. redundante interne Keys entfernen (optional):
            # d.pop("kind", None); d.pop("code", None)
            comps.append(d)
        payload = {"components": comps}
        try:
            with open(self.yaml_file, 'w', encoding='utf-8') as f:
                yaml.dump(payload, f, sort_keys=False, allow_unicode=True, Dumper=NumpySafeDumper)
        except Exception as e:
            QMessageBox.critical(self, "Save YAML", f"Could not save '{self.yaml_file}': {e}")


    def bootstrap_from_table(self, table_gather: List[Dict[str, Any]]) -> None:
        seen = set()
        comps = []
        for d in table_gather:
            key = d.get("name") or d.get("code")
            if not key or key in seen:
                continue
            seen.add(key)
            comps.append({
                "name": d.get("name") or d.get("code") or "",
                "pfd_avg": float(d.get("pfd", 0.0)),
                "pfh_avg": float(d.get("pfh", 0.0)),
                "sys_cap": d.get("syscap", ""),
                "pdm_code": d.get("pdm_code", ""),
            })
        self.populate_from_components(comps)
        self.save_to_yaml()

    # ---- Darstellung/Populate ----
    def populate_from_components(self, comps: List[dict]) -> None:
        self.items_data = comps or []
        self._all_items_cache.clear()
        self.list.clear()

        for comp in self.items_data:
            name   = str(comp.get('name', comp.get('code', '?')))
            pfd    = float(comp.get('pfd_avg', comp.get('pfd', 0.0)))
            pfh    = float(comp.get('pfh_avg', comp.get('pfh', 0.0)))
            syscap = comp.get('sys_cap', comp.get('syscap', ''))
            pdm    = comp.get('pdm_code', '')

            item = QListWidgetItem(name)  # Text bleibt für Sortierung/Filter
            item.setToolTip(make_html_tooltip(
                name, pfd, pfh, syscap, pdm_code=pdm,
                pfh_entered_fit=comp.get("pfh_fit"),
                pfd_entered_fit=comp.get("pfd_fit"),
                extra_fields=comp  # alle Felder rein
            ))

            data = {
                "name": name, "code": name, "pfd": pfd, "pfh": pfh,
                "syscap": syscap, "pdm_code": pdm, "kind": self.kind
            }
            item.setData(Qt.UserRole, data)

            card = _LibCard(name, pfd, pfh, syscap, pdm, self.kind)
            item.setSizeHint(card.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, card)

            self._all_items_cache.append({"name": name, "tooltip": item.toolTip(), "data": data})

        self.list.sortItems(Qt.AscendingOrder)
        self._update_count_label()
        QtCore.QTimer.singleShot(0, self.list.doItemsLayout)

    def _apply_filter(self, text: str):
        text = (text or "").lower().strip()
        self.list.clear()

        for it in self._all_items_cache:
            hay = f"{it['name']} {it['tooltip']}".lower()
            if not text or text in hay:
                item = QListWidgetItem(it["name"])
                item.setToolTip(it["tooltip"])
                item.setData(Qt.UserRole, it["data"])
                card = _LibCard(
                    it["name"],
                    it["data"]["pfd"],
                    it["data"]["pfh"],
                    it["data"].get("syscap",""),
                    it["data"].get("pdm_code",""),
                    self.kind
                )
                item.setSizeHint(card.sizeHint())
                self.list.addItem(item)
                self.list.setItemWidget(item, card)

        self.list.sortItems(Qt.AscendingOrder)
        self._update_count_label()
        QtCore.QTimer.singleShot(0, self.list.doItemsLayout)

    def _prepare_item_for_card(item: QListWidgetItem, name: str):
        """
        Unterdrückt die Standard-Textdarstellung des QListWidgetItem,
        behält aber einen separaten Sortierwert.
        """
        item.setData(Qt.DisplayRole, "")           # ➟ kein Standard-Text zeichnen
        item.setData(Qt.UserRole + 1, name)        # ➟ Sortier-/Filter-Schlüssel

    def add_component(self, d: Dict[str, Any]) -> None:
        name = d.get("name") or d.get("code") or ""
        pfd  = float(d.get("pfd", 0.0))
        pfh  = float(d.get("pfh", 0.0))
        syscap = d.get("syscap", "")
        pdm    = d.get("pdm_code", "")
        pfh_fit = d.get("pfh_fit", None)
        pfd_fit = d.get("pfd_fit", None)

        item = QListWidgetItem(name)
        item.setToolTip(make_html_tooltip(
            name, pfd, pfh, syscap, pdm_code=pdm, pfh_entered_fit=pfh_fit, pfd_entered_fit=pfd_fit
        ))
        d2 = {"name": name, "code": name, "pfd": pfd, "pfh": pfh, "syscap": syscap, "pdm_code": pdm, "kind": self.kind}
        if pfh_fit is not None: d2["pfh_fit"] = float(pfh_fit)
        if pfd_fit is not None: d2["pfd_fit"] = float(pfd_fit)
        item.setData(Qt.UserRole, d2)

        card = _LibCard(name, pfd, pfh, syscap, pdm, self.kind)
        item.setSizeHint(card.sizeHint())
        self.list.addItem(item)
        self.list.setItemWidget(item, card)

        self._all_items_cache.append({"name": name, "tooltip": item.toolTip(), "data": d2})
        self.modified.emit()
        self.save_to_yaml()
        self._update_count_label()
        QtCore.QTimer.singleShot(0, self.list.doItemsLayout)

    # ---- Interaktion ----
    def _on_double_clicked(self, item: QListWidgetItem):
        if not item or not self.on_add_requested:
            return
        data = item.data(Qt.UserRole) or {}
        self.on_add_requested(data)

    def _update_count_label(self):
        self._header.count.setText(str(self.list.count()))

    def _sync_liblist_grid(self):
        # Mindestbreite/Höhe einer Card -> stabilisiert Layout bei schmalen Docks
        w = max(220, self.list.viewport().width() - 16)
        h = 60
        self.list.setGridSize(QtCore.QSize(w, h))

    # ----- persistence -----
    def load_from_yaml(self) -> bool:
        """ Load YAML if present. Returns True if the YAML file existed and was parsed (even if it contained 0 components), else False if the file does not exist. """
        if not os.path.exists(self.yaml_file):
            return False
        try:
            with open(self.yaml_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            QMessageBox.critical(self, "Load YAML", f"Could not load '{self.yaml_file}': {e}")
            return False
        comps = data.get('components', [])
        self.populate_from_components(comps)
        return True  # file existed and was parsed, regardless of emptiness

    def is_empty(self) -> bool:
        """Return True if the dock list currently holds no items."""
        return self.list.count() == 0

    def save_to_yaml(self) -> None:
        comps = []
        for it in self._all_items_cache:
            d = it["data"]
            comps.append({
                "name": d.get("name") or d.get("code") or "",
                "pfd_avg": float(d.get("pfd", 0.0)),
                "pfh_avg": float(d.get("pfh", 0.0)),
                "sys_cap": d.get("syscap") or "",
                "pdm_code": d.get("pdm_code") or "",
            })
        payload = {"components": comps}
        try:
            with open(self.yaml_file, 'w', encoding='utf-8') as f:
                yaml.dump(payload, f, sort_keys=False, allow_unicode=True, Dumper=NumpySafeDumper)
        except Exception as e:
            QMessageBox.critical(self, "Save YAML", f"Could not save '{self.yaml_file}': {e}")

    def bootstrap_from_table(self, table_gather: List[Dict[str, Any]]) -> None:
        seen = set()
        comps = []
        for d in table_gather:
            key = d.get("name") or d.get("code")
            if not key or key in seen:
                continue
            seen.add(key)
            comps.append({
                "name": d.get("name") or d.get("code") or "",
                "pfd_avg": float(d.get("pfd", 0.0)),
                "pfh_avg": float(d.get("pfh", 0.0)),
                "sys_cap": d.get("syscap", ""),
                "pdm_code": d.get("pdm_code", ""),
            })
        self.populate_from_components(comps)
        self.save_to_yaml()


    # ---- populate/render (ersetzt die alte Darstellung, Logik bleibt) ----
    def populate_from_components(self, comps: List[dict]) -> None:
        self.items_data = comps or []
        self._all_items_cache.clear()
        self.list.clear()

        for comp in self.items_data:
            name   = str(comp.get('name', comp.get('code', '?')))
            pfd    = float(comp.get('pfd_avg', comp.get('pfd', 0.0)))
            pfh    = float(comp.get('pfh_avg', comp.get('pfh', 0.0)))
            syscap = comp.get('sys_cap', comp.get('syscap', ''))
            pdm    = comp.get('pdm_code', '')

            # 1) QListWidgetItem ohne sichtbaren Text (gegen Doppelanzeige)
            item = QListWidgetItem()
            
            item.setToolTip(make_html_tooltip(
                name, pfd, pfh, syscap,
                pdm_code=pdm,
                pfh_entered_fit=comp.get("pfh_fit"),
                pfd_entered_fit=comp.get("pfd_fit"),
                extra_fields=comp  # <- wichtig
            ))
            # 2) Alles, was wir brauchen, in UserRole ablegen

            payload = {
                **comp,                          # alle Original-Keys aus YAML
                "name": name,
                "code": name,
                "pfd": pfd if "pfd" not in comp and "pfd_avg" not in comp else comp.get("pfd", comp.get("pfd_avg", pfd)),
                "pfh": pfh if "pfh" not in comp and "pfh_avg" not in comp else comp.get("pfh", comp.get("pfh_avg", pfh)),
                "syscap": syscap if "syscap" in comp or "sys_cap" not in comp else comp.get("syscap", comp.get("sys_cap", syscap)),
                "pdm_code": pdm if "pdm_code" in comp else comp.get("pdm_code", pdm),
                "kind": self.kind,
            }

            item.setData(Qt.UserRole, payload)
            item.setData(Qt.DisplayRole, "")            # nichts zusätzlich zeichnen lassen
            item.setData(Qt.UserRole + 1, name)         # Sortier-/Filter-Schlüssel

            # 3) Card bauen + SizeHint setzen
            card = _LibCard(name, pfd, pfh, syscap, pdm, self.kind)
            item.setSizeHint(card.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, card)

            # 4) interner Cache für Filter
            self._all_items_cache.append({"name": name, "tooltip": item.toolTip(), "data": payload})

        # Nach DisplayRole-Entfernung: Sortierung über UserRole+1
        self.list.setSortingEnabled(True)
        try:
            self.list.model().setSortRole(Qt.UserRole + 1)
        except Exception:
            pass
        self.list.sortItems(Qt.AscendingOrder)

        self._update_count_label()
        QtCore.QTimer.singleShot(0, self.list.doItemsLayout)
        


    def _apply_filter(self, text: str):
        text = (text or "").lower().strip()
        self.list.clear()

        for it in self._all_items_cache:
            hay = f"{it['name']} {it['tooltip']}".lower()
            if text and text not in hay:
                continue

            item = QListWidgetItem()
            item.setToolTip(it["tooltip"])

            payload = it["data"]  # bereits korrekt strukturiert
            item.setData(Qt.UserRole, payload)
            item.setData(Qt.DisplayRole, "")
            item.setData(Qt.UserRole + 1, it["name"])

            card = _LibCard(
                it["name"],
                payload["pfd"],
                payload["pfh"],
                payload.get("syscap", ""),
                payload.get("pdm_code", ""),
                self.kind
            )
            item.setSizeHint(card.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, card)

        # Sortierung über den SortRole-Schlüssel
        self.list.setSortingEnabled(True)
        try:
            self.list.model().setSortRole(Qt.UserRole + 1)
        except Exception:
            pass
        self.list.sortItems(Qt.AscendingOrder)

        self._update_count_label()
        QtCore.QTimer.singleShot(0, self.list.doItemsLayout)


    def _on_double_clicked(self, item: QListWidgetItem):
        if not item or not self.on_add_requested:
            return
        data = item.data(Qt.UserRole) or {}
        self.on_add_requested(data)


    def add_component(self, d: Dict[str, Any]) -> None:
        name   = d.get("name") or d.get("code") or ""
        pfd    = float(d.get("pfd", 0.0))
        pfh    = float(d.get("pfh", 0.0))
        syscap = d.get("syscap", "")
        pdm    = d.get("pdm_code", "")
        pfh_fit = d.get("pfh_fit", None)
        pfd_fit = d.get("pfd_fit", None)

        item = QListWidgetItem()
        item.setToolTip(make_html_tooltip(
            name, pfd, pfh, syscap, pdm_code=pdm, pfh_entered_fit=pfh_fit, pfd_entered_fit=pfd_fit
        ))

        payload = {"name": name, "code": name, "pfd": pfd, "pfh": pfh, "syscap": syscap, "pdm_code": pdm, "kind": self.kind}
        if pfh_fit is not None: payload["pfh_fit"] = float(pfh_fit)
        if pfd_fit is not None: payload["pfd_fit"] = float(pfd_fit)

        item.setData(Qt.UserRole, payload)
        item.setData(Qt.DisplayRole, "")
        item.setData(Qt.UserRole + 1, name)

        card = _LibCard(name, pfd, pfh, syscap, pdm, self.kind)
        item.setSizeHint(card.sizeHint())
        self.list.addItem(item)
        self.list.setItemWidget(item, card)

        self._all_items_cache.append({"name": name, "tooltip": item.toolTip(), "data": payload})
        self.modified.emit()
        self.save_to_yaml()
        self._update_count_label()
        QtCore.QTimer.singleShot(0, self.list.doItemsLayout)

    def _update_count_label(self):
        self._header.count.setText(str(self.list.count()))



# ==========================
# Add SIFU dialog
# ==========================

class AddSifuDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add SIFU")
        form = QFormLayout(self)
        self.ed_name = QLineEdit()
        self.spin_sil = QSpinBox(); self.spin_sil.setRange(1, 4)
        self.combo_mode = QComboBox(); self.combo_mode.addItems(["High demand", "Low demand"])
        form.addRow("SIFU name", self.ed_name)
        form.addRow("Required SIL", self.spin_sil)
        form.addRow("Demand mode", self.combo_mode)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        form.addRow(btns)

    def get_values(self) -> RowMeta:
        sil_str = f"SIL {self.spin_sil.value()}"
        return RowMeta({
            "sifu_name": self.ed_name.text().strip() or "New SIFU",
            "sil_required": sil_str,
            "demand_mode_required": self.combo_mode.currentText(),
            "source": "user",
        })

# ==========================
# Edit SIFU dialog
# ==========================

class EditSifuDialog(QDialog):
    def __init__(self, meta: RowMeta, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit SIFU")
        form = QFormLayout(self)
        self.ed_name = QLineEdit(); self.ed_name.setText(str(meta.get("sifu_name", "SIFU")))
        self.spin_sil = QSpinBox(); self.spin_sil.setRange(1, 4)
        req_sil_str = str(meta.get("sil_required", "SIL 1"))
        _, sil_rank_int = normalize_required_sil(req_sil_str)
        self.spin_sil.setValue(int(sil_rank_int or 1))
        self.combo_mode = QComboBox(); self.combo_mode.addItems(["High demand", "Low demand"])
        self.combo_mode.setCurrentText(str(meta.get("demand_mode_required", "High demand")))
        form.addRow("SIFU name", self.ed_name)
        form.addRow("Required SIL", self.spin_sil)
        form.addRow("Demand mode", self.combo_mode)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def get_values(self) -> RowMeta:
        return RowMeta({
            "sifu_name": self.ed_name.text().strip() or "SIFU",
            "sil_required": f"SIL {self.spin_sil.value()}",
            "demand_mode_required": self.combo_mode.currentText(),
            "source": "user",
        })

# ==========================
# Add Component dialog (with units + FIT for PFH & PFD)
# ==========================

class AddComponentDialog(QDialog):
    def __init__(self, parent=None, pref_kind: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle("Add Component")
        form = QFormLayout(self)

        self.combo_kind = QComboBox(); self.combo_kind.addItems(["sensor", "logic", "actuator"])
        if pref_kind in ("sensor", "logic", "actuator"):
            self.combo_kind.setCurrentText(pref_kind)
        self.ed_name = QLineEdit()

        # PFD (dimensionless 0…1)
        self.spin_pfd = QDoubleSpinBox(); self.spin_pfd.setDecimals(8); self.spin_pfd.setRange(0.0, 1.0); self.spin_pfd.setValue(0.0)
        self.spin_pfd.setToolTip("PFDavg is dimensionless in range 0…1")

        # PFH with unit selector (1/h, FIT)
        self.spin_pfh = QDoubleSpinBox(); self.spin_pfh.setDecimals(12); self.spin_pfh.setRange(0, 1e12); self.spin_pfh.setValue(0.0)
        self.combo_pfh_unit = QComboBox(); self.combo_pfh_unit.addItems(["1/h", "FIT"])

        self.ed_syscap = QLineEdit()
        self.ed_pdm = QLineEdit()
        self.chk_insert = QtWidgets.QCheckBox("Also insert into current row")

        form.addRow("Type", self.combo_kind)
        form.addRow("Name/Code", self.ed_name)
        form.addRow("PFDavg (–)", self.spin_pfd)
        row_pfh = QHBoxLayout(); row_pfh.addWidget(self.spin_pfh); row_pfh.addWidget(self.combo_pfh_unit)
        w_pfh = QWidget(); w_pfh.setLayout(row_pfh)
        form.addRow("PFHavg", w_pfh)

        # live hint for PFH saving unit
        self.lbl_pfh_hint = QLabel(" ")
        form.addRow("", self.lbl_pfh_hint)
        form.addRow("SIL capability", self.ed_syscap)
        form.addRow("PDM code", self.ed_pdm)
        form.addRow(self.chk_insert)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        form.addRow(btns)

        def _update_pfh_hint():
            val = self.spin_pfh.value()
            unit = self.combo_pfh_unit.currentText()
            per_hour = val * 1e-9 if unit == "FIT" else val
            self.lbl_pfh_hint.setText(f"→ will be stored as {per_hour:.3e} 1/h")

        self.spin_pfh.valueChanged.connect(_update_pfh_hint)
        self.combo_pfh_unit.currentTextChanged.connect(lambda _: _update_pfh_hint())
        _update_pfh_hint()

    def get_values(self) -> Dict[str, Any]:
        pfh_val = float(self.spin_pfh.value())
        pfh_unit = self.combo_pfh_unit.currentText()
        pfh_per_hour = pfh_val * 1e-9 if pfh_unit == "FIT" else pfh_val
        pfd_val = float(self.spin_pfd.value())  # direct dimensionless
        out = {
            "kind": self.combo_kind.currentText(),
            "name": self.ed_name.text().strip() or "Component",
            "pfd": pfd_val,
            "pfh": float(pfh_per_hour),
            "syscap": self.ed_syscap.text().strip(),
            "pdm_code": self.ed_pdm.text().strip(),
            "insert": self.chk_insert.isChecked()
        }
        if pfh_unit == "FIT":
            out["pfh_fit"] = float(pfh_val)
        return out

# ==========================
# Main Window
# ==========================

class MainWindow(QMainWindow):
    def __init__(self, df):
        super().__init__()
        self.setWindowTitle("SIL Calculator")
        self.resize(1400, 840)
        self.df = df

        # --- assumptions (math unchanged) ---
        self.assumptions = {
            'TI': 8760.0,  # [h]
            'MTTR': 8.0,   # [h]
            'beta': 0.1,   # [–]
            'beta_D': 0.02,# [–]
        }
        self.du_dd_ratios = {'sensor': (0.7, 0.3), 'logic': (0.6, 0.4), 'actuator': (0.6, 0.4)}

        self.link_palette: List[Tuple[str, str]] = [
            ("#2E406E", "link0"),  # Deep Blue
            ("#D93673", "link1"),  # Dusty Pink
            ("#E06745", "link2"),  # Coral Red
            ("#8E6F6B", "link3"),  # Teal
            ("#8C6A10", "link4"),  # Deep Mustard
            ("#004D4D", "link5"),  # Dark Teal
            ("#4C5528", "link6"),  # Deep Olive
            ("#A44B38", "link7"),  # Burnt Terracotta
        ]
        self._link_color_tags: Dict[str, str] = {color.lower(): tag for color, tag in self.link_palette}
        self._link_selected_color: str = self._sanitize_link_color(self.link_palette[0][0]) or self.link_palette[0][0]
        self._link_color_menu: Optional[QtWidgets.QMenu] = None
        self._link_color_actions: List[QAction] = []
        self._link_color_action_group = QActionGroup(self)
        self._link_color_action_group.setExclusive(True)
        self._link_session_counters: Dict[str, int] = {}
        self._link_active = False
        self._link_active_row_uid: Optional[str] = None
        self._link_active_lane: Optional[str] = None
        self._link_active_lanes: Set[str] = set()
        self._link_active_list = None
        self._link_active_color: Optional[str] = None
        self._link_active_group_id: Optional[str] = None
        self._last_focused_list = None

        # --- per-row metadata store ---
        self.rows_meta: List[RowMeta] = []

        # --- toolbar ---
        #tb = QToolBar("Actions"); tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        #.addToolBar(tb)

        # --- view menu ---
        view_menu = self.menuBar().addMenu("View")

        toggle_sensor = QAction("Toggle Sensor Library", self)
        toggle_sensor.setCheckable(True)
        toggle_sensor.setChecked(True)
        toggle_sensor.triggered.connect(lambda checked: self.sensor_lib.setVisible(checked))
        view_menu.addAction(toggle_sensor)

        toggle_logic = QAction("Toggle Logic Library", self)
        toggle_logic.setCheckable(True)
        toggle_logic.setChecked(True)
        toggle_logic.triggered.connect(lambda checked: self.logic_lib.setVisible(checked))
        view_menu.addAction(toggle_logic)

        toggle_actuator = QAction("Toggle Actuator Library", self)
        toggle_actuator.setCheckable(True)
        toggle_actuator.setChecked(True)
        toggle_actuator.triggered.connect(lambda checked: self.act_lib.setVisible(checked))
        view_menu.addAction(toggle_actuator)

        tools_menu = self.menuBar().addMenu("Tools")
        self.link_mode_action = QAction("Component Link Mode", self)
        self.link_mode_action.setCheckable(True)
        self.link_mode_action.setShortcut("Ctrl+L")
        self.link_mode_action.setToolTip("Highlight related components within the active lane (Ctrl+L)")
        self.link_mode_action.triggered.connect(self._toggle_link_mode)
        tools_menu.addAction(self.link_mode_action)

        self._link_color_menu = tools_menu.addMenu("Link colour")
        self._link_color_menu.setToolTipsVisible(True)
        self._populate_link_color_menu()

        # New Project
        act_new = QAction("New Project", self)
        act_new.setShortcut("Ctrl+Shift+N")
        act_new.setToolTip("Clear current assignment (keep libraries) (Ctrl+Shift+N)")
        act_new.setIcon(self.style().standardIcon(QStyle.SP_FileIcon))
        act_new.triggered.connect(lambda: (getattr(self, "_action_new_project", None) or self._new_project_impl)())
        #tb.addAction(act_new)

        # Add SIFU
        act_add_sifu = QAction("Add SIFU", self)
        act_add_sifu.setShortcut("Ctrl+N")
        act_add_sifu.setToolTip("Add a new SIFU row (Ctrl+N)")
        act_add_sifu.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))
        act_add_sifu.triggered.connect(self._action_add_sifu)
        #tb.addAction(act_add_sifu)

        # Remove SIFU
        act_remove_sifu = QAction("Remove SIFU", self)
        act_remove_sifu.setShortcut("Ctrl+Del")
        act_remove_sifu.setToolTip("Remove selected SIFU (Ctrl+Del)")
        act_remove_sifu.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        act_remove_sifu.triggered.connect(self._action_remove_sifu)
        #tb.addAction(act_remove_sifu)

        # Edit SIFU
        act_edit_sifu = QAction("Edit SIFU", self)
        act_edit_sifu.setShortcut("Ctrl+E")
        act_edit_sifu.setToolTip("Edit SIFU parameters (Ctrl+E)")
        act_edit_sifu.setIcon(self.style().standardIcon(QStyle.SP_FileDialogListView))
        act_edit_sifu.triggered.connect(self._action_edit_sifu)
       #tb.addAction(act_edit_sifu)
        # Duplicate SIFU
        act_duplicate_sifu = QAction("Duplicate SIFU", self)
        act_duplicate_sifu.setShortcut("Ctrl+D")
        act_duplicate_sifu.setToolTip("Duplicate the selected SIFU (Ctrl+D)")
        act_duplicate_sifu.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))
        act_duplicate_sifu.triggered.connect(self._action_duplicate_sifu)
        #tb.addAction(act_duplicate_sifu)


        # also allow DEL key
        self._del_shortcut = QShortcut(QKeySequence(Qt.Key_Delete), self)
        self._del_shortcut.activated.connect(self._action_remove_sifu)

        # Add Component…
        act_add_comp = QAction("Add Component…", self)
        act_add_comp.setShortcut("Ctrl+Alt+N")
        act_add_comp.setToolTip("Add component to a library; optionally insert into current row (Ctrl+Alt+N)")
        act_add_comp.setIcon(self.style().standardIcon(QStyle.SP_FileDialogContentsView))
        act_add_comp.triggered.connect(self.open_add_component_dialog)
        #tb.addAction(act_add_comp)

        #tb.addSeparator()

        # Save / Load
        act_save_yaml = QAction("Save", self)
        act_save_yaml.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        act_save_yaml.setShortcut("Ctrl+S")
        act_save_yaml.setToolTip("Save current assignment as YAML (Ctrl+S)")
        act_save_yaml.triggered.connect(self._action_export_yaml)
        #tb.addAction(act_save_yaml)

        act_load_yaml = QAction("Load", self)
        act_load_yaml.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
        act_load_yaml.setShortcut("Ctrl+O")
        act_load_yaml.setToolTip("Load assignment from YAML (Ctrl+O)")
        act_load_yaml.triggered.connect(self._action_import_yaml)
        #tb.addAction(act_load_yaml)

        # Config
        act_config = QAction("Configuration", self)
        act_config.setToolTip("Edit global parameters (Ctrl+,)")
        act_config.setShortcut("Ctrl+,")
        act_config.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        act_config.triggered.connect(self._open_config_dialog)
        #tb.addAction(act_config)
        # Export HTML report
        act_export_html = QAction("Export Report (HTML)", self)
        act_export_html.setIcon(self.style().standardIcon(QStyle.SP_ArrowRight))
        act_export_html.setShortcut("Ctrl+Shift+E")
        act_export_html.setToolTip("Export an HTML report for all SIFUs (Ctrl+Shift+E)")
        act_export_html.triggered.connect(self._action_export_html_report)
        #tb.addAction(act_export_html)


        # --- central widget + filter strip + table ---
        central = QWidget(self)
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(6)

        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(8, 6, 8, 0)
        filter_row.setSpacing(8)
        filter_label = QLabel("Filter")
        filter_label.setObjectName("SifuFilterLabel")
        filter_row.addWidget(filter_label)

        self.sifu_filter = QLineEdit()
        self.sifu_filter.setObjectName("SifuFilterEdit")
        self.sifu_filter.setPlaceholderText("Filter SIFUs (name, components, SIL…)")
        self.sifu_filter.setClearButtonEnabled(True)
        self.sifu_filter.setToolTip("Type to filter the SIFU table by name, demand mode or contained components")
        filter_row.addWidget(self.sifu_filter, 1)

        self.sifu_filter_info = QLabel("All SIFUs")
        self.sifu_filter_info.setObjectName("SifuFilterInfo")
        self.sifu_filter_info.setProperty("filtered", False)
        self.sifu_filter_info.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        filter_row.addWidget(self.sifu_filter_info)

        central_layout.addLayout(filter_row)

        self.table = QTableWidget(0, 4, central)
        self.table.setHorizontalHeaderLabels(["Sensor / Input", "Logic", "Output / Actuator", "Result"])

        # Header-Resize-Modi: Result (3) kompakt, 0..2 interaktiv
        hdr = self.table.horizontalHeader()
        hdr.setSectionsMovable(False)  # Reihenfolge fixieren, Result bleibt rechts
        hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        # Ensure the table occupies the central area (prevents docks from filling the whole window)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        central_layout.addWidget(self.table, 1)
        self.setCentralWidget(central)

        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._open_table_ctx_menu)
        # Kontextmenü für den vertikalen Header (Zeilenköpfe)
        vh = self.table.verticalHeader()
        vh.setContextMenuPolicy(Qt.CustomContextMenu)
        vh.customContextMenuRequested.connect(self._open_header_ctx_menu)

        # Filter helper: delayed updates to keep UI responsive while typing
        self._filter_timer = QtCore.QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(120)
        self._filter_timer.timeout.connect(self._reapply_sifu_filter)
        self.sifu_filter.textChanged.connect(self._schedule_filter_update)
        self.sifu_filter.returnPressed.connect(self._reapply_sifu_filter)

        self._filter_focus_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._filter_focus_shortcut.setContext(Qt.ApplicationShortcut)
        self._filter_focus_shortcut.activated.connect(self._focus_sifu_filter)

        self._filter_clear_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self.sifu_filter)
        self._filter_clear_shortcut.setContext(Qt.WidgetShortcut)
        self._filter_clear_shortcut.activated.connect(self.sifu_filter.clear)

        # --- docks: libraries ---
        self.logic_lib  = ComponentLibraryDock("Logic Library",  "logic",   os.path.join(os.getcwd(), "logic_library.yaml"),    self)
        self.sensor_lib = ComponentLibraryDock("Sensor Library", "sensor",  os.path.join(os.getcwd(), "sensor_library.yaml"),   self)
        self.act_lib    = ComponentLibraryDock("Actuator Library","actuator",os.path.join(os.getcwd(), "actuator_library.yaml"),self)

        self.addDockWidget(Qt.RightDockWidgetArea, self.logic_lib)
        self.addDockWidget(Qt.RightDockWidgetArea, self.sensor_lib)
        self.addDockWidget(Qt.RightDockWidgetArea, self.act_lib)
        # Keep docks on right side and show them as tabs rather than stacked columns
        for dock in (self.logic_lib, self.sensor_lib, self.act_lib):
            dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        try:
            self.tabifyDockWidget(self.logic_lib, self.sensor_lib)
            self.tabifyDockWidget(self.logic_lib, self.act_lib)
            self.logic_lib.raise_()
        except Exception:
            pass


        self.logic_lib.on_add_requested  = self._add_logic_to_current_row
        self.sensor_lib.on_add_requested = self._add_sensor_to_current_row
        self.act_lib.on_add_requested    = self._add_actuator_to_current_row

        self.logic_lib.modified.connect(self.logic_lib.save_to_yaml)
        self.sensor_lib.modified.connect(self.sensor_lib.save_to_yaml)
        self.act_lib.modified.connect(self.act_lib.save_to_yaml)

        logic_loaded  = self.logic_lib.load_from_yaml()
        sensor_loaded = self.sensor_lib.load_from_yaml()
        act_loaded    = self.act_lib.load_from_yaml()

        # Build initial rows from DataFrame
        self.sifu_widgets: Dict[int, SifuRowWidgets] = {}
        self._populate_from_dataframe()

        # If YAML files are missing, bootstrap (existing code)
        if not sensor_loaded:
            self.sensor_lib.bootstrap_from_table(self._gather_table_content_for_kind("sensor"))
        if not logic_loaded:
            self.logic_lib.bootstrap_from_table(self._gather_table_content_for_kind("logic"))
        if not act_loaded:
            self.act_lib.bootstrap_from_table(self._gather_table_content_for_kind("actuator"))

        # If any library present but EMPTY, bootstrap from table as well
        if self.sensor_lib.is_empty():
            self.sensor_lib.bootstrap_from_table(self._gather_table_content_for_kind("sensor"))
        if self.logic_lib.is_empty():
            self.logic_lib.bootstrap_from_table(self._gather_table_content_for_kind("logic"))
        if self.act_lib.is_empty():
            self.act_lib.bootstrap_from_table(self._gather_table_content_for_kind("actuator"))

        # Prefill logic (first 3) if empty
        self._prefill_logic_from_library(count=3)

        self.table.resizeColumnsToContents()
        # WICHTIG: letzte Spalte nicht strecken
        self.table.horizontalHeader().setStretchLastSection(False)

        # initial calc & row height
        self.recalculate_all()
        self._reseed_link_counters()

        # theme
        self._apply_qss_theme()  # Light only per preference

        # settings
        self.settings = QtCore.QSettings("YourOrg", "SIFU-GUI")
        self._restore_settings()

        # --- one-time autosize if no saved widths
        try:
            saved_widths = self.settings.value("table/col_widths", [])
        except Exception:
            saved_widths = []
        have_saved = isinstance(saved_widths, list) and len(saved_widths) == self.table.columnCount()
        total_saved = sum(int(w) for w in saved_widths) if have_saved else 0
        if not have_saved or total_saved < 200:
            QtCore.QTimer.singleShot(0, self._autosize_columns_initial)
        else:
            self._columns_sized_once = True

        # finale Layout-Sanitisierung (immer)
        QtCore.QTimer.singleShot(0, self._finalize_layout)

        # Make sure a status bar exists
        self.statusBar().showMessage("Ready", 3000)

    def _open_table_ctx_menu(self, pos: QtCore.QPoint):
        # Position -> Tabellenindex
        idx = self.table.indexAt(pos)
        row = idx.row() if idx.isValid() else self._current_row_index()
        if row < 0 or row >= self.table.rowCount():
            return  # kein gültiger Treffer

        # Zur Sicherheit die Zeile selektieren
        self.table.setCurrentCell(row, max(0, self.table.currentColumn()))

        m = QtWidgets.QMenu(self)

        act_edit = m.addAction("Edit SIFU")
        act_dup  = m.addAction("Duplicate SIFU")
        m.addSeparator()
        act_del  = m.addAction("Remove SIFU")

        action = m.exec_(self.table.viewport().mapToGlobal(pos))
        if not action:
            return

        if action == act_edit:
            self._edit_sifu_at_row(row)          # gibt's bereits
        elif action == act_dup:
            self._duplicate_sifu_at_row(row)     # siehe 4) kleine Hilfsfunktion
        elif action == act_del:
            # vorhandene Löschlogik nutzt currentRow; daher kurz setzen:
            self.table.setCurrentCell(row, 0)
            self._action_remove_sifu()

    def _open_header_ctx_menu(self, pos: QtCore.QPoint):
        """Rechtsklick-Kontextmenü auf der vertikalen Kopfzeile (SIFU-Zeilenheader)."""
        vh = self.table.verticalHeader()
        logical_row = vh.logicalIndexAt(pos)
        if logical_row < 0 or logical_row >= self.table.rowCount():
            return

        # Zeile selektieren, damit die bestehenden Actions den aktuellen Kontext haben
        self.table.setCurrentCell(logical_row, max(0, self.table.currentColumn()))

        m = QtWidgets.QMenu(self)
        act_edit = m.addAction("Edit SIFU")
        act_dup  = m.addAction("Duplicate SIFU")
        m.addSeparator()
        act_del  = m.addAction("Remove SIFU")

        action = m.exec_(vh.mapToGlobal(pos))
        if not action:
            return

        if action == act_edit:
            self._edit_sifu_at_row(logical_row)
        elif action == act_dup:
            self._duplicate_sifu_at_row(logical_row)
        elif action == act_del:
            self.table.setCurrentCell(logical_row, 0)  # damit _action_remove_sifu() auf currentRow arbeitet
            self._action_remove_sifu()


    def _duplicate_sifu_at_row(self, row: int):
        # Temporär den aktuellen Row-Zeiger setzen & bestehende Action nutzen
        if row < 0 or row >= self.table.rowCount():
            return
        self.table.setCurrentCell(row, max(0, self.table.currentColumn()))
        self._action_duplicate_sifu()



    # ----- settings -----
    def _restore_settings(self):
        geo = self.settings.value("win/geo", type=QtCore.QByteArray)
        state = self.settings.value("win/state", type=QtCore.QByteArray)
        if geo:
            self.restoreGeometry(geo)
        if state:
            self.restoreState(state)
        widths = self.settings.value("table/col_widths", [])
        if isinstance(widths, list) and len(widths) == 4:
            for i, w in enumerate(widths):
                try:
                    self.table.setColumnWidth(i, int(w))
                except Exception:
                    pass
        filter_text = self.settings.value("ui/sifu_filter", "", type=str)
        if isinstance(filter_text, str):
            block = self.sifu_filter.blockSignals(True)
            self.sifu_filter.setText(filter_text)
            self.sifu_filter.blockSignals(block)
            self._apply_sifu_filter(filter_text)
        else:
            self._apply_sifu_filter("")

    def closeEvent(self, e):
        self.settings.setValue("win/geo", self.saveGeometry())
        self.settings.setValue("win/state", self.saveState())
        widths = [self.table.columnWidth(i) for i in range(self.table.columnCount())]
        self.settings.setValue("table/col_widths", widths)
        if hasattr(self, "sifu_filter"):
            self.settings.setValue("ui/sifu_filter", self.sifu_filter.text())
        super().closeEvent(e)

        # ----- QSS theme (Light) -----
    def _apply_qss_theme(self):
        primary = "#3B82F6"; success = "#1B7F3A"; danger = "#B42318"
        bg0 = "#FFFFFF"; bg1 = "#F7F8FA"; border = "#DADCE0"
        sensor_accent = "#0EA5E9"; logic_accent = "#22C55E"; actuator_accent= "#A855F7"
        link_styles = """
        QLabel#ChipLinkDot {
            min-width: 10px;
            max-width: 10px;
            min-height: 10px;
            max-height: 10px;
            border-radius: 5px;
            border:1px solid rgba(148,163,184,0.45);
            background: transparent;
        }
        """

        self.setStyleSheet(f"""
        * {{ font-size: 11px; }}
        QToolTip {{ font-size: 10px; }}

        /* Dialog/Tabs */
        #ModernConfigDialog {{
            background: {bg0};
        }}
        QDialog {{
            background: {bg0};
        }}
        QDialog QDialogButtonBox QPushButton {{
            padding: 6px 10px; border:1px solid #cfcfcf; border-radius:6px; background:{bg0};
        }}
        QDialog QDialogButtonBox QPushButton:focus {{
            border-color:{primary};
        }}
        QLabel#FormLabel {{ color:#222; }}
        QTabWidget::pane {{
            border:1px solid {border}; border-radius:10px; background:{bg0};
        }}
        QTabBar::tab {{
            padding:6px 10px; border:1px solid transparent; border-bottom:none; background:transparent; margin-right:6px;
        }}
        QTabBar::tab:selected {{
            border-color:{border}; border-top-left-radius:8px; border-top-right-radius:8px; background:{bg0};
        }}
        QGroupBox {{
            border:1px solid {border}; border-radius:8px; margin-top:10px; padding:6px 8px 8px 8px;
        }}

        /* Spinboxes, LineEdits */
        QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {{
            padding:4px 6px; border:1px solid #cfcfcf; border-radius:6px; background:{bg0};
        }}
        QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{
            border-color:{primary};
        }}
        QLineEdit#SifuFilterEdit {{
            padding:6px 8px;
        }}
        QLineEdit#SifuFilterEdit:focus {{
            border-color:{primary};
            box-shadow:0 0 0 1px rgba(59,130,246,0.15);
        }}
        QLabel#SifuFilterLabel {{
            color:#4b5563;
            font-weight:600;
        }}
        QLabel#SifuFilterInfo {{
            color:#6b7280;
            min-width:120px;
        }}
        QLabel#SifuFilterInfo[filtered="true"] {{
            color:{primary};
            font-weight:600;
        }}

        /* Dock Header */
        #DockHeader {{
            background: {bg1}; border-bottom:1px solid {border};
        }}
        #DockTitle {{ font-weight:600; color:#111; }}
        #DockSearch {{ min-width: 140px; }}
        #DockCount {{
            color:#555; border:1px solid {border}; background:#fff; border-radius:999px; padding:2px 8px;
        }}
        #DockAdd {{
            border:1px solid #cfcfcf; border-radius:6px; padding:4px 10px; background:{bg0};
        }}
        #DockAdd:hover {{ border-color:{primary}; color:{primary}; }}

        /* Library List + Cards */
        QListWidget#LibList {{
            background:{bg0}; border:1px solid {border}; border-radius:8px; padding:8px;
        }}
        QWidget#LibCard {{
            background:{bg1}; border:1px solid {border}; border-radius:10px;
        }}
        QWidget#LibCard[kind="sensor"] {{ border-left:4px solid {sensor_accent}; }}
        QWidget#LibCard[kind="logic"]  {{ border-left:4px solid {logic_accent}; }}
        QWidget#LibCard[kind="actuator"]{{ border-left:4px solid {actuator_accent}; }}
        QLabel#LibCardTitle {{ font-weight:600; color:#111; }}

        QLabel#Pill {{
            color:#374151; background:#fff; border:1px solid {border};
            border-radius:999px; padding:1px 8px; font-size:10px;
        }}

        /* Deine bestehenden Styles (gekürzt) */
        QTableWidget::item:selected {{ background: #E0ECFF; }}
        QListWidget {{ background: {bg1}; border: 1px solid {border}; border-radius: 8px; padding: 6px; }}
        QListWidget[dragTarget="true"] {{ border-color:{primary}; background:#EEF5FF; }}
        QWidget[kind] {{
            background:{bg0}; border:1px solid #d9d9d9; border-radius:12px;
        }}
{link_styles}
        QWidget[kind="sensor"] {{ border-left:4px solid {sensor_accent}; padding-left:8px; }}
        QWidget[kind="logic"] {{ border-left:4px solid {logic_accent}; padding-left:8px; }}
        QWidget[kind="actuator"] {{ border-left:4px solid {actuator_accent}; padding-left:8px; }}

        QLabel#ResultSummary {{
            font-weight:700;
        }}

        QWidget#ResultCell {{
            background: transparent;
        }}

        QFrame#ResultCard {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {bg0}, stop:1 {bg1});
            border: 1px solid {border};
            border-radius: 18px;
        }}

        QFrame#ResultCard:hover {{
            border-color: {primary};
        }}

        QLabel#ResultCaption {{
            font-size: 12px;
            font-weight: 600;
            color: #4b5563;
        }}

        QLabel#ResultValue {{
            font-size: 12px;
            font-weight: 600;
            color: #111827;
        }}

        QLabel#ResultValue[variant="metric"] {{
            font-family: "Source Code Pro", "Fira Code", monospace;
            font-size: 12px;
            font-weight: 600;
            color: #1f2937;
        }}

        QComboBox#DemandCombo {{
            padding: 1px 10px;
            border: 1px solid #cfcfcf;
            border-radius: 8px;
            background: {bg0};
            font-weight: 600;
        }}
        QComboBox#DemandCombo:focus {{ border-color: {primary}; }}
        """)


    # ----- dataframe → rows -----
    def _populate_from_dataframe(self):
        rows = len(self.df)
        self.table.setRowCount(rows)
        self.rows_meta.clear()

        for row_idx, sifu in enumerate(self.df.itertuples(index=False)):
            req_sil_str, _ = normalize_required_sil(getattr(sifu, 'sil_required', 'n.a.'))
            req_mode = getattr(sifu, 'demand_mode_required', 'High demand')
            meta = RowMeta({
                "sifu_name": sifu.sifu_name,
                "sil_required": req_sil_str,
                "demand_mode_required": req_mode,
                "source": "df"
            })
            self.rows_meta.append(meta)
            self._ensure_row_uid(meta)

            header = f"{meta['sifu_name']} \nRequired {meta['sil_required']} \n{meta['demand_mode_ required'] if 'demand_mode_ required' in meta else meta['demand_mode_required']}"
            # Fix whitespace key if any
            header = header.replace("demand_mode_ required", "demand_mode_required")
            self.table.setVerticalHeaderItem(row_idx, QTableWidgetItem(header))

            widgets = SifuRowWidgets()
            self.sifu_widgets[row_idx] = widgets

            widgets.result.combo.setCurrentText(meta['demand_mode_required'])
            widgets.result.override_changed.connect(lambda val, r=row_idx: self._on_row_override_changed(r, val))

            self.table.setCellWidget(row_idx, 0, widgets.in_list)
            self.table.setCellWidget(row_idx, 1, widgets.logic_list)
            self.table.setCellWidget(row_idx, 2, widgets.out_list)
            self.table.setCellWidget(row_idx, 3, widgets.result)

            self.table.resizeColumnsToContents()
            self.table.setCurrentCell(0, 3)

            # sensors
            for sensor in getattr(sifu, 'sensors', []):
                title = sensor.pid_code or sensor.bmk_code or "?"
                item = self._make_item(title, sensor.pfd_avg, sensor.pfh_avg, sensor.sys_cap, sensor.pdm_code, kind="sensor")
                widgets.in_list.addItem(item)
                widgets.in_list.attach_chip(item)

            # actuators
            for act in getattr(sifu, 'actuators', []):
                title = act.pid_code or act.bmk_code or "?"
                item = self._make_item(title, act.pfd_avg, act.pfh_avg, act.sys_cap, act.pdm_code, kind="actuator")
                widgets.out_list.addItem(item)
                widgets.out_list.attach_chip(item)

            self._update_row_height(row_idx)

        if self.table.columnCount() == 4:
            self.table.setColumnWidth(0, 360)
            self.table.setColumnWidth(1, 300)
            self.table.setColumnWidth(2, 360)

    
    def _tooltip_for_1oo2(self, m1: dict, m2: dict, group: str = "actuator",
                          mode_key: str = "low_demand") -> str:
        members = [m for m in (m1, m2) if isinstance(m, dict)]
        assumptions = self._current_assumptions()
        du_ratio, dd_ratio = self._ratios(group)
        _, tooltip, _, errors, _ = self._group_metrics(
            members,
            du_ratio,
            dd_ratio,
            mode_key,
            assumptions,
        )
        for err in errors:
            self._handle_conversion_error(err)
        return tooltip

    def _refresh_group_tooltips_in_row(self, row_idx: int) -> None:
        """Update tooltips for all 1oo2 groups in Output/Actuator of the given row."""
        widgets = self.sifu_widgets.get(row_idx)
        if not widgets: return
        mode = self._effective_demand_mode(row_idx) if 0 <= row_idx < len(self.rows_meta) else ""
        mode_key = self._mode_key_from_value(mode)
        lw = widgets.out_list
        for i in range(lw.count()):
            item = lw.item(i)
            if not item: continue
            d = item.data(Qt.UserRole) or {}
            if d.get('group') and d.get('architecture') == '1oo2':
                members = d.get('members', [{}, {}])
                m1 = members[0] if len(members) > 0 else {}
                m2 = members[1] if len(members) > 1 else {}
                item.setToolTip(self._tooltip_for_1oo2(m1, m2, "actuator", mode_key))

    def _gather_table_content_for_kind(self, kind: str) -> List[Dict[str, Any]]:
        seen = set()
        gathered: List[Dict[str, Any]] = []
        for row_idx in range(self.table.rowCount()):
            lw = self.sifu_widgets[row_idx].in_list if kind == "sensor" else (
                self.sifu_widgets[row_idx].logic_list if kind == "logic" else self.sifu_widgets[row_idx].out_list
            )
            for i in range(lw.count()):
                d = lw.item(i).data(Qt.UserRole) or {}
                if d.get('group'):  # skip 1oo2 composites
                    continue
                name = d.get("name") or d.get("code")
                if not name or name in seen:
                    continue
                seen.add(name)
                gathered.append({
                    "name": name, "code": name, "pfd": float(d.get("pfd", 0.0)),
                    "pfh": float(d.get("pfh", 0.0)), "syscap": d.get("syscap", ""),
                    "pdm_code": d.get("pdm_code", "")
                })
        return gathered

    # ----- item factory -----
    def _make_item(self, title: str, pfd: float, pfh: float, syscap,
                pdm_code: str = "", kind: str = "",
                pfh_fit: Optional[float] = None,
                pfd_fit: Optional[float] = None,
                extra_fields: Optional[Dict[str, Any]] = None) -> QListWidgetItem:
        item = QListWidgetItem(title)
        item.setToolTip(make_html_tooltip(
            title, pfd, pfh, syscap,
            pdm_code=pdm_code,
            pfh_entered_fit=pfh_fit,
            pfd_entered_fit=pfd_fit,
            extra_fields=extra_fields  # <- NEU
        ))
        data = {
            "name": title,
            "code": title,
            "pfd": float(pfd),
            "pfh": float(pfh),
            "syscap": syscap,
            "pdm_code": pdm_code,
            "kind": kind
        }
        # Extra Felder in die UserRole-Daten übernehmen:
        if isinstance(extra_fields, dict):
            data.update({k: v for k, v in extra_fields.items() if k not in data})
        if pfh_fit is not None:
            data["pfh_fit"] = float(pfh_fit)
        if pfd_fit is not None:
            data["pfd_fit"] = float(pfd_fit)

        inst_id = data.get("instance_id")
        if not isinstance(inst_id, str) or not inst_id:
            inst_id = new_instance_id()
        data["instance_id"] = inst_id

        item.setData(Qt.UserRole, data)
        item.setSizeHint(QtCore.QSize(170, 38))
        return item


    # ----- prefill logic -----
    def _prefill_logic_from_library(self, count: int = 3) -> None:
        comps = getattr(self.logic_lib, 'items_data', []) or []
        if not comps: return
        to_add = comps[: max(0, count)]
        for row_idx in range(self.table.rowCount()):
            widgets = self.sifu_widgets.get(row_idx)
            if not widgets: continue
            if widgets.logic_list.count() > 0:
                continue
            for comp in to_add:
                name = str(comp.get('name', comp.get('code', 'Logic')))
                pfd = float(comp.get('pfd_avg', comp.get('pfd', 0.0)))
                pfh = float(comp.get('pfh_avg', comp.get('pfh', 0.0)))
                syscap = comp.get('sys_cap', comp.get('syscap', ''))
                item = self._make_item(name, pfd, pfh, syscap, kind="logic")
                widgets.logic_list.addItem(item)
                widgets.logic_list.attach_chip(item)
            self._update_row_height(row_idx)

    # ----- overrides -----
    def _on_row_override_changed(self, row_idx: int, value: str):
        if row_idx < 0 or row_idx >= len(self.rows_meta): return
        req = self.rows_meta[row_idx].get("demand_mode_required", "High demand")
        self.rows_meta[row_idx]["demand_mode_override"] = value if value != req else None
        self.recalculate_row(row_idx)

    # ----- add to current row -----
    def _current_row_index(self) -> int:
        row = self.table.currentRow()
        return row if row >= 0 else 0

    def _add_logic_to_current_row(self, data: dict):
        row = self._current_row_index()
        widgets = self.sifu_widgets.get(row); assert widgets
        name = data.get("name") or data.get("code") or "Logic"
        pfd = float(data.get("pfd", data.get("pfd_avg", 0.0)))
        pfh = float(data.get("pfh", data.get("pfh_avg", 0.0)))
        syscap = data.get("syscap", data.get("sys_cap", ""))
        pdm = data.get("pdm_code", "")
        pfh_fit = data.get("pfh_fit", None); pfd_fit = data.get("pfd_fit", None)

        item = self._make_item(
            str(name), pfd, pfh, syscap, pdm_code=pdm, kind="logic",
            pfh_fit=pfh_fit, pfd_fit=pfd_fit,
            extra_fields=data  # <- NEU
        )
        widgets.logic_list.addItem(item)
        widgets.logic_list.attach_chip(item)
        self.statusBar().showMessage(f"Added logic '{name}'", 1500)
        self.recalculate_row(row)

    def _add_sensor_to_current_row(self, data: dict):
        row = self._current_row_index()
        widgets = self.sifu_widgets.get(row); assert widgets
        name = data.get("name") or data.get("code") or "Sensor"
        pfd = float(data.get("pfd", data.get("pfd_avg", 0.0)))
        pfh = float(data.get("pfh", data.get("pfh_avg", 0.0)))
        syscap = data.get("syscap", data.get("sys_cap", ""))
        pdm = data.get("pdm_code", "")
        pfh_fit = data.get("pfh_fit", None); pfd_fit = data.get("pfd_fit", None)
        item = self._make_item(str(name), pfd, pfh, syscap, pdm, kind="sensor", pfh_fit=pfh_fit, pfd_fit=pfd_fit)
        widgets.in_list.addItem(item)
        widgets.in_list.attach_chip(item)
        self.statusBar().showMessage(f"Added sensor '{name}'", 1500)
        self.recalculate_row(row)

    def _add_actuator_to_current_row(self, data: dict):
        row = self._current_row_index()
        widgets = self.sifu_widgets.get(row); assert widgets
        name = data.get("name") or data.get("code") or "Actuator"
        pfd = float(data.get("pfd", data.get("pfd_avg", 0.0)))
        pfh = float(data.get("pfh", data.get("pfh_avg", 0.0)))
        syscap = data.get("syscap", data.get("sys_cap", ""))
        pdm = data.get("pdm_code", "")
        pfh_fit = data.get("pfh_fit", None); pfd_fit = data.get("pfd_fit", None)
        item = self._make_item(str(name), pfd, pfh, syscap, pdm, kind="actuator", pfh_fit=pfh_fit, pfd_fit=pfd_fit)
        widgets.out_list.addItem(item)
        widgets.out_list.attach_chip(item)
        self.statusBar().showMessage(f"Added actuator '{name}'", 1500)
        self.recalculate_row(row)

    # ----- configuration -----
    def _open_config_dialog(self):
        dlg = ConfigDialog(self.assumptions, self.du_dd_ratios, self)
        if dlg.exec_():
            vals, ratios = dlg.get_values()
            self.assumptions.update(vals)
            self.du_dd_ratios.update(ratios)
            self.statusBar().showMessage("Updated configuration", 1500)
            self.recalculate_all()

    # ----- export/import -----
    def _action_export_yaml(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export", "sifu_assignment.yaml", "YAML (*.yaml *.yml)")
        if not path: return
        try:
            payload = self._collect_assignment_payload()
            with open(path, 'w', encoding='utf-8') as f:
                yaml.dump(payload, f, sort_keys=False, allow_unicode=True, Dumper=NumpySafeDumper)
            QMessageBox.information(self, "Export", f"Exported to {path}.")
            self.statusBar().showMessage(f"Exported to {os.path.basename(path)}", 2000)
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    def _action_import_yaml(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import", "", "YAML (*.yaml *.yml)")
        if not path: return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            self._rebuild_from_payload(data)
            QMessageBox.information(self, "Import", f"Imported from {path}.")
            self.statusBar().showMessage(f"Imported {os.path.basename(path)}", 2000)
        except Exception as e:
            QMessageBox.critical(self, "Import failed", str(e))

    def _action_duplicate_sifu(self):
        """Duplicate the currently selected SIFU row (deep copy of UI content + meta)."""
        row = self._current_row_index()
        if row < 0 or row >= self.table.rowCount():
            QMessageBox.information(self, "Duplicate SIFU", "No SIFU row selected.")
            return

        # --- Quelle: Metadaten + Widgets ermitteln
        src_meta = self.rows_meta[row]
        src_widgets = self.sifu_widgets.get(row)
        if not src_widgets:
            QMessageBox.warning(self, "Duplicate SIFU", "Source row widgets not found.")
            return

        # --- Zielzeile ans Ende anfügen und Basis-Widgets anlegen
        new_meta = RowMeta(src_meta.copy())
        new_meta["sifu_name"] = f"{new_meta.get('sifu_name','SIFU')} (copy)"
        new_meta.pop("_uid", None)
        self._append_sifu_row(new_meta)
        new_row = self.table.rowCount() - 1
        dst_widgets = self.sifu_widgets.get(new_row)

        # --- Inhalte der drei Spalten kopieren
        def _clone_list(src_list, dst_list, group_kind: str):
            for i in range(src_list.count()):
                it = src_list.item(i)
                if not it:
                    continue
                payload = it.data(Qt.UserRole) or {}
                new_payload = self._clone_chip_data(payload, preserve_id=False)
                new_item = QListWidgetItem(it)
                new_item.setData(Qt.UserRole, new_payload)
                dst_list.addItem(new_item)
                dst_list.attach_chip(new_item)

        _clone_list(src_widgets.in_list,    dst_widgets.in_list,    "sensor")
        _clone_list(src_widgets.logic_list, dst_widgets.logic_list, "logic")
        _clone_list(src_widgets.out_list,   dst_widgets.out_list,   "actuator")

        # --- Höhe und Ergebnis neu berechnen
        self._update_row_height(new_row)
        self.recalculate_row(new_row)
        self._reseed_link_counters()
        self.statusBar().showMessage("SIFU duplicated", 2000)
        
    # ---- HTML Report Export -------------------------------------------------
    def _action_export_html_report(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export HTML Report",
            "sifu_report.html",
            "HTML (*.html)"
        )
        if not path:
            return
        try:
            html_doc = self._build_html_report()
            with open(path, 'w', encoding='utf-8') as f:
                f.write(html_doc)
            QMessageBox.information(self, "Export", f"HTML report written to {path}.")
            self.statusBar().showMessage(f"Exported HTML report to {os.path.basename(path)}", 3000)
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))

    def _ensure_row_uid(self, meta: RowMeta) -> str:
        uid = meta.get("_uid")
        if not uid:
            uid = f"sifu-{uuid.uuid4().hex}"
            meta["_uid"] = uid
        return uid

    def _row_index_from_uid(self, uid: str) -> int:
        for idx, meta in enumerate(self.rows_meta):
            if self._ensure_row_uid(meta) == uid:
                return idx
        return -1

    def _clone_chip_data(self, data: dict, preserve_id: bool = False) -> dict:
        new_data = copy.deepcopy(data) if data else {}
        if not preserve_id or not isinstance(new_data.get("instance_id"), str):
            new_data["instance_id"] = new_instance_id()
        if new_data.get("group") and isinstance(new_data.get("members"), list):
            members: List[dict] = []
            for member in new_data.get("members", []):
                if not isinstance(member, dict):
                    continue
                member_copy = copy.deepcopy(member)
                if not preserve_id or not isinstance(member_copy.get("instance_id"), str):
                    member_copy["instance_id"] = new_instance_id()
                members.append(member_copy)
            new_data["members"] = members
        if not preserve_id:
            new_data.pop("link_color", None)
            new_data.pop("link_group_id", None)
        return new_data

    def _tag_for_color(self, color: Optional[str]) -> Optional[str]:
        if not color:
            return None
        return self._link_color_tags.get(str(color).lower())

    def _row_uid_for_index(self, row_idx: int) -> Optional[str]:
        if 0 <= row_idx < len(self.rows_meta):
            return self._ensure_row_uid(self.rows_meta[row_idx])
        return None

    def _lane_name_for_column(self, column: int) -> Optional[str]:
        mapping = {0: "sensor", 1: "logic", 2: "actuator"}
        return mapping.get(column)

    def _list_for_lane(self, row_idx: int, lane: Optional[str]) -> Optional[ChipList]:
        widgets = self.sifu_widgets.get(row_idx)
        if not widgets or not lane:
            return None
        if lane == "sensor":
            return widgets.in_list
        if lane == "logic":
            return widgets.logic_list
        if lane == "actuator":
            return widgets.out_list
        return None

    def _row_lane_for_list(self, list_widget: Optional[ChipList]) -> Tuple[int, Optional[str]]:
        if list_widget is None:
            return -1, None
        for idx, widgets in self.sifu_widgets.items():
            if list_widget is widgets.in_list:
                return idx, "sensor"
            if list_widget is widgets.logic_list:
                return idx, "logic"
            if list_widget is widgets.out_list:
                return idx, "actuator"
        return -1, None

    @staticmethod
    def _sanitize_link_color(value: Optional[str]) -> Optional[str]:
        if not isinstance(value, str):
            return None
        candidate = value.strip()
        if not candidate:
            return None
        if re.fullmatch(r'#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})', candidate):
            # Normalise to lowercase hex for stable comparisons
            if len(candidate) == 4:  # short form like #abc
                # Expand to 6-digit for consistency
                r, g, b = candidate[1], candidate[2], candidate[3]
                candidate = f"#{r}{r}{g}{g}{b}{b}"
            return candidate.lower()
        return None

    @staticmethod
    def _normalize_link_group_id(group_id: Optional[str]) -> Optional[str]:
        if not isinstance(group_id, str):
            return None
        normalized = group_id.strip()
        if not normalized:
            return None
        parts = normalized.split(":")
        if len(parts) == 3 and parts[1] in {"sensor", "logic", "actuator"}:
            return f"{parts[0]}:{parts[2]}"
        return normalized

    @staticmethod
    def _group_id_for_color(row_uid: str, color: str) -> str:
        token = color.lower().lstrip('#') or color.lower()
        return f"{row_uid}:{token}"

    def _color_icon(self, color: str) -> QIcon:
        pix = QPixmap(16, 16)
        pix.fill(QColor(color))
        painter = QPainter(pix)
        pen = QPen(QColor(0, 0, 0, 80))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawRect(0, 0, pix.width() - 1, pix.height() - 1)
        painter.end()
        return QIcon(pix)

    def _populate_link_color_menu(self) -> None:
        if not self._link_color_menu:
            return
        self._link_color_menu.clear()
        for action in self._link_color_actions:
            self._link_color_action_group.removeAction(action)
        self._link_color_actions.clear()
        for color, tag in self.link_palette:
            sanitized = self._sanitize_link_color(color) or color
            title = f"{sanitized.upper()}"
            action = QAction(title, self)
            action.setCheckable(True)
            action.setData(sanitized)
            action.setIcon(self._color_icon(sanitized))
            action.setToolTip(f"Assign components to subgroup colour {sanitized.upper()}")
            action.triggered.connect(lambda checked, c=sanitized: self._apply_link_color_selection(c))
            self._link_color_action_group.addAction(action)
            self._link_color_actions.append(action)
            self._link_color_menu.addAction(action)
        self._link_color_menu.addSeparator()
        custom_action = QAction("Custom colour…", self)
        custom_action.setToolTip("Select any colour for link subgroups")
        custom_action.triggered.connect(self._choose_custom_link_color)
        self._link_color_menu.addAction(custom_action)
        self._update_link_color_checks()

    def _update_link_color_checks(self) -> None:
        target = (self._link_selected_color or "").lower()
        for action in self._link_color_actions:
            action.setChecked(str(action.data()).lower() == target)
        if self._link_color_menu and self._link_selected_color:
            self._link_color_menu.setTitle(f"Link colour ({self._link_selected_color.upper()})")

    def _apply_link_color_selection(self, color: str, announce: bool = True) -> None:
        sanitized = self._sanitize_link_color(color)
        if not sanitized:
            return
        self._link_selected_color = sanitized
        self._update_link_color_checks()
        message = None
        if self._link_active and self._link_active_row_uid:
            group_id = self._group_id_for_color(self._link_active_row_uid, sanitized)
            self._link_active_color = sanitized
            self._link_active_group_id = group_id
            message = f"Link colour changed to {sanitized}"
        else:
            message = f"Link colour set to {sanitized}"
        if announce and message:
            self.statusBar().showMessage(message, 2000)

    def _choose_custom_link_color(self) -> None:
        initial = QColor(self._link_selected_color)
        chosen = QColorDialog.getColor(initial, self, "Select link colour")
        if chosen.isValid():
            self._apply_link_color_selection(chosen.name(), announce=True)

    def _popup_link_color_menu(self, global_pos: QtCore.QPoint) -> None:
        if self._link_color_menu:
            self._link_color_menu.popup(global_pos)

    def _toggle_link_mode(self, checked: bool) -> None:
        if checked:
            if not self._sanitize_link_color(self._link_selected_color):
                self._apply_link_color_selection(self.link_palette[0][0], announce=False)
            target_list = self._last_focused_list
            row_idx, lane = self._row_lane_for_list(target_list)
            if lane is None or row_idx < 0:
                row_idx = self._current_row_index()
                lane = self._lane_name_for_column(self.table.currentColumn())
                target_list = self._list_for_lane(row_idx, lane)
            if lane is None or row_idx < 0 or target_list is None:
                self.link_mode_action.blockSignals(True)
                self.link_mode_action.setChecked(False)
                self.link_mode_action.blockSignals(False)
                self.statusBar().showMessage("Select a SIFU lane before enabling link mode", 3000)
                return
            self._activate_link_mode_for(row_idx, lane, target_list, restart=True)
        else:
            self._end_link_session()

    def _activate_link_mode_for(self, row_idx: int, lane: str, list_widget: Optional[ChipList], restart: bool = True) -> None:
        if list_widget is None or not lane or row_idx < 0:
            return
        row_uid = self._row_uid_for_index(row_idx)
        if not row_uid:
            return
        if self._link_active:
            same_row = self._link_active_row_uid == row_uid
            lane_known = lane in getattr(self, "_link_active_lanes", set())
            if same_row and lane_known and not restart:
                return
            self._end_link_session(silent=True, keep_action=True)
        self._begin_link_session(row_idx, row_uid, lane, list_widget)

    def _begin_link_session(self, row_idx: int, row_uid: str, lane: str, list_widget: ChipList) -> None:
        selected = self._sanitize_link_color(self._link_selected_color)
        if not selected:
            selected = self._sanitize_link_color(self.link_palette[0][0]) or self.link_palette[0][0]
            self._link_selected_color = selected
        self._link_selected_color = selected
        self._update_link_color_checks()
        group_id = self._group_id_for_color(row_uid, selected)
        color = selected

        self._link_active = True
        self._link_active_row_uid = row_uid
        self._link_active_lane = lane
        self._link_active_lanes = {lane}
        self._link_active_list = list_widget
        self._link_active_color = color
        self._link_active_group_id = group_id
        self._last_focused_list = list_widget

        if hasattr(self, "link_mode_action"):
            self.link_mode_action.blockSignals(True)
            self.link_mode_action.setChecked(True)
            self.link_mode_action.blockSignals(False)

        sifu_name = "SIFU"
        if 0 <= row_idx < len(self.rows_meta):
            sifu_name = self.rows_meta[row_idx].get("sifu_name", sifu_name)
        lane_label = {"sensor": "Sensors", "logic": "Logic", "actuators": "Outputs", "actuator": "Outputs"}.get(lane, lane)
        color_label = color.upper() if isinstance(color, str) else color
        self.statusBar().showMessage(f"Link mode active for {sifu_name} — {lane_label} (colour {color_label})", 4000)

    def _end_link_session(self, silent: bool = False, keep_action: bool = False) -> None:
        if not self._link_active:
            if hasattr(self, "link_mode_action") and not keep_action:
                self.link_mode_action.blockSignals(True)
                self.link_mode_action.setChecked(False)
                self.link_mode_action.blockSignals(False)
            return
        self._link_active = False
        self._link_active_row_uid = None
        self._link_active_lane = None
        self._link_active_lanes.clear()
        self._link_active_list = None
        self._link_active_color = None
        self._link_active_group_id = None
        if hasattr(self, "link_mode_action") and not keep_action:
            self.link_mode_action.blockSignals(True)
            self.link_mode_action.setChecked(False)
            self.link_mode_action.blockSignals(False)
        if not silent:
            self.statusBar().showMessage("Link mode stopped", 3000)

    def _is_link_active_for(self, row_idx: int, lane: Optional[str]) -> bool:
        if not self._link_active or lane is None:
            return False
        row_uid = self._row_uid_for_index(row_idx)
        return bool(
            row_uid
            and row_uid == self._link_active_row_uid
            and lane in self._link_active_lanes
        )

    def _handle_link_click(self, list_widget: ChipList, item: QListWidgetItem) -> None:
        if not self._link_active or not item:
            return
        row_idx, lane = self._row_lane_for_list(list_widget)
        row_uid = self._row_uid_for_index(row_idx)
        if row_uid != self._link_active_row_uid:
            self.statusBar().showMessage("Link mode is active for a different SIFU.", 3000)
            return
        if lane not in self._link_active_lanes:
            self._link_active_lanes.add(lane)
            self._link_active_lane = lane
            lane_label = {"sensor": "Sensors", "logic": "Logic", "actuator": "Outputs", "actuators": "Outputs"}.get(lane, lane)
            self.statusBar().showMessage(
                f"Link mode extended to {lane_label} lane", 2500
            )
        payload = item.data(Qt.UserRole) or {}
        updated = copy.deepcopy(payload)
        current_id = updated.get("link_group_id")
        changed = False
        if current_id == self._link_active_group_id:
            removed = False
            if updated.pop("link_color", None) is not None:
                removed = True
            if updated.pop("link_group_id", None) is not None:
                removed = True or removed
            if removed:
                item.setData(Qt.UserRole, updated)
                list_widget.refresh_chip(item)
                self.statusBar().showMessage("Component removed from link group", 2000)
                changed = True
        else:
            if self._link_active_color and self._link_active_row_uid:
                active_color = self._sanitize_link_color(self._link_active_color)
                if not active_color:
                    return
                group_id = self._group_id_for_color(self._link_active_row_uid, active_color)
                self._link_active_group_id = group_id
                updated["link_color"] = active_color
                updated["link_group_id"] = group_id
                item.setData(Qt.UserRole, updated)
                list_widget.refresh_chip(item)
                self.statusBar().showMessage("Component linked", 2000)
                changed = True

        if changed:
            self._reseed_link_counters()
            self.recalculate_row(row_idx)

    def _clear_lane_links(self, row_idx: int, lane: str, announce: bool = True) -> bool:
        list_widget = self._list_for_lane(row_idx, lane)
        if not list_widget:
            if announce:
                self.statusBar().showMessage("No lane available to clear", 2000)
            return False
        row_uid = self._row_uid_for_index(row_idx)
        if self._is_link_active_for(row_idx, lane):
            self._end_link_session(silent=True)
        changed = False
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            if not item:
                continue
            payload = item.data(Qt.UserRole) or {}
            updated = copy.deepcopy(payload)
            removed = False
            if updated.pop("link_color", None) is not None:
                removed = True
            if updated.pop("link_group_id", None) is not None:
                removed = True or removed
            if removed:
                item.setData(Qt.UserRole, updated)
                list_widget.refresh_chip(item)
                changed = True
        if row_uid:
            self._reseed_link_counters()
        if announce:
            if changed:
                self.statusBar().showMessage("Cleared link highlights for lane", 2000)
            else:
                self.statusBar().showMessage("No link highlights found for lane", 2000)
        return changed

    def _clear_sifu_links(self, row_idx: int) -> None:
        if row_idx < 0 or row_idx >= len(self.rows_meta):
            return
        any_cleared = False
        for lane in ("sensor", "logic", "actuator"):
            if self._clear_lane_links(row_idx, lane, announce=False):
                any_cleared = True
        row_uid = self._row_uid_for_index(row_idx)
        if row_uid:
            self._reseed_link_counters()
        if any_cleared:
            self.statusBar().showMessage("Cleared link highlights for SIFU", 2000)
        else:
            self.statusBar().showMessage("No link highlights found for SIFU", 2000)

    def _reseed_link_counters(self) -> None:
        counters: Dict[str, int] = {}
        for row_idx, meta in enumerate(self.rows_meta):
            row_uid = self._ensure_row_uid(meta)
            if not row_uid:
                continue
            widgets = self.sifu_widgets.get(row_idx)
            if not widgets:
                continue
            seen: Set[str] = set()
            for attr in ("in_list", "logic_list", "out_list"):
                lw = getattr(widgets, attr, None)
                if not lw:
                    continue
                for i in range(lw.count()):
                    item = lw.item(i)
                    if not item:
                        continue
                    payload = item.data(Qt.UserRole) or {}
                    color = self._sanitize_link_color(payload.get("link_color"))
                    if color:
                        group_id = self._group_id_for_color(row_uid, color)
                        if payload.get("link_group_id") != group_id or payload.get("link_color") != color:
                            updated = copy.deepcopy(payload)
                            updated["link_color"] = color
                            updated["link_group_id"] = group_id
                            item.setData(Qt.UserRole, updated)
                        seen.add(group_id)
                    else:
                        if payload.get("link_group_id"):
                            updated = copy.deepcopy(payload)
                            updated.pop("link_group_id", None)
                            item.setData(Qt.UserRole, updated)
            if seen:
                counters[row_uid] = len(seen)
        self._link_session_counters = counters

    def _create_group_item(self, entry: dict, kind: str) -> QListWidgetItem:
        members: List[dict] = []
        for member in entry.get('members', []):
            if not isinstance(member, dict):
                continue
            member_copy = copy.deepcopy(member)
            inst_id = member_copy.get('instance_id')
            if not isinstance(inst_id, str) or not inst_id:
                member_copy['instance_id'] = new_instance_id()
            members.append(member_copy)

        labels: List[str] = []
        for idx, member in enumerate(members):
            label = member.get('code') or member.get('name') or f"Member {idx + 1}"
            labels.append(str(label))
        if not labels:
            fallback = entry.get('code') or entry.get('name') or "1oo2 Group"
            labels.append(str(fallback))

        item = QListWidgetItem(" + ".join(labels[:2]))
        payload = {
            'group': True,
            'architecture': '1oo2',
            'members': members,
            'kind': kind,
            'instance_id': entry.get('instance_id', new_instance_id()),
        }
        color = self._sanitize_link_color(entry.get('link_color'))
        if color:
            payload['link_color'] = color
        group_id = self._normalize_link_group_id(entry.get('link_group_id'))
        if group_id:
            payload['link_group_id'] = group_id
        item.setData(Qt.UserRole, payload)

        try:
            m1 = members[0] if len(members) > 0 else {}
            m2 = members[1] if len(members) > 1 else {}
            tooltip = self._tooltip_for_1oo2(m1, m2, kind)
        except Exception:
            tooltip = None
        if tooltip:
            item.setToolTip(tooltip)
        return item

    def _build_html_report(self) -> str:
        '''Build a self-contained HTML report (print-friendly) with all SIFUs,
        their components, assumptions, DU/DD ratios and computed results.'''
        import html as _html
        from datetime import datetime as _dt
        dt = _dt.now().strftime('%Y-%m-%d %H:%M')

        def esc(x):
            return _html.escape('' if x is None else str(x))

        def sanitize_color(value: Any) -> Optional[str]:
            if not isinstance(value, str):
                return None
            candidate = value.strip()
            if re.fullmatch(r'#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})', candidate):
                return candidate
            return None

        def fmt_pfd(x):
            try:
                return f"{float(x):.6f}"
            except Exception:
                return "–"

        def fmt_pfh(x):
            try:
                return f"{float(x):.3e}"  # 1/h
            except Exception:
                return "–"

        def fmt_lambda(x):
            try:
                return f"{float(x):.3e}"  # 1/h
            except Exception:
                return "–"

        def fmt_fit(x):
            try:
                return f"{float(x) * 1e9:.2f}"
            except Exception:
                return "–"

        # Collect all data using existing helpers
        payload = {"sifus": []}
        lane_display_map = {
            'sensor': 'Sensors / Inputs',
            'logic': 'Logic',
            'actuator': 'Outputs / Actuators',
        }
        for row_idx in range(len(self.rows_meta)):
            meta = self.rows_meta[row_idx]
            widgets = self.sifu_widgets[row_idx]
            mode = self._effective_demand_mode(row_idx)
            mode_key = self._mode_key_from_value(mode)
            sensors = self._collect_list_items(widgets.in_list, 'sensor', mode_key)
            logic = self._collect_list_items(widgets.logic_list, 'logic', mode_key)
            outputs = self._collect_list_items(widgets.out_list, 'actuator', mode_key)
            pfd_sum, pfh_sum, subgroup_info = self._sum_lists(
                (widgets.in_list, widgets.logic_list, widgets.out_list),
                mode_key,
            )
            combined_groups: List[Dict[str, Any]] = []
            lane_residuals: List[Dict[str, Any]] = []
            breakdown_total: Dict[str, float] = {
                'pfd': float(pfd_sum),
                'pfh': float(pfh_sum),
                'lambda_du': 0.0,
                'lambda_dd': 0.0,
                'details': [],
            }
            if isinstance(subgroup_info, dict):
                combined_groups = copy.deepcopy(subgroup_info.get('combined', []) or [])
                lane_residuals = copy.deepcopy(subgroup_info.get('lane_residuals', []) or [])
                total_entry = subgroup_info.get('total')
                if isinstance(total_entry, dict):
                    breakdown_total = {
                        'pfd': float(total_entry.get('pfd', pfd_sum)),
                        'pfh': float(total_entry.get('pfh', pfh_sum)),
                        'lambda_du': float(total_entry.get('lambda_du', 0.0)),
                        'lambda_dd': float(total_entry.get('lambda_dd', 0.0)),
                        'details': copy.deepcopy(total_entry.get('details', [])),
                    }
            sil_calc = (
                classify_sil_from_pfh(pfh_sum)
                if mode_key == 'high_demand'
                else classify_sil_from_pfd(pfd_sum)
            )
            req_sil_str, req_rank_raw = normalize_required_sil(meta.get('sil_required', 'n.a.'))
            req_rank = int(req_rank_raw)
            calc_rank = sil_rank(sil_calc)
            ok = (calc_rank >= req_rank) and (calc_rank > 0)
            uid = self._ensure_row_uid(meta)
            row_pos = self._row_index_from_uid(uid)
            if row_pos < 0:
                print(f"[export] No table row found for uid {uid}", file=sys.stderr)
            payload["sifus"].append({
                "meta": meta,
                "sensors": sensors,
                "logic": logic,
                "actuators": outputs,
                "pfd_sum": float(pfd_sum),
                "pfh_sum": float(pfh_sum),
                "mode": mode,
                "mode_key": mode_key,
                "sil_calc": sil_calc,
                "ok": ok,
                "req_sil": req_sil_str,
                "uid": uid,
                "link_subgroups": combined_groups,
                "lane_residuals": lane_residuals,
                "breakdown_total": breakdown_total,
            })

        # Global assumptions and DU/DD ratios
        asm = self.assumptions
        ratios = self.du_dd_ratios

        # CSS (embedded, print-friendly)
        css = '''
        body { font: 14px/1.45 -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; color: #111; margin: 0; background: #fff; }
        .page { padding: 24px 28px 40px; }
        h1 { font-size: 22px; margin: 0 0 8px; }
        h2 { font-size: 18px; margin: 24px 0 8px; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; }
        h3 { font-size: 16px; margin: 18px 0 6px; }
        .meta { color: #4b5563; font-size: 13px; margin-bottom: 12px; }
        table { border-collapse: collapse; width: 100%; margin: 8px 0 16px; font-size: 13px; }
        th, td { border: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; vertical-align: top; }
        th { background: #f8fafc; font-weight: 600; }
        tbody tr:nth-child(even) { background:#f9fafb; }
        tbody tr:hover { background:#f1f5f9; }
        table.component-table { table-layout: fixed; }
        table.component-table col.col-code { width: 32%; }
        table.component-table col.col-pfd { width: 14%; }
        table.component-table col.col-pfh { width: 16%; }
        table.component-table col.col-fit { width: 14%; }
        table.component-table col.col-sil { width: 14%; }
        table.component-table col.col-pdm { width: 10%; }
        table.component-table tbody tr.group-row td { background:#eef2ff; font-weight:600; border-bottom:0; }
        table.component-table tbody tr.group-row:hover td { background:#e0e7ff; }
        table.component-table tbody tr.group-row td .group-label { display:flex; flex-wrap:wrap; align-items:center; gap:8px; }
        table.component-table tbody tr.group-row td .group-title { font-size:13px; }
        table.component-table tbody tr.group-member td { background:#f9f5ff; border-top:0; font-size:12px; }
        table.component-table tbody tr.group-member:hover td { background:#ede9fe; }
        table.component-table tbody tr.group-member td:first-child { padding-left:30px; position:relative; }
        table.component-table tbody tr.group-member td:first-child::before { content:'↳'; position:absolute; left:12px; top:50%; transform:translateY(-50%); color:#6366f1; font-size:12px; }
        table.component-table td.right, table.component-table th.right { font-variant-numeric: tabular-nums; white-space: nowrap; }
        .member-tag { display:inline-flex; align-items:center; padding:1px 6px; border-radius:999px; background:#ede9fe; color:#312e81; font-weight:600; }
        .member-caption { display:inline-flex; align-items:center; color:#6b7280; font-size:11px; margin-top:0; }
        .ok { color: #166534; font-weight: 600; }
        .bad { color: #b91c1c; font-weight: 600; }
        .pill { display:inline-flex; align-items:center; padding:2px 7px; border:1px solid #d1d5db; border-radius:999px; font-size:11px; font-weight:500; text-transform:uppercase; letter-spacing:0.04em; background:#f9fafb; color:#374151; }
        .pill.arch, .lane-pill.arch { background:#ede9fe; color:#312e81; border:1px solid #c4b5fd; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
        .card { border:1px solid #e5e7eb; border-radius:10px; padding:10px 12px; background:#fff; }
        .muted { color:#6b7280; }
        .small { font-size: 12px; }
        .code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
        .right { text-align:right; }
        .nowrap { white-space: nowrap; }
        .architecture { margin: 18px 0 24px; }
        .architecture { position: relative; }
        .arch-lanes-wrapper { position: relative; }
        .arch-link-layer { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 3; }
        .arch-lanes { position: relative; z-index: 1; display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }
        .lane { border:1px solid #e5e7eb; border-radius:12px; padding:12px 14px; background:#fff; box-shadow:0 6px 18px rgba(15,23,42,0.04); display:flex; flex-direction:column; }
        .lane-header { font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color:#1f2937; margin-bottom:10px; }
        .lane-cards { display:flex; flex-direction:column; gap:4px; }
        .lane-card { border:1px solid #e5e7eb; border-radius:10px; padding:8px 10px; background:#f9fafb; border-left:4px solid transparent; display:flex; flex-direction:column; gap:6px; }
        .lane-card.group { background:#f5f3ff; border-color:#c7d2fe; border-left-color:#6366f1; }
        .lane-card.empty { border-style: dashed; color:#9ca3af; background:#fff; border-left-color:transparent; }
        .lane--sensors .lane-card { border-left-color:#0EA5E9; }
        .lane--logic .lane-card { border-left-color:#22C55E; }
        .lane--actuators .lane-card { border-left-color:#A855F7; }
        .chip-link-dot { width:10px; height:10px; border-radius:999px; border:1px solid rgba(148,163,184,0.45); background:transparent; display:inline-flex; flex-shrink:0; }
        .lane-card-header { display:flex; align-items:center; justify-content:space-between; gap:8px; }
        .lane-title { display:flex; align-items:center; gap:6px; font-size:13px; font-weight:600; color:#111827; margin:0; }
        .lane-title-text { display:inline-flex; align-items:center; }
        .lane-subtitle { font-size:11px; color:#6b7280; margin:0; }
        .lane-metrics { display:flex; flex-wrap:wrap; gap:6px; font-size:11px; color:#374151; }
        .lane-metrics span { white-space:nowrap; padding:0 6px; border-radius:999px; background:#fff; border:1px solid #e5e7eb; }
        .lane-pill { display:inline-flex; align-items:center; padding:2px 6px; border-radius:999px; background:#e5e7eb; color:#374151; font-size:10px; letter-spacing:0.05em; text-transform:uppercase; }
        .lane-members { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:4px; }
        .lane-member { border:1px solid #d1d5db; border-radius:8px; padding:4px 6px; background:#fff; border-left:3px solid transparent; display:flex; flex-direction:column; gap:4px; }
        .lane--sensors .lane-member { border-left-color:#0EA5E9; }
        .lane--logic .lane-member { border-left-color:#22C55E; }
        .lane--actuators .lane-member { border-left-color:#A855F7; }
        .lane-member-title { display:flex; align-items:center; gap:6px; font-size:11px; color:#1f2937; font-weight:600; margin:0; }
        .lane-member-text { color:#1f2937; }
        .lane-member .lane-metrics { margin:0; gap:4px; font-size:10px; }
        .lane-member .lane-metrics span { background:#f8fafc; border:1px solid #e2e8f0; padding:0 5px; }
        .lane-group-meta { font-size:11px; color:#4b5563; }
        .lane-note { font-size:11px; color:#6b7280; margin-top:4px; }
        .component-label { display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
        .component-label-text { font-weight:600; color:#1f2937; }
        .link-subgroup-box { margin-top:16px; border:1px solid #e5e7eb; border-radius:12px; padding:12px 14px; background:#fff; box-shadow:0 6px 18px rgba(15,23,42,0.04); }
        .link-subgroup-heading { font-size:12px; letter-spacing:0.08em; text-transform:uppercase; color:#1f2937; margin:0 0 10px; }
        .link-subgroup-list { display:flex; flex-direction:column; gap:10px; }
        .link-subgroup-card { border:1px solid #e5e7eb; border-radius:10px; padding:10px 12px; background:#f9fafb; }
        .link-subgroup-header { display:flex; align-items:center; justify-content:space-between; gap:8px; }
        .link-subgroup-title { display:flex; align-items:center; gap:6px; font-size:13px; font-weight:600; }
        .pill.subgroup { background:#dbeafe; color:#1d4ed8; border:1px solid #bfdbfe; }
        .link-subgroup-color { width:14px; height:14px; border-radius:999px; border:1px solid rgba(17,24,39,0.18); }
        .link-subgroup-lanes { font-size:12px; color:#4b5563; }
        .link-subgroup-metrics { margin-top:6px; font-size:12px; color:#1f2937; font-variant-numeric:tabular-nums; }
        .link-subgroup-members { margin-top:8px; display:flex; flex-wrap:wrap; gap:6px; }
        .link-subgroup-member { display:inline-flex; align-items:center; gap:6px; padding:4px 8px; border-radius:999px; background:#ede9fe; color:#312e81; font-size:12px; }
        .link-subgroup-member .lane { color:#4338ca; font-size:11px; }
        .link-breakdown-box { margin-top:16px; border:1px solid #e5e7eb; border-radius:12px; padding:12px 14px; background:#fff; box-shadow:0 6px 18px rgba(15,23,42,0.04); }
        .link-breakdown-title { font-size:12px; letter-spacing:0.08em; text-transform:uppercase; color:#1f2937; margin:0 0 10px; }
        .link-breakdown-table { width:100%; border-collapse:collapse; font-size:12px; }
        .link-breakdown-table th, .link-breakdown-table td { padding:6px 8px; border:1px solid #e5e7eb; text-align:left; }
        .link-breakdown-table th.numeric, .link-breakdown-table td.numeric { text-align:right; font-variant-numeric:tabular-nums; }
        .link-breakdown-source { display:flex; align-items:center; gap:6px; }
        .link-breakdown-table tfoot td { font-weight:600; background:#f8fafc; }
        .link-breakdown-computation { display:flex; flex-direction:column; gap:6px; }
        .link-breakdown-computation-entry { display:flex; flex-direction:column; gap:3px; padding:4px 0; }
        .link-breakdown-computation-entry .label { font-weight:600; color:#111827; display:flex; align-items:center; gap:6px; font-size:12px; }
        .link-breakdown-computation-entry .label .lane { font-weight:500; color:#4b5563; font-size:11px; }
        .link-breakdown-computation-entry .formula { font-family:'Fira Mono','SFMono-Regular',Menlo,monospace; font-size:10px; color:#1f2937; }
        .formula-section { margin: 24px 0; }
        .formula-layout { display:flex; flex-wrap:wrap; gap:20px; align-items:stretch; }
        .formula-column { display:flex; flex-direction:column; gap:16px; }
        .formula-column--architecture { flex:1 1 340px; }
        .formula-column--supporting { flex:1 1 260px; }
        .formula-column--variables { flex:1 1 320px; min-width:280px; }
        .formula-panel { flex:0 0 auto; border:1px solid #e5e7eb; border-radius:10px; background:#fff; box-shadow:0 6px 16px rgba(15,23,42,0.05); display:flex; flex-direction:column; min-width:240px; }
        .formula-panel-header { padding:12px 16px; background:#f8fafc; color:#111827; font-weight:600; font-size:14px; border-bottom:1px solid #e5e7eb; }
        .formula-panel-body { padding:12px 16px 16px; display:flex; flex-direction:column; gap:14px; }
        .formula-box { border:1px solid #e5e7eb; border-radius:8px; background:#f9fafb; padding:12px 14px; }
        .formula-note { margin:6px 0 0; }
        .formula-table { width:100%; border-collapse:collapse; font-size:13px; }
        .formula-table th, .formula-table td { border:1px solid #e5e7eb; padding:6px 8px; text-align:left; }
        .formula-table th { background:#f8fafc; width:32%; }
        @media (max-width: 960px) {
            .formula-layout { flex-direction:column; }
            .formula-column--variables { min-width:0; }
        }
        @media (max-width: 720px) {
            .formula-panel { min-width:0; }
        }
        @media print { .page { padding: 0; } .no-print { display:none; } }
        '''

        def build_architecture_lanes(
            sensors: List[dict],
            logic: List[dict],
            actuators: List[dict],
            anchor_prefix: str = "",
        ) -> Tuple[str, List[Dict[str, Any]]]:
            stage_defs = [
                ("sensors", "Sensors / Inputs", sensors or []),
                ("logic", "Logic", logic or []),
                ("actuators", "Outputs / Actuators", actuators or []),
            ]

            stage_payload: List[Tuple[str, str, List[Dict[str, Any]]]] = []
            connector_targets: Dict[str, List[Dict[str, str]]] = {}

            safe_prefix = re.sub(r"[^a-zA-Z0-9_-]+", "-", anchor_prefix or "sifu").strip("-")
            if not safe_prefix:
                safe_prefix = "sifu"

            for stage_key, stage_title, entries in stage_defs:
                cards: List[Dict[str, Any]] = []
                for idx, entry in enumerate(entries):
                    architecture = entry.get("architecture")
                    base_label = entry.get("code") or entry.get("name") or f"{stage_title} {idx + 1}"
                    pfd_val = entry.get("pfd_avg", entry.get("pfd"))
                    pfh_val = entry.get("pfh_avg", entry.get("pfh"))
                    sil_val = entry.get("sys_cap", entry.get("syscap", ""))
                    pdm_val = entry.get("pdm_code", "")
                    color = sanitize_color(entry.get("link_color") or entry.get("color"))

                    note_text = self._note_for_provenance(entry.get("provenance"))

                    if architecture == "1oo2" and entry.get("members"):
                        members_payload: List[Dict[str, Any]] = []
                        member_codes: List[str] = []
                        for m_idx, member in enumerate(entry.get("members", [])):
                            if not isinstance(member, dict):
                                continue
                            member_label = member.get("code") or member.get("name") or f"Member {m_idx + 1}"
                            member_codes.append(member_label)
                            member_color = sanitize_color(member.get("link_color") or color)
                            members_payload.append({
                                "label": member_label,
                                "name": member.get("name"),
                                "pfd": member.get("pfd_avg", member.get("pfd")),
                                "pfh": member.get("pfh_avg", member.get("pfh")),
                                "sil": member.get("sys_cap", member.get("syscap", "")),
                                "pdm": member.get("pdm_code", ""),
                                "note": self._note_for_provenance(member.get("provenance")),
                                "color": member_color,
                            })
                        display_label = " ∥ ".join(c for c in member_codes if c) or base_label
                        subtitle = base_label if display_label != base_label else ""
                        cards.append({
                            "type": "group",
                            "label": display_label,
                            "subtitle": subtitle,
                            "architecture": architecture,
                            "pfd": pfd_val,
                            "pfh": pfh_val,
                            "sil": sil_val,
                            "pdm": pdm_val,
                            "members": members_payload,
                            "member_count": len(members_payload),
                            "note": note_text,
                            "color": color,
                        })
                    else:
                        subtitle = ""
                        name_val = entry.get("name")
                        if name_val and name_val != base_label:
                            subtitle = name_val
                        cards.append({
                            "type": "single",
                            "label": base_label,
                            "subtitle": subtitle,
                            "architecture": architecture,
                            "pfd": pfd_val,
                            "pfh": pfh_val,
                            "sil": sil_val,
                            "pdm": pdm_val,
                            "note": note_text,
                            "color": color,
                        })

                stage_payload.append((stage_key, stage_title, cards))

            if all(not cards for _, _, cards in stage_payload):
                return "", []

            def render_metrics(pfd, pfh, sil, pdm) -> str:
                bits: List[str] = []
                if pfd not in (None, ""):
                    bits.append(f"<span>PFDavg {fmt_pfd(pfd)}</span>")
                if pfh not in (None, ""):
                    bits.append(f"<span>PFHavg {fmt_pfh(pfh)}</span>")
                if sil:
                    bits.append(f"<span>SIL {esc(sil)}</span>")
                if pdm:
                    bits.append(f"<span>PDM {esc(pdm)}</span>")
                if not bits:
                    return ""
                return '<div class="lane-metrics">' + ''.join(bits) + '</div>'

            html_parts: List[str] = ['<div class="arch-lanes-wrapper">', '<div class="arch-lanes">']
            for stage_key, stage_title, cards in stage_payload:
                html_parts.append(f'<div class="lane lane--{stage_key}">')
                html_parts.append(f'<div class="lane-header">{esc(stage_title)}</div>')
                html_parts.append('<div class="lane-cards">')
                if not cards:
                    html_parts.append('<div class="lane-card empty">No components listed</div>')
                for idx, card in enumerate(cards):
                    classes = ["lane-card"]
                    if card["type"] == "group":
                        classes.append("group")
                    class_attr = " ".join(classes)
                    card_color = sanitize_color(card.get("color"))
                    card_anchor = f"{safe_prefix}-lane-{stage_key}-{idx + 1}"
                    attr_list = [f'class="{class_attr}"']
                    attr_list.append(f'id="{card_anchor}"')
                    attr_list.append(f'data-lane="{stage_key}"')
                    if card_color:
                        attr_list.append(f'data-link-color="{card_color}"')
                    attr_str = ' '.join(attr_list)
                    html_parts.append(f'<div {attr_str}>')
                    html_parts.append('<div class="lane-card-header">')
                    title_bits = ['<div class="lane-title">']
                    if card_color:
                        title_bits.append(f'<span class="chip-link-dot" style="background:{card_color};"></span>')
                    title_bits.append(f'<span class="lane-title-text">{esc(card["label"])}</span>')
                    title_bits.append('</div>')
                    html_parts.append(''.join(title_bits))
                    if card.get("architecture"):
                        html_parts.append(f'<span class="lane-pill arch">{esc(card["architecture"])}</span>')
                    html_parts.append('</div>')
                    subtitle_bits: List[str] = []
                    subtitle_text = card.get("subtitle")
                    if subtitle_text:
                        subtitle_bits.append(subtitle_text)
                    if card["type"] == "group":
                        count = card.get("member_count", len(card.get("members", [])))
                        if count:
                            comp_word = "components" if count != 1 else "component"
                            subtitle_bits.append(f"{count} redundant {comp_word}")
                    subtitle_render = ' • '.join(esc(bit) for bit in subtitle_bits if bit)
                    if subtitle_render:
                        html_parts.append(f'<div class="lane-subtitle">{subtitle_render}</div>')
                    metrics_html = render_metrics(card.get("pfd"), card.get("pfh"), card.get("sil"), card.get("pdm"))
                    if metrics_html:
                        html_parts.append(metrics_html)
                    if card.get("note"):
                        html_parts.append(f'<div class="lane-note">{esc(card.get("note"))}</div>')
                    is_oneoo2 = card.get("architecture") == "1oo2"
                    if card["type"] == "group":
                        members = card.get("members", [])
                        if members:
                            html_parts.append(f'<div class="lane-group-meta">Members ({len(members)})</div>')
                            html_parts.append('<div class="lane-members">')
                            if is_oneoo2 and card_color:
                                connector_targets.setdefault(card_color, []).append({
                                    "id": card_anchor,
                                    "lane": stage_key,
                                    "kind": "card",
                                })
                            for m_idx, member in enumerate(members, 1):
                                member_color = sanitize_color(member.get("color") or card_color)
                                member_anchor = f"{card_anchor}-member-{m_idx}" if member_color else None
                                member_attr: List[str] = ['class="lane-member"']
                                if member_anchor:
                                    member_attr.append(f'id="{member_anchor}"')
                                member_attr.append(f'data-lane="{stage_key}"')
                                if member_color:
                                    member_attr.append(f'data-link-color="{member_color}"')
                                    if not is_oneoo2:
                                        connector_targets.setdefault(member_color, []).append({
                                            "id": member_anchor,
                                            "lane": stage_key,
                                            "kind": "member",
                                        })
                                member_attr_str = ' '.join(member_attr)
                                html_parts.append(f'<div {member_attr_str}>')
                                member_title_bits = ['<div class="lane-member-title">']
                                if member_color:
                                    member_title_bits.append(
                                        f'<span class="chip-link-dot" style="background:{member_color};"></span>'
                                    )
                                member_title_bits.append(
                                    f'<span class="lane-member-text">{esc(member.get("label", "Member"))}</span>'
                                )
                                member_title_bits.append('</div>')
                                html_parts.append(''.join(member_title_bits))
                                member_metrics = render_metrics(member.get("pfd"), member.get("pfh"), member.get("sil"), member.get("pdm"))
                                if member_metrics:
                                    html_parts.append(member_metrics)
                                else:
                                    html_parts.append('<div class="lane-note">No reliability data</div>')
                                if member.get("note"):
                                    html_parts.append(f'<div class="lane-note">{esc(member.get("note"))}</div>')
                                html_parts.append('</div>')
                            html_parts.append('</div>')
                        else:
                            html_parts.append('<div class="lane-note">Group members unavailable</div>')
                    elif card_color:
                        connector_targets.setdefault(card_color, []).append({
                            "id": card_anchor,
                            "lane": stage_key,
                            "kind": "card",
                        })
                    html_parts.append('</div>')
                html_parts.append('</div>')
                html_parts.append('</div>')

            html_parts.append('</div>')
            html_parts.append('<svg class="arch-link-layer" aria-hidden="true"></svg>')
            html_parts.append('</div>')

            connector_payload: List[Dict[str, Any]] = []
            lane_sequence = ("sensors", "logic", "actuators")

            def pairwise_links(source_lane: str, target_lane: str, records: Dict[str, List[Dict[str, str]]]) -> List[Dict[str, Dict[str, str]]]:
                links: List[Dict[str, Dict[str, str]]] = []
                source_items = records.get(source_lane) or []
                target_items = records.get(target_lane) or []
                for src in source_items:
                    src_id = src.get("id")
                    if not src_id:
                        continue
                    for dst in target_items:
                        dst_id = dst.get("id")
                        if not dst_id or dst_id == src_id:
                            continue
                        links.append({
                            "start": {
                                "id": src_id,
                                "lane": source_lane,
                            },
                            "end": {
                                "id": dst_id,
                                "lane": target_lane,
                            },
                        })
                return links

            for color, anchors in connector_targets.items():
                if not color:
                    continue
                lanes_map: Dict[str, List[Dict[str, str]]] = {}
                for anchor in anchors:
                    lane_key = anchor.get("lane")
                    if lane_key not in lane_sequence:
                        continue
                    lanes_map.setdefault(lane_key, []).append(anchor)
                if len(lanes_map) < 2:
                    continue
                links: List[Dict[str, Dict[str, str]]] = []
                if lanes_map.get("sensors") and lanes_map.get("logic"):
                    links.extend(pairwise_links("sensors", "logic", lanes_map))
                if lanes_map.get("logic") and lanes_map.get("actuators"):
                    links.extend(pairwise_links("logic", "actuators", lanes_map))
                if not lanes_map.get("logic") and lanes_map.get("sensors") and lanes_map.get("actuators"):
                    links.extend(pairwise_links("sensors", "actuators", lanes_map))
                if not links:
                    continue
                connector_payload.append({
                    "color": color,
                    "links": links,
                })

            return ''.join(html_parts), connector_payload

        def render_link_subgroups(entries: Optional[List[Dict[str, Any]]]) -> str:
            if not entries:
                return ""

            cards: List[str] = []
            cards.append('<div class="link-subgroup-box">')
            cards.append('<div class="link-subgroup-heading">Link subgroups</div>')
            cards.append('<div class="link-subgroup-list">')
            has_card = False
            for idx, subgroup in enumerate(entries, 1):
                if not isinstance(subgroup, dict):
                    continue

                color = sanitize_color(subgroup.get('color'))
                lanes = subgroup.get('lanes')
                lanes_display = ''
                if isinstance(lanes, (list, tuple)) and lanes:
                    lanes_display = ', '.join(str(l) for l in lanes if l)

                metrics_bits: List[str] = []
                pfd_val = subgroup.get('pfd')
                if pfd_val not in (None, ''):
                    metrics_bits.append(f"PFDavg {fmt_pfd(pfd_val)}")
                pfh_val = subgroup.get('pfh')
                if pfh_val not in (None, ''):
                    metrics_bits.append(f"PFHavg {fmt_pfh(pfh_val)} 1/h")
                lambda_du_val = subgroup.get('lambda_du')
                if lambda_du_val not in (None, ''):
                    metrics_bits.append(f"λ_DU {fmt_lambda(lambda_du_val)} 1/h")
                lambda_dd_val = subgroup.get('lambda_dd')
                if lambda_dd_val not in (None, ''):
                    metrics_bits.append(f"λ_DD {fmt_lambda(lambda_dd_val)} 1/h")
                count_val = subgroup.get('count')
                if isinstance(count_val, int) and count_val > 0:
                    metrics_bits.append(f"{count_val} component{'s' if count_val != 1 else ''}")

                cards.append('<div class="link-subgroup-card">')
                has_card = True
                cards.append('<div class="link-subgroup-header">')
                title_parts = [f'<span class="pill subgroup">Subgroup {idx}</span>']
                if color:
                    title_parts.append(f'<span class="link-subgroup-color" style="background:{color};"></span>')
                cards.append(f"<div class=\"link-subgroup-title\">{''.join(title_parts)}</div>")
                if lanes_display:
                    cards.append(f'<div class="link-subgroup-lanes">Lanes: {esc(lanes_display)}</div>')
                else:
                    cards.append('<div class="link-subgroup-lanes muted">Lanes: —</div>')
                cards.append('</div>')

                if metrics_bits:
                    cards.append(f"<div class=\"link-subgroup-metrics\">{' | '.join(metrics_bits)}</div>")

                components = [comp for comp in subgroup.get('components', []) if isinstance(comp, dict)]
                if components:
                    cards.append('<div class="link-subgroup-members">')
                    for comp in components:
                        label_val = comp.get('label') or 'Component'
                        if comp.get('architecture') == '1oo2':
                            label_val = f"{label_val} (1oo2)"
                        lane_title = comp.get('lane_title') or lane_display_map.get(comp.get('lane'), comp.get('lane', ''))
                        lane_caption = esc(lane_title) if lane_title else ''
                        member_labels = [lbl for lbl in comp.get('member_labels', []) if lbl]
                        tooltip_attr = ''
                        if member_labels:
                            tooltip_attr = f' title="{esc("Members: " + ", ".join(member_labels))}"'
                        comp_color = sanitize_color(comp.get('color') or subgroup.get('color'))
                        cards.append(f'<div class="link-subgroup-member"{tooltip_attr}>')
                        if comp_color:
                            cards.append(f'<span class="chip-link-dot" style="background:{comp_color};"></span>')
                        cards.append(f'<span class="member-tag">{esc(label_val)}</span>')
                        if lane_caption:
                            cards.append(f'<span class="lane">{lane_caption}</span>')
                        cards.append('</div>')
                    cards.append('</div>')

                cards.append('</div>')

            cards.append('</div>')
            cards.append('</div>')
            if not has_card:
                return ""
            return ''.join(cards)

        def render_link_breakdown(
            total_entry: Optional[Dict[str, Any]],
            subgroups: Optional[List[Dict[str, Any]]],
            residuals: Optional[List[Dict[str, Any]]],
            mode_key: Optional[str],
            mode_text: Optional[str],
        ) -> str:
            normalized_key = self._mode_key_from_value(mode_key or mode_text)
            is_high = normalized_key == 'high_demand'
            mode_label = self._mode_label_from_key(normalized_key)

            def fmt_ratio(value: Optional[float]) -> str:
                try:
                    return f"{float(value) * 100.0:.1f}%"
                except Exception:
                    return "–"

            metric_header = 'PFHavg [1/h]' if is_high else 'PFDavg'
            metric_key = 'pfh' if is_high else 'pfd'
            metric_formatter = fmt_pfh if is_high else fmt_pfd

            def build_computation_cell(
                details: Optional[List[Dict[str, Any]]],
                fallback_color: Optional[str] = None,
            ) -> str:
                if not isinstance(details, (list, tuple)):
                    return '—'

                entry_parts: List[str] = []
                for detail in details:
                    if not isinstance(detail, dict):
                        continue

                    lambda_total_txt = fmt_lambda(detail.get('lambda_total'))
                    lambda_du_txt = fmt_lambda(detail.get('lambda_du'))
                    ratio_du_txt = fmt_ratio(detail.get('ratio_du'))

                    formula_bits: List[str] = []
                    if (
                        lambda_total_txt != '–'
                        and ratio_du_txt != '–'
                        and lambda_du_txt != '–'
                    ):
                        formula_bits.append(
                            f'λ_total {lambda_total_txt} × r_DU {ratio_du_txt} → λ_DU {lambda_du_txt} 1/h'
                        )
                    if not formula_bits:
                        continue

                    label_val = esc(detail.get('label') or 'Component')
                    lane_title = detail.get('lane_title') or ''
                    lane_html = f'<span class="lane">{esc(lane_title)}</span>' if lane_title else ''
                    members = detail.get('member_labels')
                    tooltip_attr = ''
                    if isinstance(members, (list, tuple)) and members:
                        tooltip_attr = (
                            ' title="'
                            + esc('Members: ' + ', '.join(str(lbl) for lbl in members if lbl))
                            + '"'
                        )
                    dot_color = sanitize_color(detail.get('color') or fallback_color)

                    entry_html: List[str] = ['<div class="link-breakdown-computation-entry">']
                    entry_html.append('<div class="label"' + tooltip_attr + '>')
                    if dot_color:
                        entry_html.append(
                            f'<span class="chip-link-dot" style="background:{dot_color};"></span>'
                        )
                    entry_html.append(f'<span>{label_val}</span>')
                    if lane_html:
                        entry_html.append(lane_html)
                    entry_html.append('</div>')
                    for formula in formula_bits:
                        entry_html.append(f'<div class="formula">{formula}</div>')
                    entry_html.append('</div>')
                    entry_parts.append(''.join(entry_html))

                if not entry_parts:
                    return '—'
                return '<div class="link-breakdown-computation">' + ''.join(entry_parts) + '</div>'

            rows: List[str] = []
            has_rows = False

            if subgroups:
                for idx, subgroup in enumerate(subgroups, 1):
                    if not isinstance(subgroup, dict):
                        continue
                    color = sanitize_color(subgroup.get('color'))
                    lanes = subgroup.get('lanes')
                    if isinstance(lanes, (list, tuple)) and lanes:
                        lanes_display = ', '.join(str(l) for l in lanes if l)
                    else:
                        lanes_display = '—'
                    source_bits = ['<div class="link-breakdown-source">']
                    if color:
                        source_bits.append(
                            f'<span class="chip-link-dot" style="background:{color};"></span>'
                        )
                    source_bits.append(f'<span>Subgroup {idx}</span>')
                    source_bits.append('</div>')
                    computation_html = build_computation_cell(subgroup.get('details'), color)
                    rows.append(
                        '<tr>'
                        f'<td>{"".join(source_bits)}</td>'
                        f'<td>{esc(lanes_display)}</td>'
                        f'<td>{computation_html}</td>'
                        f'<td class="numeric">{metric_formatter(subgroup.get(metric_key))}</td>'
                        f'<td class="numeric">{fmt_lambda(subgroup.get("lambda_du"))}</td>'
                        f'<td class="numeric">{fmt_lambda(subgroup.get("lambda_dd"))}</td>'
                        '</tr>'
                    )
                    has_rows = True

            if residuals:
                for entry in residuals:
                    if not isinstance(entry, dict):
                        continue
                    lane_title = entry.get('lane_title') or entry.get('lane') or '—'
                    lane_display = lane_title or '—'
                    source_html = (
                        '<div class="link-breakdown-source">'
                        f'<span>{esc(lane_title)} (ungrouped)</span>'
                        '</div>'
                    )
                    computation_html = build_computation_cell(entry.get('details'))
                    rows.append(
                        '<tr>'
                        f'<td>{source_html}</td>'
                        f'<td>{esc(lane_display)}</td>'
                        f'<td>{computation_html}</td>'
                        f'<td class="numeric">{metric_formatter(entry.get(metric_key))}</td>'
                        f'<td class="numeric">{fmt_lambda(entry.get("lambda_du"))}</td>'
                        f'<td class="numeric">{fmt_lambda(entry.get("lambda_dd"))}</td>'
                        '</tr>'
                    )
                    has_rows = True

            if not has_rows:
                return ""

            total_entry = total_entry or {}
            total_metric_txt = metric_formatter(total_entry.get(metric_key))
            total_lambda_du_txt = fmt_lambda(total_entry.get('lambda_du'))
            total_lambda_dd_txt = fmt_lambda(total_entry.get('lambda_dd'))

            parts_box = ['<div class="link-breakdown-box">']
            parts_box.append(
                f'<div class="link-breakdown-title">Total composition — {mode_label}</div>'
            )
            parts_box.append('<table class="link-breakdown-table">')
            parts_box.append(
                '<thead><tr>'
                '<th>Source</th><th>Lanes</th><th>Computation</th>'
                f'<th class="numeric">{metric_header}</th>'
                '<th class="numeric">λ_DU [1/h]</th><th class="numeric">λ_DD [1/h]</th>'
                '</tr></thead>'
            )
            parts_box.append('<tbody>')
            parts_box.extend(rows)
            parts_box.append('</tbody>')
            parts_box.append(
                '<tfoot>'
                f'<tr><td colspan="3">Total</td><td class="numeric">{total_metric_txt}</td><td class="numeric">{total_lambda_du_txt}</td><td class="numeric">{total_lambda_dd_txt}</td></tr>'
                '</tfoot>'
            )
            parts_box.append('</table>')
            parts_box.append('</div>')
            return ''.join(parts_box)

        def build_formula_reference() -> str:
            section_parts: List[str] = []
            section_parts.append('<section class="formula-section">')
            section_parts.append('<h2>Base Formulas</h2>')

            def render_formulas(entries: List[Tuple[str, str]]) -> str:
                box_bits: List[str] = []
                for latex, note in entries:
                    box_bits.append('<div class="formula-box">')
                    box_bits.append(f'\\[{latex}\\]')
                    box_bits.append(f'<p class="formula-note muted small"><em>{esc(note)}</em></p>')
                    box_bits.append('</div>')
                return ''.join(box_bits)

            def panel_block(title: str, inner_html: str) -> str:
                block_parts: List[str] = []
                block_parts.append('<div class="formula-panel">')
                block_parts.append(f'<div class="formula-panel-header">{esc(title)}</div>')
                block_parts.append('<div class="formula-panel-body">')
                block_parts.append(inner_html)
                block_parts.append('</div>')
                block_parts.append('</div>')
                return ''.join(block_parts)

            oneoo1_entries = [
                (r'PFD_{1oo1} = \lambda_{DU}(T_I/2 + MTTR) + \lambda_{DD}MTTR', 'Average probability of failure on demand for a single 1oo1 channel.'),
                (r'PFH_{1oo1} = \lambda_{DU}', 'Dangerous failure rate per hour for a single 1oo1 channel.'),
            ]
            architecture_blocks = [
                panel_block('1oo1 Architecture', render_formulas(oneoo1_entries)),
            ]
            oneoo2_entries = [
                (r't_{CE} = \frac{\lambda_{DU}^{ind}}{\lambda_D^{ind}}(T_I/2 + MTTR) + \frac{\lambda_{DD}^{ind}}{\lambda_D^{ind}}MTTR', 'Exposure time for common-cause dangerous undetected combinations using independent channel rates.'),
                (r't_{GE} = \frac{\lambda_{DU}^{ind}}{\lambda_D^{ind}}(T_I/3 + MTTR) + \frac{\lambda_{DD}^{ind}}{\lambda_D^{ind}}MTTR', 'Exposure time for general dangerous undetected combinations with staggered testing, independent portion.'),
                (r'PFD_{1oo2} = 2(1-\beta)^2(\lambda_D)^2 t_{CE}t_{GE} \\[4pt]'
                 r'+ \beta\lambda_{DU}(T_I/2 + MTTR) + \beta_D\lambda_{DD}MTTR', 'System-level probability of failure on demand for a redundant 1oo2 channel.'),
                (r'PFH_{1oo2} = 2(1-\beta)\lambda_D^{ind}\lambda_{DU}^{ind}t_{CE} + \beta\lambda_{DU}', 'System-level dangerous failure rate per hour for a redundant 1oo2 channel.'),
            ]
            architecture_blocks.append(
                panel_block('1oo2 Architecture', render_formulas(oneoo2_entries))
            )

            supporting_entries = [
                (r'\lambda_D = \lambda_{DU} + \lambda_{DD}', 'Total dangerous failure rate split into undetected and detected parts.'),
                (r'\lambda_{DU} = r_{DU}\lambda_D,\ \lambda_{DD} = r_{DD}\lambda_D', 'Ratios mapping total dangerous failures to undetected and detected portions.'),
                (r'\lambda_{DU}^{ind} = (1-\beta)\lambda_{DU},\ \lambda_{DD}^{ind} = (1-\beta_D)\lambda_{DD}', 'Independent channel failure rates after removing common cause factors.'),
            ]
            supporting_block = panel_block('Supporting Relations', render_formulas(supporting_entries))

            var_rows: List[Tuple[str, str]] = [
                (r't_{CE}', 'Exposure window for common-cause dangerous undetected failures.'),
                (r't_{GE}', 'Exposure window for general dangerous undetected failures.'),
                (r'\lambda_{DU}', 'Dangerous undetected failure rate.'),
                (r'\lambda_{DD}', 'Dangerous detected failure rate.'),
                (r'\lambda_D', 'Total dangerous failure rate (detected + undetected).'),
                (r'\lambda_D^{ind}', 'Independent-channel total dangerous failure rate (excludes common cause).'),
                (r'\lambda_{DU}^{ind}', 'Channel-specific dangerous undetected failure rate (independent portion).'),
                (r'\lambda_{DD}^{ind}', 'Channel-specific dangerous detected failure rate (independent portion).'),
                (r'r_{DU}', 'Fraction of dangerous failures that are undetected.'),
                (r'r_{DD}', 'Fraction of dangerous failures that are detected.'),
                (r'\beta', 'Common cause factor for dangerous undetected failures.'),
                (r'\beta_D', 'Common cause factor for dangerous detected failures.'),
                (r'T_I', 'Proof-test interval.'),
                (r'MTTR', 'Mean time to repair.'),
            ]
            table_parts: List[str] = ['<div class="formula-box">', '<table class="formula-table"><thead><tr><th>Symbol</th><th>Meaning</th></tr></thead><tbody>']
            for symbol, meaning in var_rows:
                table_parts.append('<tr>')
                table_parts.append(f'<td class="nowrap">\\({symbol}\\)</td>')
                table_parts.append(f'<td>{esc(meaning)}</td>')
                table_parts.append('</tr>')
            table_parts.append('</tbody></table></div>')
            variable_block = panel_block('Variable Summary', ''.join(table_parts))

            section_parts.append('<div class="formula-layout">')
            section_parts.append('<div class="formula-column formula-column--architecture">')
            section_parts.extend(architecture_blocks)
            section_parts.append('</div>')
            section_parts.append('<div class="formula-column formula-column--supporting">')
            section_parts.append(supporting_block)
            section_parts.append('</div>')
            section_parts.append('<div class="formula-column formula-column--variables">')
            section_parts.append(variable_block)
            section_parts.append('</div>')
            section_parts.append('</div>')

            section_parts.append('</section>')
            return ''.join(section_parts)

        # Build HTML
        parts = []
        parts.append('<!doctype html><html><head><meta charset="utf-8">')
        parts.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
        parts.append('<title>SIFU Report</title>')
        parts.append(f'<style>{css}</style>')
        parts.append('<script src="https://polyfill.io/v3/polyfill.min.js?features=es6"></script>')
        parts.append('<script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>')
        parts.append('</head><body>')
        parts.append('<div class="page">')
        parts.append('<h1>SIFU Calculation Report</h1>')
        parts.append(f'<div class="meta">Generated: {esc(dt)}</div>')

        # Summary table
        parts.append('<h2>Summary</h2>')
        parts.append('<table><thead><tr><th>#</th><th>SIFU</th><th>Demand mode (effective)</th><th>Required SIL</th><th>Calculated SIL</th><th class="right">PFDsum</th><th class="right">PFHsum [1/h]</th><th>Status</th></tr></thead><tbody>')
        for i, s in enumerate(payload["sifus"], 1):
            status = '<span class="ok">meets</span>' if s['ok'] else '<span class="bad">fails</span>'
            parts.append(
                '<tr>'
                f'<td class="nowrap">{i}</td>'
                f'<td>{esc(s["meta"].get("sifu_name", f"SIFU {i}"))}</td>'
                f'<td>{esc(s["mode"])}</td>'
                f'<td>{esc(s["req_sil"])}</td>'
                f'<td>{esc(s["sil_calc"])}</td>'
                f'<td class="right">{fmt_pfd(s["pfd_sum"])}</td>'
                f'<td class="right">{fmt_pfh(s["pfh_sum"])}</td>'
                f'<td>{status}</td>'
                '</tr>'
            )
        parts.append('</tbody></table>')

        parts.append(build_formula_reference())

        # Assumptions & Ratios
        parts.append('<div class="grid">')
        parts.append('<div class="card">')
        parts.append('<h3>Global Assumptions</h3>')
        parts.append('<table><tbody>')
        parts.append(f'<tr><th>TI — Proof-test interval [h]</th><td class="right">{asm.get("TI", 0):.2f}</td></tr>')
        parts.append(f'<tr><th>MTTR — Mean time to repair [h]</th><td class="right">{asm.get("MTTR", 0):.2f}</td></tr>')
        parts.append(f'<tr><th>beta — CCF (DU) [–]</th><td class="right">{asm.get("beta", 0):.4f}</td></tr>')
        parts.append(f'<tr><th>beta_D — CCF (DD) [–]</th><td class="right">{asm.get("beta_D", 0):.4f}</td></tr>')
        parts.append('</tbody></table>')
        parts.append('</div>')

        parts.append('<div class="card">')
        parts.append('<h3>DU/DD Ratios (per group)</h3>')
        parts.append('<table><thead><tr><th>Group</th><th class="right">DU [–]</th><th class="right">DD [–]</th></tr></thead><tbody>')
        for g in ("sensor","logic","actuator"):
            du, dd = ratios.get(g, (0.6, 0.4))
            parts.append(f'<tr><td>{g}</td><td class="right">{du:.2f}</td><td class="right">{dd:.2f}</td></tr>')
        parts.append('</tbody></table>')
        parts.append('</div>')
        parts.append('</div>')

        # Detailed sections per SIFU
        for i, s in enumerate(payload["sifus"], 1):
            meta = s['meta']
            parts.append(f'<h2>#{i} — {esc(meta.get("sifu_name", f"SIFU {i}"))}</h2>')
            parts.append('<table><tbody>')
            parts.append(f'<tr><th>Required SIL</th><td>{esc(s["req_sil"])}</td></tr>')
            parts.append(f'<tr><th>Demand mode</th><td>Required: {esc(meta.get("demand_mode_required", "High demand"))} | Effective: {esc(s["mode"])}</td></tr>')
            ov = meta.get('demand_mode_override', None)
            parts.append(f'<tr><th>Override</th><td>{esc(ov) if ov else "—"}</td></tr>')
            status = '<span class="ok">meets</span>' if s['ok'] else '<span class="bad">fails</span>'
            parts.append(f'<tr><th>Calculated SIL</th><td>{esc(s["sil_calc"])}, {status}</td></tr>')
            parts.append(f'<tr><th>Totals</th><td>PFDsum = {fmt_pfd(s["pfd_sum"])} | PFHsum = {fmt_pfh(s["pfh_sum"])} 1/h</td></tr>')
            parts.append('</tbody></table>')

            anchor_token = uid or "sifu"
            anchor_prefix = f"{anchor_token}-{i}"
            arch_html, arch_connectors = build_architecture_lanes(
                s['sensors'],
                s['logic'],
                s['actuators'],
                anchor_prefix=anchor_prefix,
            )
            subgroup_html = render_link_subgroups(s.get('link_subgroups'))
            breakdown_total = s.get('breakdown_total')
            breakdown_html = render_link_breakdown(
                breakdown_total,
                s.get('link_subgroups'),
                s.get('lane_residuals'),
                s.get('mode_key'),
                s.get('mode'),
            )
            if arch_html or subgroup_html or breakdown_html:
                parts.append('<div class="architecture">')
                if arch_html:
                    parts.append('<h3>Architecture overview</h3>')
                    parts.append(arch_html)
                    if arch_connectors:
                        data_json = json.dumps(arch_connectors)
                        safe_json = data_json.replace('</', '<\\/')
                        parts.append('<script type="application/json" class="link-connector-data">')
                        parts.append(safe_json)
                        parts.append('</script>')
                if subgroup_html:
                    parts.append(subgroup_html)
                if breakdown_html:
                    parts.append(breakdown_html)
                parts.append('</div>')

            def render_group(title, items):
                parts.append(f'<h3>{esc(title)}</h3>')
                if not items:
                    parts.append('<div class="muted small">No items</div>')
                    return
                parts.append('<table class="component-table"><colgroup><col class="col-code"><col class="col-pfd"><col class="col-pfh"><col class="col-fit"><col class="col-sil"><col class="col-pdm"></colgroup><thead><tr><th>Code / Name</th><th class="right">PFDavg</th><th class="right">PFHavg [1/h]</th><th class="right">PFH [FIT]</th><th>SIL capability</th><th>PDM code</th></tr></thead><tbody>')
                for it in items:
                    if it.get('architecture') == '1oo2':
                        pfd_g = it.get('pfd_avg', 0.0)
                        pfh_g = it.get('pfh_avg', 0.0)
                        members = it.get('members', [])
                        member_codes = [m.get('code') or m.get('name') or f'Member {idx + 1}' for idx, m in enumerate(members)]
                        group_title = ' ∥ '.join([c for c in member_codes if c]) or '1oo2 redundant set'
                        group_color = sanitize_color(it.get('link_color') or it.get('color'))
                        group_label_bits = ['<div class="group-label">', '<span class="pill arch">1oo2</span>']
                        if group_color:
                            group_label_bits.append(f'<span class="chip-link-dot" style="background:{group_color};"></span>')
                        group_label_bits.append(f'<span class="group-title">{esc(group_title)}</span>')
                        group_label_bits.append('</div>')
                        group_label_html = ''.join(group_label_bits)
                        parts.append('<tr class="group-row">'
                                     f'<td>{group_label_html}</td>'
                                     f'<td class="right">{fmt_pfd(pfd_g)}</td>'
                                     f'<td class="right">{fmt_pfh(pfh_g)}</td>'
                                     f'<td class="right">{fmt_fit(pfh_g)}</td>'
                                     '<td>—</td><td>—</td></tr>')
                        for m_idx, m in enumerate(members, 1):
                            code_val = m.get('code') or m.get('name') or f'Member {m_idx}'
                            name_val = m.get('name')
                            member_color = sanitize_color(m.get('link_color') or m.get('color') or group_color)
                            label_bits = ['<div class="component-label">']
                            if member_color:
                                label_bits.append(f'<span class="chip-link-dot" style="background:{member_color};"></span>')
                            label_bits.append(f'<span class="member-tag">{esc(code_val)}</span>')
                            if name_val and name_val != code_val:
                                label_bits.append(f'<span class="member-caption">{esc(name_val)}</span>')
                            label_bits.append('</div>')
                            note = self._note_for_provenance(m.get('provenance'))
                            if note:
                                label_bits.append(f"<div class=\"lane-note\">{esc(note)}</div>")
                            label_html = ''.join(label_bits)
                            parts.append('<tr class="group-member">'
                                         f'<td>{label_html}</td>'
                                         f'<td class="right">{fmt_pfd(m.get("pfd_avg", m.get("pfd")))}</td>'
                                         f'<td class="right">{fmt_pfh(m.get("pfh_avg", m.get("pfh")))}</td>'
                                         f'<td class="right">{fmt_fit(m.get("pfh_avg", m.get("pfh")))}</td>'
                                         f'<td>{esc(m.get("sys_cap", m.get("syscap", "")) or "—")}</td>'
                                         f'<td>{esc(m.get("pdm_code", "") or "—")}</td>'
                                         '</tr>')
                    else:
                        item_color = sanitize_color(it.get('link_color') or it.get('color'))
                        label_bits = ['<div class="component-label">']
                        if item_color:
                            label_bits.append(f'<span class="chip-link-dot" style="background:{item_color};"></span>')
                        code_label = esc(it.get("code", it.get("name", "?")))
                        label_bits.append(f'<span class="component-label-text">{code_label}</span>')
                        label_bits.append('</div>')
                        note = self._note_for_provenance(it.get('provenance'))
                        if note:
                            label_bits.append(f"<div class=\"lane-note\">{esc(note)}</div>")
                        label_html = ''.join(label_bits)
                        parts.append('<tr>'
                                     f'<td>{label_html}</td>'
                                     f'<td class="right">{fmt_pfd(it.get("pfd_avg", it.get("pfd")))}</td>'
                                     f'<td class="right">{fmt_pfh(it.get("pfh_avg", it.get("pfh")))}</td>'
                                     f'<td class="right">{fmt_fit(it.get("pfh_avg", it.get("pfh")))}</td>'
                                     f'<td>{esc(it.get("sys_cap", it.get("syscap","")) or "—")}</td>'
                                     f'<td>{esc(it.get("pdm_code", "") or "—")}</td>'
                                     '</tr>')
                parts.append('</tbody></table>')


            render_group('Sensors / Inputs', s['sensors'])
            render_group('Logic', s['logic'])
            render_group('Outputs / Actuators', s['actuators'])

        parts.append('<div class="muted small">This report is generated for documentation support of IEC 61508 evaluations. Ensure project-specific assumptions and operational profiles are validated.</div>')
        parts.append('</div>')
        parts.append('''<script>
(function() {
  const laneIndex = { sensors: 0, logic: 1, actuators: 2 };

  function determineStartSide(startLane, endLane) {
    const startIdx = laneIndex[startLane];
    const endIdx = laneIndex[endLane];
    if (startIdx == null || endIdx == null) {
      return 'right';
    }
    return startIdx <= endIdx ? 'right' : 'left';
  }

  function determineEndSide(startLane, endLane) {
    const startIdx = laneIndex[startLane];
    const endIdx = laneIndex[endLane];
    if (startIdx == null || endIdx == null) {
      return 'left';
    }
    return startIdx <= endIdx ? 'left' : 'right';
  }

  function pointFor(rect, side, bounds) {
    const x = side === 'left' ? rect.left - bounds.left : rect.right - bounds.left;
    const y = rect.top + rect.height / 2 - bounds.top;
    return { x: x, y: y };
  }

  function bezierPath(start, end, startSide, endSide) {
    const dx = Math.abs(end.x - start.x);
    const offset = Math.max(36, dx * 0.45);
    const c1x = start.x + (startSide === 'right' ? offset : -offset);
    const c2x = end.x + (endSide === 'left' ? -offset : offset);
    return 'M ' + start.x + ' ' + start.y + ' C ' + c1x + ' ' + start.y + ' ' + c2x + ' ' + end.y + ' ' + end.x + ' ' + end.y;
  }
  function draw(block) {
    const dataTag = block.querySelector('script.link-connector-data');
    const svg = block.querySelector('.arch-link-layer');
    const lanesWrapper = block.querySelector('.arch-lanes-wrapper');
    if (!svg || !lanesWrapper) {
      return;
    }
    svg.innerHTML = '';
    if (!dataTag) {
      svg.setAttribute('width', 0);
      svg.setAttribute('height', 0);
      return;
    }
    let groups;
    try {
      groups = JSON.parse(dataTag.textContent || '[]');
    } catch (err) {
      return;
    }
    if (!Array.isArray(groups) || !groups.length) {
      svg.setAttribute('width', 0);
      svg.setAttribute('height', 0);
      return;
    }
    const bounds = lanesWrapper.getBoundingClientRect();
    const width = bounds.width;
    const height = bounds.height;
    if (!width || !height) {
      return;
    }
    svg.setAttribute('width', width);
    svg.setAttribute('height', height);
    svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
    const svgNS = 'http://www.w3.org/2000/svg';
    groups.forEach(function(group) {
      if (!group || !group.color || !Array.isArray(group.links)) {
        return;
      }
      group.links.forEach(function(link) {
        if (!link || !link.start || !link.end) {
          return;
        }
        const startRef = link.start;
        const endRef = link.end;
        if (!startRef.id || !endRef.id) {
          return;
        }
        const startEl = document.getElementById(startRef.id);
        const endEl = document.getElementById(endRef.id);
        if (!startEl || !endEl) {
          return;
        }
        const startLane = startRef.lane || startEl.getAttribute('data-lane');
        const endLane = endRef.lane || endEl.getAttribute('data-lane');
        if (!startLane || !endLane || startLane === endLane) {
          return;
        }
        const startRect = startEl.getBoundingClientRect();
        const endRect = endEl.getBoundingClientRect();
        const startSide = determineStartSide(startLane, endLane);
        const endSide = determineEndSide(startLane, endLane);
        const startPoint = pointFor(startRect, startSide, bounds);
        const endPoint = pointFor(endRect, endSide, bounds);
        const path = document.createElementNS(svgNS, 'path');
        path.setAttribute('d', bezierPath(startPoint, endPoint, startSide, endSide));
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke', group.color);
        path.setAttribute('stroke-width', '2');
        path.setAttribute('stroke-linecap', 'round');
        path.setAttribute('stroke-linejoin', 'round');
        path.setAttribute('stroke-opacity', '0.99');
        svg.appendChild(path);
      });
    });
  }
  function renderAll() {
    document.querySelectorAll('.architecture').forEach(draw);
  }
  function scheduleRender() {
    window.requestAnimationFrame(renderAll);
  }
  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    scheduleRender();
  } else {
    document.addEventListener('DOMContentLoaded', scheduleRender, { once: true });
  }
  window.addEventListener('load', scheduleRender);
  window.addEventListener('resize', scheduleRender);
})();
</script>''')
        parts.append('</body></html>')

        return '\n'.join(parts)

    def _collect_assignment_payload(self) -> dict:
        out = {"sifus": []}
        for row_idx in range(len(self.rows_meta)):
            meta = self.rows_meta[row_idx]
            widgets = self.sifu_widgets[row_idx]
            mode = self._effective_demand_mode(row_idx)
            mode_key = self._mode_key_from_value(mode)
            sensors = self._collect_list_items(widgets.in_list, 'sensor', mode_key)
            logic   = self._collect_list_items(widgets.logic_list, 'logic', mode_key)
            outputs = self._collect_list_items(widgets.out_list, 'actuator', mode_key)
            pfd_sum, pfh_sum, _ = self._sum_lists(
                (widgets.in_list, widgets.logic_list, widgets.out_list),
                mode_key,
            )
            sil_calc = (
                classify_sil_from_pfh(pfh_sum)
                if mode_key == 'high_demand'
                else classify_sil_from_pfd(pfd_sum)
            )
            req_sil_str, req_rank_raw = normalize_required_sil(meta.get('sil_required', 'n.a.'))
            req_rank = int(req_rank_raw)
            out["sifus"].append({
                "sifu_name": meta.get("sifu_name", f"Row {row_idx+1}"),
                "sil_required": req_sil_str,
                "demand_mode_required": meta.get("demand_mode_required", "High demand"),
                "demand_mode_override": meta.get("demand_mode_override", None),  # optional
                "sensors": sensors, "logic": logic, "actuators": outputs,
                "pfd_sum": float(pfd_sum), "pfh_sum": float(pfh_sum),
                "sil_calculated": sil_calc,
                "sil_required_met": sil_rank(sil_calc) >= req_rank and sil_rank(sil_calc) > 0,
            })
        return out

    def _rebuild_from_payload(self, data: dict):
        self.table.clearContents(); self.table.setRowCount(0)
        self.rows_meta.clear(); self.sifu_widgets.clear()
        sifus = data.get("sifus", [])
        self.table.setRowCount(len(sifus))
        for row_idx, sifu_data in enumerate(sifus):
            req_sil_str, _ = normalize_required_sil(sifu_data.get("sil_required", "n.a."))
            meta = RowMeta({
                "sifu_name": sifu_data.get("sifu_name", f"SIFU {row_idx+1}"),
                "sil_required": req_sil_str,
                "demand_mode_required": sifu_data.get("demand_mode_required", "High demand"),
                "demand_mode_override": sifu_data.get("demand_mode_override", None),
                "source": "user"
            })
            self.rows_meta.append(meta)
            self._ensure_row_uid(meta)

            header = f"{meta['sifu_name']} \nRequired: {meta['sil_required']}\n {meta['demand_mode_required']}"
            self.table.setVerticalHeaderItem(row_idx, QTableWidgetItem(header))

            widgets = SifuRowWidgets()
            self.sifu_widgets[row_idx] = widgets

            effective = self._effective_demand_mode(row_idx)
            widgets.result.combo.setCurrentText(effective)
            widgets.result.override_changed.connect(lambda val, r=row_idx: self._on_row_override_changed(r, val))

            self.table.setCellWidget(row_idx, 0, widgets.in_list)
            self.table.setCellWidget(row_idx, 1, widgets.logic_list)
            self.table.setCellWidget(row_idx, 2, widgets.out_list)
            self.table.setCellWidget(row_idx, 3, widgets.result)

            for sensor in sifu_data.get("sensors", []):
                if sensor.get("architecture") == "1oo2":
                    item = self._create_group_item(sensor, "sensor")
                    widgets.in_list.addItem(item)
                    widgets.in_list.attach_chip(item)
                else:
                    item = self._make_item(sensor.get("code", "?"), sensor.get("pfd_avg", 0.0), sensor.get("pfh_avg", 0.0), sensor.get("sys_cap", ""), sensor.get("pdm_code", ""), kind="sensor", extra_fields=sensor)
                    widgets.in_list.addItem(item)
                    widgets.in_list.attach_chip(item)

            for logic in sifu_data.get("logic", []):
                name = logic.get("code", logic.get("name", "Logic"))
                item = self._make_item(name, logic.get("pfd_avg", 0.0), logic.get("pfh_avg", 0.0), logic.get("sys_cap", ""), kind="logic", extra_fields=logic)
                widgets.logic_list.addItem(item)
                widgets.logic_list.attach_chip(item)

            for act in sifu_data.get("actuators", []):
                if act.get("architecture") == "1oo2":
                    grp_item = self._create_group_item(act, "actuator")
                    widgets.out_list.addItem(grp_item)
                    widgets.out_list.attach_chip(grp_item)
                else:
                    item = self._make_item(act.get("code", "?"), act.get("pfd_avg", 0.0), act.get("pfh_avg", 0.0), act.get("sys_cap", ""), act.get("pdm_code", ""), kind="actuator", extra_fields=act)
                    widgets.out_list.addItem(item)
                    widgets.out_list.attach_chip(item)

            self._update_row_height(row_idx)

        if self.table.columnCount() == 4:
            self.table.setColumnWidth(0, 360); self.table.setColumnWidth(1, 300); self.table.setColumnWidth(2, 360)

        self.recalculate_all()
        self._reseed_link_counters()

    # ----- collect list items -----
    def _collect_list_items(self, lw: QListWidget, group_kind: str, mode_key: str) -> List[dict]:
        items: List[dict] = []
        assumptions = self._current_assumptions()
        du_ratio, dd_ratio = self._ratios(group_kind)
        row_idx, _ = self._row_lane_for_list(lw)
        row_uid = self._row_uid_for_index(row_idx) if row_idx >= 0 else None

        for i in range(lw.count()):
            item = lw.item(i)
            if not item:
                continue
            payload = item.data(Qt.UserRole) or {}
            if payload.get('group') and payload.get('architecture') == '1oo2':
                normalized_members: List[dict] = []
                group_link_color = self._sanitize_link_color(payload.get('link_color'))
                for member in payload.get('members', []):
                    if isinstance(member, dict):
                        member_copy = copy.deepcopy(member)
                        member_id = member_copy.get('instance_id')
                        if not isinstance(member_id, str) or not member_id:
                            member_id = new_instance_id()
                            member_copy['instance_id'] = member_id
                        normalized_members.append(member_copy)
                if normalized_members != payload.get('members'):
                    new_payload = copy.deepcopy(payload)
                    new_payload['members'] = normalized_members
                    item.setData(Qt.UserRole, new_payload)
                    payload = new_payload

                metrics, _, member_infos, errors, _ = self._group_metrics(
                    normalized_members,
                    du_ratio,
                    dd_ratio,
                    mode_key,
                    assumptions,
                )
                for err in errors:
                    self._handle_conversion_error(err)

                members_payload: List[dict] = []
                for info in member_infos:
                    member_payload = copy.deepcopy(info['payload'])
                    member_id = member_payload.get('instance_id')
                    if not isinstance(member_id, str) or not member_id:
                        member_id = new_instance_id()
                        member_payload['instance_id'] = member_id
                    member_entry = {
                        'code': member_payload.get('code'),
                        'name': member_payload.get('name'),
                        'pfd_avg': float(member_payload.get('pfd', member_payload.get('pfd_avg', 0.0)) or 0.0),
                        'pfh_avg': float(member_payload.get('pfh', member_payload.get('pfh_avg', 0.0)) or 0.0),
                        'sys_cap': member_payload.get('sys_cap', member_payload.get('syscap', '')),
                        'pdm_code': member_payload.get('pdm_code'),
                        'instance_id': member_id,
                        'provenance': info['provenance'],
                    }
                    if group_link_color:
                        member_entry['link_color'] = group_link_color
                    members_payload.append(member_entry)

                entry = {
                    'architecture': '1oo2',
                    'members': members_payload,
                    'pfd_avg': float(metrics.pfd),
                    'pfh_avg': float(metrics.pfh),
                    'instance_id': payload.get('instance_id'),
                    'kind': payload.get('kind', group_kind),
                }
                if group_link_color:
                    entry['link_color'] = group_link_color
                    if row_uid:
                        entry['link_group_id'] = self._group_id_for_color(row_uid, group_link_color)
                items.append(entry)
            else:
                inst_id = payload.get('instance_id')
                if not isinstance(inst_id, str) or not inst_id:
                    inst_id = new_instance_id()
                    payload = copy.deepcopy(payload)
                    payload['instance_id'] = inst_id
                    item.setData(Qt.UserRole, payload)

                metrics, provenance, _, _, error = self._component_metrics(
                    payload,
                    du_ratio,
                    dd_ratio,
                    mode_key,
                    assumptions,
                )
                if error:
                    self._handle_conversion_error(error)
                    continue

                entry = {
                    'code': payload.get('code') or payload.get('name'),
                    'name': payload.get('name'),
                    'pfd_avg': float(payload.get('pfd', payload.get('pfd_avg', 0.0)) or 0.0),
                    'pfh_avg': float(payload.get('pfh', payload.get('pfh_avg', 0.0)) or 0.0),
                    'sys_cap': payload.get('syscap', payload.get('sys_cap', '')),
                    'pdm_code': payload.get('pdm_code', ''),
                    'kind': payload.get('kind'),
                    'instance_id': inst_id,
                    'provenance': provenance,
                }
                link_color = self._sanitize_link_color(payload.get('link_color'))
                if link_color:
                    entry['link_color'] = link_color
                    if row_uid:
                        entry['link_group_id'] = self._group_id_for_color(row_uid, link_color)
                items.append(entry)
        return items

    # ----- effective mode -----
    @staticmethod
    def _mode_key_from_value(mode_value: Any) -> str:
        text = str(mode_value or "").strip().lower()
        if "low" in text:
            return "low_demand"
        if "high" in text:
            return "high_demand"
        return "high_demand"

    @staticmethod
    def _mode_label_from_key(mode_key: str) -> str:
        return "Low demand" if str(mode_key).lower() == "low_demand" else "High demand"

    def _effective_demand_mode(self, row_idx: int) -> str:
        if row_idx < 0 or row_idx >= len(self.rows_meta):
            return "High demand"
        meta = self.rows_meta[row_idx]
        return meta.get("demand_mode_override") or meta.get("demand_mode_required", "High demand")

    # ----- sums + display (math unchanged) -----
    def _ratios(self, group: str) -> Tuple[float, float]:
        du, dd = self.du_dd_ratios.get(group, (0.6, 0.4))
        tot = du + dd
        if tot <= 0: return 0.6, 0.4
        return du / tot, dd / tot

    def _current_assumptions(self) -> Assumptions:
        return Assumptions(
            TI=float(self.assumptions['TI']),
            MTTR=float(self.assumptions['MTTR']),
            beta=float(self.assumptions['beta']),
            beta_D=float(self.assumptions['beta_D']),
        )

    @staticmethod
    def _note_for_provenance(provenance: Optional[str]) -> Optional[str]:
        if provenance == "derived_from_pfh":
            return "Data source: λ_total derived from PFH; DU/DD use the current settings."
        if provenance == "derived_from_pfd":
            return "Data source: λ_total derived from 2·PFD/TI using the current TI; DU/DD use the current settings."
        return None

    def _handle_conversion_error(self, message: str) -> None:
        if not message:
            return
        print(message, file=sys.stderr)
        if hasattr(self, 'statusBar'):
            self.statusBar().showMessage(message, 5000)

    def _component_metrics(
        self,
        payload: dict,
        du_ratio: float,
        dd_ratio: float,
        mode_key: str,
        assumptions: Assumptions,
    ) -> Tuple[
        Optional[ChannelMetrics],
        Optional[str],
        Optional[str],
        Optional[Dict[str, float]],
        Optional[str],
    ]:
        try:
            lambda_total, provenance = compute_lambda_total(payload, mode_key, assumptions)
        except ConversionError as exc:
            return None, None, None, None, str(exc)

        metrics = calculate_single_channel(lambda_total, du_ratio, dd_ratio, assumptions)
        note = self._note_for_provenance(provenance)
        title = payload.get('code') or payload.get('name') or "Component"
        pfd_val = payload.get('pfd', payload.get('pfd_avg'))
        pfh_val = payload.get('pfh', payload.get('pfh_avg'))
        syscap = payload.get('syscap', payload.get('sys_cap', ''))
        tooltip = make_html_tooltip(
            str(title),
            pfd_val,
            pfh_val,
            syscap,
            pdm_code=payload.get('pdm_code', ''),
            pfh_entered_fit=payload.get('pfh_fit'),
            pfd_entered_fit=payload.get('pfd_fit'),
            extra_fields={k: v for k, v in payload.items() if isinstance(k, str)},
            note=note,
        )
        detail = {
            'lambda_total': float(lambda_total),
            'lambda_du': float(metrics.lambda_du),
            'lambda_dd': float(metrics.lambda_dd),
            'ratio_du': float(du_ratio),
            'ratio_dd': float(dd_ratio),
            'pfd': float(metrics.pfd),
            'pfh': float(metrics.pfh),
        }
        return metrics, provenance, tooltip, detail, None

    def _group_metrics(
        self,
        members: List[dict],
        du_ratio: float,
        dd_ratio: float,
        mode_key: str,
        assumptions: Assumptions,
    ) -> Tuple[
        ChannelMetrics,
        str,
        List[Dict[str, Any]],
        List[str],
        Dict[str, float],
    ]:
        member_infos: List[Dict[str, Any]] = []
        lambda_values: List[float] = []
        errors: List[str] = []
        for member in members:
            if not isinstance(member, dict):
                continue
            try:
                lam, provenance = compute_lambda_total(member, mode_key, assumptions)
            except ConversionError as exc:
                lam = 0.0
                provenance = None
                errors.append(str(exc))
            lambda_values.append(lam)
            member_infos.append({
                'payload': member,
                'provenance': provenance,
                'lambda_total': lam,
                'lambda_du': lam * float(du_ratio),
                'lambda_dd': lam * float(dd_ratio),
                'ratio_du': float(du_ratio),
                'ratio_dd': float(dd_ratio),
            })

        metrics = calculate_one_out_of_two(lambda_values, du_ratio, dd_ratio, assumptions)
        tooltip = self._format_group_tooltip(member_infos, metrics)
        detail = {
            'lambda_total': float(metrics.lambda_total),
            'lambda_du': float(metrics.lambda_du),
            'lambda_dd': float(metrics.lambda_dd),
            'ratio_du': float(du_ratio),
            'ratio_dd': float(dd_ratio),
            'pfd': float(metrics.pfd),
            'pfh': float(metrics.pfh),
        }
        return metrics, tooltip, member_infos, errors, detail

    def _format_group_tooltip(self, member_infos: List[Dict[str, Any]], metrics: ChannelMetrics) -> str:
        def esc(x: Any) -> str:
            return html.escape('' if x is None else str(x))

        def fmt_pfd(x: Optional[float]) -> str:
            try:
                return f"{float(x):.6f}"
            except Exception:
                return "–"

        def fmt_pfh(x: Optional[float]) -> str:
            try:
                return f"{float(x):.3e} 1/h"
            except Exception:
                return "–"

        labels = [
            member.get('payload', {}).get('code') or member.get('payload', {}).get('name') or f"Member {idx + 1}"
            for idx, member in enumerate(member_infos)
        ]
        title = " ∥ ".join(esc(lbl) for lbl in labels if lbl)

        rows = []
        for idx, info in enumerate(member_infos):
            member_payload = info.get('payload', {})
            pfd_val = member_payload.get('pfd', member_payload.get('pfd_avg'))
            pfh_val = member_payload.get('pfh', member_payload.get('pfh_avg'))
            note = self._note_for_provenance(info.get('provenance'))
            rows.append(
                f"<tr><td>{esc(labels[idx])}</td><td>{fmt_pfd(pfd_val)}</td><td>{fmt_pfh(pfh_val)}</td></tr>"
            )
            if note:
                rows.append(
                    f"<tr><td colspan='3' style='font-size:11px; color:#555;'>{esc(note)}</td></tr>"
                )

        member_table = (
            "<table style='border-collapse:collapse; margin-top:6px;'>"
            "<tr><th style='text-align:left;padding-right:10px;'>Member</th>"
            "<th style='text-align:left;padding-right:10px;'>PFDavg</th>"
            "<th style='text-align:left;'>PFHavg</th></tr>"
            f"{''.join(rows)}"
            "</table>"
        )

        return (
            "<qt>"
            f"<div style='font-weight:600;'>1oo2 Group — {title or 'Members'}</div>"
            "<table style='border-collapse:collapse; margin-top:4px;'>"
            "<tr><td style='padding-right:8px;'><b>PFDavg (group):</b></td>"
            f"<td>{fmt_pfd(metrics.pfd)}</td></tr>"
            "<tr><td style='padding-right:8px;'><b>PFHavg (group):</b></td>"
            f"<td>{fmt_pfh(metrics.pfh)}</td></tr>"
            "</table>"
            f"{member_table}"
            "</qt>"
        )

    def _sum_lists(
        self,
        lists: Tuple[QListWidget, QListWidget, QListWidget],
        mode_key: str,
    ) -> Tuple[float, float, Dict[str, List[Dict[str, Any]]]]:
        pfd_sum = 0.0
        pfh_sum = 0.0
        assumptions = self._current_assumptions()

        def group_of(idx: int) -> str:
            return ('sensor', 'logic', 'actuator')[idx]

        lane_title_map = {
            'sensor': 'Sensors / Inputs',
            'logic': 'Logic',
            'actuator': 'Outputs / Actuators',
        }

        subgroup_totals: Dict[str, Dict[str, Any]] = {}
        lane_totals: Dict[str, Dict[str, Any]] = {
            'sensor': {
                'pfd': 0.0,
                'pfh': 0.0,
                'lambda_du': 0.0,
                'lambda_dd': 0.0,
                'details': [],
                'components': [],
            },
            'logic': {
                'pfd': 0.0,
                'pfh': 0.0,
                'lambda_du': 0.0,
                'lambda_dd': 0.0,
                'details': [],
                'components': [],
            },
            'actuator': {
                'pfd': 0.0,
                'pfh': 0.0,
                'lambda_du': 0.0,
                'lambda_dd': 0.0,
                'details': [],
                'components': [],
            },
        }
        total_lambda_du = 0.0
        total_lambda_dd = 0.0
        total_details: List[Dict[str, Any]] = []

        def describe_payload(payload: dict, default_label: str) -> Tuple[str, List[str]]:
            if payload.get('group') and payload.get('architecture') == '1oo2':
                member_labels: List[str] = []
                for m_idx, member in enumerate(payload.get('members', [])):
                    if not isinstance(member, dict):
                        continue
                    label = member.get('code') or member.get('name') or f"Member {m_idx + 1}"
                    member_labels.append(str(label))
                label = " ∥ ".join(lbl for lbl in member_labels if lbl) or default_label
                return label, member_labels
            label = payload.get('code') or payload.get('name') or default_label
            return str(label), []

        def build_detail_entry(
            label: str,
            lane: str,
            architecture: Optional[str],
            metrics_detail: Optional[Dict[str, float]],
            member_labels: Optional[List[str]] = None,
            color: Optional[str] = None,
        ) -> Optional[Dict[str, Any]]:
            if not metrics_detail:
                return None
            return {
                'label': label,
                'lane': lane,
                'lane_title': lane_title_map.get(lane, lane.title()),
                'architecture': architecture,
                'member_labels': list(member_labels or []),
                'color': color,
                'lambda_total': float(metrics_detail.get('lambda_total', 0.0)),
                'lambda_du': float(metrics_detail.get('lambda_du', 0.0)),
                'lambda_dd': float(metrics_detail.get('lambda_dd', 0.0)),
                'ratio_du': float(metrics_detail.get('ratio_du', 0.0)),
                'ratio_dd': float(metrics_detail.get('ratio_dd', 0.0)),
                'pfd': float(metrics_detail.get('pfd', 0.0)),
                'pfh': float(metrics_detail.get('pfh', 0.0)),
            }

        for idx, lw in enumerate(lists):
            group = group_of(idx)
            du_ratio, dd_ratio = self._ratios(group)
            lane_row_idx, _ = self._row_lane_for_list(lw)
            row_uid = self._row_uid_for_index(lane_row_idx) if lane_row_idx >= 0 else None
            for i in range(lw.count()):
                item = lw.item(i)
                if item is None:
                    continue
                ud = item.data(Qt.UserRole) or {}
                raw_group_id = ud.get('link_group_id')
                link_group_id = self._normalize_link_group_id(raw_group_id)
                if link_group_id and raw_group_id != link_group_id:
                    updated_payload = copy.deepcopy(ud)
                    updated_payload['link_group_id'] = link_group_id
                    item.setData(Qt.UserRole, updated_payload)
                    ud = updated_payload
                elif raw_group_id and not link_group_id:
                    updated_payload = copy.deepcopy(ud)
                    updated_payload.pop('link_group_id', None)
                    item.setData(Qt.UserRole, updated_payload)
                    ud = updated_payload

                link_color = self._sanitize_link_color(ud.get('link_color'))
                if link_color and ud.get('link_color') != link_color:
                    updated_payload = copy.deepcopy(ud)
                    updated_payload['link_color'] = link_color
                    item.setData(Qt.UserRole, updated_payload)
                    ud = updated_payload
                elif ud.get('link_color') and not link_color:
                    updated_payload = copy.deepcopy(ud)
                    updated_payload.pop('link_color', None)
                    item.setData(Qt.UserRole, updated_payload)
                    ud = updated_payload
                if link_color and row_uid:
                    expected_group_id = self._group_id_for_color(row_uid, link_color)
                    if link_group_id != expected_group_id:
                        updated_payload = copy.deepcopy(ud)
                        updated_payload['link_group_id'] = expected_group_id
                        updated_payload['link_color'] = link_color
                        item.setData(Qt.UserRole, updated_payload)
                        ud = updated_payload
                        link_group_id = expected_group_id
                elif not link_color and link_group_id:
                    updated_payload = copy.deepcopy(ud)
                    updated_payload.pop('link_group_id', None)
                    item.setData(Qt.UserRole, updated_payload)
                    ud = updated_payload
                    link_group_id = None

                if ud.get('group') and ud.get('architecture') == '1oo2':
                    members = [m for m in ud.get('members', []) if isinstance(m, dict)]
                    metrics, tooltip, member_infos, errors, group_detail = self._group_metrics(
                        members,
                        du_ratio,
                        dd_ratio,
                        mode_key,
                        assumptions,
                    )
                    for err in errors:
                        self._handle_conversion_error(err)

                    metrics_pfd = float(metrics.pfd)
                    metrics_pfh = float(metrics.pfh)
                    metrics_lambda_du = float(metrics.lambda_du)
                    metrics_lambda_dd = float(metrics.lambda_dd)
                    label, member_labels = describe_payload(ud, item.text() or 'Component')
                    component_info = {
                        'label': label,
                        'member_labels': member_labels,
                        'architecture': '1oo2',
                        'kind': ud.get('kind', group),
                        'lane': group,
                        'lane_title': lane_title_map.get(group, group.title()),
                        'color': link_color,
                    }
                    detail_entry = build_detail_entry(
                        label,
                        group,
                        '1oo2',
                        group_detail,
                        member_labels,
                        link_color,
                    )

                    if link_group_id:
                        entry = subgroup_totals.setdefault(
                            link_group_id,
                            {
                                'color': link_color,
                                'pfd': 0.0,
                                'pfh': 0.0,
                                'lambda_du': 0.0,
                                'lambda_dd': 0.0,
                                'components': [],
                                'lanes': set(),
                                'details': [],
                            },
                        )
                        if link_color and not entry.get('color'):
                            entry['color'] = link_color
                        entry['pfd'] += metrics_pfd
                        entry['pfh'] += metrics_pfh
                        entry['lambda_du'] += metrics_lambda_du
                        entry['lambda_dd'] += metrics_lambda_dd
                        entry['components'].append(component_info)
                        entry['lanes'].add(group)
                        if detail_entry:
                            entry['details'].append(detail_entry)
                    else:
                        lane_totals[group]['pfd'] += metrics_pfd
                        lane_totals[group]['pfh'] += metrics_pfh
                        lane_totals[group]['lambda_du'] += metrics_lambda_du
                        lane_totals[group]['lambda_dd'] += metrics_lambda_dd
                        lane_totals[group]['components'].append(component_info)
                        if detail_entry:
                            lane_totals[group]['details'].append(detail_entry)

                    item.setToolTip(tooltip)
                    continue

                metrics, _, tooltip, comp_detail, error = self._component_metrics(
                    ud,
                    du_ratio,
                    dd_ratio,
                    mode_key,
                    assumptions,
                )
                if error:
                    self._handle_conversion_error(error)
                    continue

                metrics_pfd = float(metrics.pfd)
                metrics_pfh = float(metrics.pfh)
                metrics_lambda_du = float(metrics.lambda_du)
                metrics_lambda_dd = float(metrics.lambda_dd)
                label, member_labels = describe_payload(ud, item.text() or 'Component')
                component_info = {
                    'label': label,
                    'member_labels': member_labels,
                    'architecture': ud.get('architecture'),
                    'kind': ud.get('kind', group),
                    'lane': group,
                    'lane_title': lane_title_map.get(group, group.title()),
                    'color': link_color,
                }
                detail_entry = build_detail_entry(
                    label,
                    group,
                    ud.get('architecture'),
                    comp_detail,
                    member_labels,
                    link_color,
                )

                if link_group_id:
                    entry = subgroup_totals.setdefault(
                        link_group_id,
                        {
                            'color': link_color,
                            'pfd': 0.0,
                            'pfh': 0.0,
                            'lambda_du': 0.0,
                            'lambda_dd': 0.0,
                            'components': [],
                            'lanes': set(),
                            'details': [],
                        },
                    )
                    if link_color and not entry.get('color'):
                        entry['color'] = link_color
                    entry['pfd'] += metrics_pfd
                    entry['pfh'] += metrics_pfh
                    entry['lambda_du'] += metrics_lambda_du
                    entry['lambda_dd'] += metrics_lambda_dd
                    entry['components'].append(component_info)
                    entry['lanes'].add(group)
                    if detail_entry:
                        entry['details'].append(detail_entry)
                else:
                    lane_totals[group]['pfd'] += metrics_pfd
                    lane_totals[group]['pfh'] += metrics_pfh
                    lane_totals[group]['lambda_du'] += metrics_lambda_du
                    lane_totals[group]['lambda_dd'] += metrics_lambda_dd
                    lane_totals[group]['components'].append(component_info)
                    if detail_entry:
                        lane_totals[group]['details'].append(detail_entry)

                if tooltip:
                    item.setToolTip(tooltip)

        subgroup_payload: Dict[str, List[Dict[str, Any]]] = {}
        if subgroup_totals:
            combined_payload: List[Dict[str, Any]] = []
            for group_id, info in subgroup_totals.items():
                pfd_sum += info['pfd']
                pfh_sum += info['pfh']
                total_lambda_du += info.get('lambda_du', 0.0)
                total_lambda_dd += info.get('lambda_dd', 0.0)
                comp_entries: List[Dict[str, Any]] = []
                labels: List[str] = []
                for comp in info['components']:
                    if not isinstance(comp, dict):
                        continue
                    label_val = comp.get('label')
                    if label_val:
                        labels.append(label_val)
                    comp_entries.append({
                        'label': label_val,
                        'lane': comp.get('lane'),
                        'lane_title': comp.get('lane_title') or lane_title_map.get(comp.get('lane'), comp.get('lane', '')),
                        'architecture': comp.get('architecture'),
                        'member_labels': comp.get('member_labels', []),
                        'kind': comp.get('kind'),
                        'color': comp.get('color', info.get('color')),
                    })
                detail_entries: List[Dict[str, Any]] = []
                for detail in info.get('details', []):
                    if not isinstance(detail, dict):
                        continue
                    detail_entries.append({
                        'label': detail.get('label'),
                        'lane': detail.get('lane'),
                        'lane_title': detail.get('lane_title'),
                        'architecture': detail.get('architecture'),
                        'member_labels': detail.get('member_labels', []),
                        'color': detail.get('color', info.get('color')),
                        'lambda_total': float(detail.get('lambda_total', 0.0)),
                        'lambda_du': float(detail.get('lambda_du', 0.0)),
                        'lambda_dd': float(detail.get('lambda_dd', 0.0)),
                        'ratio_du': float(detail.get('ratio_du', 0.0)),
                        'ratio_dd': float(detail.get('ratio_dd', 0.0)),
                        'pfd': float(detail.get('pfd', 0.0)),
                        'pfh': float(detail.get('pfh', 0.0)),
                    })
                lanes = sorted(info.get('lanes', set()))
                combined_payload.append({
                    'id': group_id,
                    'color': info.get('color'),
                    'pfd': float(info['pfd']),
                    'pfh': float(info['pfh']),
                    'lambda_du': float(info.get('lambda_du', 0.0)),
                    'lambda_dd': float(info.get('lambda_dd', 0.0)),
                    'components': comp_entries,
                    'member_labels': labels,
                    'lanes': [lane_title_map.get(lane, lane) for lane in lanes],
                    'count': len(comp_entries),
                    'details': detail_entries,
                })
                total_details.extend(detail_entries)
            subgroup_payload['combined'] = combined_payload

        lane_entries: List[Dict[str, Any]] = []
        for lane_key, lane_metrics in lane_totals.items():
            if lane_metrics['pfd'] != 0.0 or lane_metrics['pfh'] != 0.0:
                lane_detail_entries: List[Dict[str, Any]] = []
                for detail in lane_metrics.get('details', []):
                    if not isinstance(detail, dict):
                        continue
                    lane_detail_entries.append({
                        'label': detail.get('label'),
                        'lane': detail.get('lane', lane_key),
                        'lane_title': detail.get('lane_title') or lane_title_map.get(lane_key, lane_key.title()),
                        'architecture': detail.get('architecture'),
                        'member_labels': detail.get('member_labels', []),
                        'color': detail.get('color'),
                        'lambda_total': float(detail.get('lambda_total', 0.0)),
                        'lambda_du': float(detail.get('lambda_du', 0.0)),
                        'lambda_dd': float(detail.get('lambda_dd', 0.0)),
                        'ratio_du': float(detail.get('ratio_du', 0.0)),
                        'ratio_dd': float(detail.get('ratio_dd', 0.0)),
                        'pfd': float(detail.get('pfd', 0.0)),
                        'pfh': float(detail.get('pfh', 0.0)),
                    })
                lane_entries.append({
                    'lane': lane_key,
                    'lane_title': lane_title_map.get(lane_key, lane_key.title()),
                    'pfd': float(lane_metrics['pfd']),
                    'pfh': float(lane_metrics['pfh']),
                    'lambda_du': float(lane_metrics['lambda_du']),
                    'lambda_dd': float(lane_metrics['lambda_dd']),
                    'details': lane_detail_entries,
                })
                total_details.extend(lane_detail_entries)
            pfd_sum += lane_metrics['pfd']
            pfh_sum += lane_metrics['pfh']
            total_lambda_du += lane_metrics['lambda_du']
            total_lambda_dd += lane_metrics['lambda_dd']

        subgroup_payload['lane_residuals'] = lane_entries
        subgroup_payload['total'] = {
            'pfd': float(pfd_sum),
            'pfh': float(pfh_sum),
            'lambda_du': float(total_lambda_du),
            'lambda_dd': float(total_lambda_dd),
            'details': total_details,
        }

        return pfd_sum, pfh_sum, subgroup_payload

    # ----- recalc & UI update -----
    def recalculate_row(self, row_idx: int):
        if row_idx < 0 or row_idx >= len(self.rows_meta): return
        widgets = self.sifu_widgets.get(row_idx)
        if not widgets: return  # can happen after remove
        mode = self._effective_demand_mode(row_idx)
        mode_key = self._mode_key_from_value(mode)
        pfd_sum, pfh_sum, subgroup_info = self._sum_lists(
            (widgets.in_list, widgets.logic_list, widgets.out_list),
            mode_key,
        )
        is_high = (mode_key == "high_demand")
        if is_high:
            sil_calc = classify_sil_from_pfh(pfh_sum)
            metric_caption = "PFH"
            metric_value = f"{pfh_sum:.3e} 1/h"
            demand_txt = "High demand"
        else:
            sil_calc = classify_sil_from_pfd(pfd_sum)
            metric_caption = "PFD"
            metric_value = f"{pfd_sum:.6f} (–)"
            demand_txt = "Low demand"

        req_sil_str, req_rank_raw = normalize_required_sil(self.rows_meta[row_idx].get('sil_required', 'n.a.'))
        req_rank = int(req_rank_raw)
        calc_rank = sil_rank(sil_calc)
        ok = (calc_rank >= req_rank) and (calc_rank > 0)

        widgets.result.set_sil_badge(sil_calc, ok if calc_rank > 0 else None)

        widgets.result.demand_caption.setText("Demand mode")
        widgets.result.combo.setCurrentText(demand_txt)
        widgets.result.req_value.setText(req_sil_str)
        widgets.result.calc_value.setText(sil_calc)
        widgets.result.metric_caption.setText(metric_caption)
        widgets.result.metric_value.setText(metric_value)
        tooltip_lines: List[str] = [
            demand_txt,
            f"Required: {req_sil_str}",
            f"Calculated: {sil_calc}",
            f"{metric_caption}: {metric_value}",
        ]

        def fmt_optional_pfd(value: Optional[float]) -> str:
            if value is None:
                return ""
            try:
                return f"PFDavg {float(value):.6f}"
            except Exception:
                return ""

        def fmt_optional_pfh(value: Optional[float]) -> str:
            if value is None:
                return ""
            try:
                return f"PFHavg {float(value):.3e} 1/h"
            except Exception:
                return ""

        def fmt_optional_lambda_du(value: Optional[float]) -> str:
            if value is None:
                return ""
            try:
                return f"λ_DU {float(value):.3e} 1/h"
            except Exception:
                return ""

        def fmt_optional_lambda_dd(value: Optional[float]) -> str:
            if value is None:
                return ""
            try:
                return f"λ_DD {float(value):.3e} 1/h"
            except Exception:
                return ""

        def fmt_lambda_value(value: Optional[float]) -> str:
            if value is None:
                return "–"
            try:
                return f"{float(value):.3e}"
            except Exception:
                return "–"

        def fmt_ratio_percent(value: Optional[float]) -> str:
            if value is None:
                return "–"
            try:
                return f"{float(value) * 100.0:.1f}%"
            except Exception:
                return "–"

        def fmt_pfd_value(value: Optional[float]) -> str:
            if value is None:
                return "–"
            try:
                return f"{float(value):.6f}"
            except Exception:
                return "–"

        def fmt_pfh_value(value: Optional[float]) -> str:
            if value is None:
                return "–"
            try:
                return f"{float(value):.3e}"
            except Exception:
                return "–"

        def build_detail_lines(details: Any, indent: str = "    ") -> List[str]:
            lines: List[str] = []
            if not isinstance(details, (list, tuple)):
                return lines
            for detail in details:
                if not isinstance(detail, dict):
                    continue
                label = detail.get('label') or detail.get('lane_title') or 'Component'
                lane_title = detail.get('lane_title')
                if lane_title and lane_title not in label:
                    label = f"{label} ({lane_title})"
                lambda_total_txt = fmt_lambda_value(detail.get('lambda_total'))
                ratio_du_txt = fmt_ratio_percent(detail.get('ratio_du'))
                lambda_du_txt = fmt_lambda_value(detail.get('lambda_du'))
                segments: List[str] = []
                if (
                    lambda_total_txt != "–"
                    and ratio_du_txt != "–"
                    and lambda_du_txt != "–"
                ):
                    segments.append(
                        f"λ_total {lambda_total_txt} × r_DU {ratio_du_txt} → λ_DU {lambda_du_txt} 1/h"
                    )
                if segments:
                    lines.append(f"{indent}{label}: {' | '.join(segments)}")
            return lines

        combined_groups: List[Dict[str, Any]] = []
        lane_residuals: List[Dict[str, Any]] = []
        total_entry: Optional[Dict[str, Any]] = None
        if isinstance(subgroup_info, dict):
            combined_groups = subgroup_info.get('combined', []) or []
            lane_residuals = subgroup_info.get('lane_residuals', []) or []
            total_candidate = subgroup_info.get('total')
            if isinstance(total_candidate, dict):
                total_entry = total_candidate

        if combined_groups:
            tooltip_lines.append("")
            tooltip_lines.append("Link subgroups:")
            for idx, subgroup in enumerate(combined_groups, 1):
                if not isinstance(subgroup, dict):
                    continue
                header_bits = [f"  Subgroup {idx}"]
                lanes = subgroup.get('lanes')
                if isinstance(lanes, (list, tuple)) and lanes:
                    header_bits.append(f"[{', '.join(str(l) for l in lanes if l)}]")
                tooltip_lines.append(" ".join(header_bits))

                metric_bits: List[str] = []
                if is_high:
                    pfh_txt = fmt_optional_pfh(subgroup.get('pfh'))
                    if pfh_txt:
                        metric_bits.append(pfh_txt)
                else:
                    pfd_txt = fmt_optional_pfd(subgroup.get('pfd'))
                    if pfd_txt:
                        metric_bits.append(pfd_txt)
                lambda_du_txt = fmt_optional_lambda_du(subgroup.get('lambda_du'))
                if lambda_du_txt:
                    metric_bits.append(lambda_du_txt)
                lambda_dd_txt = fmt_optional_lambda_dd(subgroup.get('lambda_dd'))
                if lambda_dd_txt:
                    metric_bits.append(lambda_dd_txt)
                if metric_bits:
                    tooltip_lines.append("    " + " | ".join(metric_bits))

                members = subgroup.get('member_labels')
                if not members:
                    members = [
                        comp.get('label')
                        for comp in subgroup.get('components', [])
                        if isinstance(comp, dict) and comp.get('label')
                    ]
                if members:
                    tooltip_lines.append(
                        "    Members: " + ", ".join(str(lbl) for lbl in members if lbl)
                    )

                detail_lines = build_detail_lines(subgroup.get('details'), "      ")
                tooltip_lines.extend(detail_lines)

        if lane_residuals:
            tooltip_lines.append("")
            tooltip_lines.append("Ungrouped lane contributions:")
            for entry in lane_residuals:
                if not isinstance(entry, dict):
                    continue
                lane_label = entry.get('lane_title') or entry.get('lane') or 'Lane'
                metric_bits: List[str] = []
                if is_high:
                    pfh_txt = fmt_optional_pfh(entry.get('pfh'))
                    if pfh_txt:
                        metric_bits.append(pfh_txt)
                else:
                    pfd_txt = fmt_optional_pfd(entry.get('pfd'))
                    if pfd_txt:
                        metric_bits.append(pfd_txt)
                lambda_du_txt = fmt_optional_lambda_du(entry.get('lambda_du'))
                if lambda_du_txt:
                    metric_bits.append(lambda_du_txt)
                lambda_dd_txt = fmt_optional_lambda_dd(entry.get('lambda_dd'))
                if lambda_dd_txt:
                    metric_bits.append(lambda_dd_txt)
                if metric_bits:
                    tooltip_lines.append(f"  {lane_label}: {' | '.join(metric_bits)}")
                else:
                    tooltip_lines.append(f"  {lane_label}: —")

                detail_lines = build_detail_lines(entry.get('details'), "    ")
                tooltip_lines.extend(detail_lines)

        if total_entry:
            total_bits: List[str] = []
            if is_high:
                total_pfh_txt = fmt_optional_pfh(total_entry.get('pfh'))
                if total_pfh_txt:
                    total_bits.append(total_pfh_txt)
            else:
                total_pfd_txt = fmt_optional_pfd(total_entry.get('pfd'))
                if total_pfd_txt:
                    total_bits.append(total_pfd_txt)
            total_lambda_du_txt = fmt_optional_lambda_du(total_entry.get('lambda_du'))
            if total_lambda_du_txt:
                total_bits.append(total_lambda_du_txt)
            total_lambda_dd_txt = fmt_optional_lambda_dd(total_entry.get('lambda_dd'))
            if total_lambda_dd_txt:
                total_bits.append(total_lambda_dd_txt)
            if total_bits:
                tooltip_lines.append("")
                tooltip_lines.append("Overall composition total:")
                tooltip_lines.append("  " + " | ".join(total_bits))

        widgets.result.setToolTip("\n".join(tooltip_lines))

        self._update_row_height(row_idx)
        # refresh 1oo2 tooltips
        self._refresh_group_tooltips_in_row(row_idx)
        self._schedule_filter_update()

    def recalculate_all(self):
        for row_idx in range(self.table.rowCount()):
            self.recalculate_row(row_idx)
        self._reapply_sifu_filter()

    # ----- SIFU filter helpers -----
    def _schedule_filter_update(self, _text: str = "") -> None:
        timer = getattr(self, "_filter_timer", None)
        if timer is None:
            return
        if timer.isActive():
            timer.stop()
        timer.start()

    def _reapply_sifu_filter(self) -> None:
        if not hasattr(self, "sifu_filter"):
            return
        self._apply_sifu_filter(self.sifu_filter.text())

    def _apply_sifu_filter(self, text: str) -> None:
        if not hasattr(self, "table"):
            return
        tokens = [tok.casefold() for tok in re.split(r"\s+", text.strip()) if tok]
        total = self.table.rowCount()
        matches = 0
        for row_idx in range(total):
            visible = True
            if tokens:
                haystack = self._row_filter_haystack(row_idx)
                visible = all(tok in haystack for tok in tokens)
            self.table.setRowHidden(row_idx, not visible)
            if visible:
                matches += 1

        if hasattr(self, "sifu_filter_info"):
            if total == 0:
                status = "No SIFUs"
            elif tokens:
                suffix = "match" if matches == 1 else "matches"
                status = f"{matches}/{total} {suffix}"
            else:
                suffix = "SIFU" if total == 1 else "SIFUs"
                status = f"{total} {suffix}"
            self.sifu_filter_info.setText(status)
            self.sifu_filter_info.setProperty("filtered", bool(tokens))
            self.sifu_filter_info.style().unpolish(self.sifu_filter_info)
            self.sifu_filter_info.style().polish(self.sifu_filter_info)

    def _row_filter_haystack(self, row_idx: int) -> str:
        parts: List[str] = []
        if 0 <= row_idx < len(self.rows_meta):
            meta = self.rows_meta[row_idx]
            for key in ("sifu_name", "sil_required", "demand_mode_required", "demand_mode_override"):
                val = meta.get(key)
                if val:
                    parts.append(str(val))
        parts.append(str(row_idx + 1))
        widgets = self.sifu_widgets.get(row_idx)
        if widgets:
            lists = (widgets.in_list, widgets.logic_list, widgets.out_list)
            for lw in lists:
                for i in range(lw.count()):
                    item = lw.item(i)
                    if not item:
                        continue
                    text = item.text()
                    if text:
                        parts.append(str(text))
                    data = item.data(Qt.UserRole) or {}
                    for key in ("code", "name", "pdm_code", "syscap", "sys_cap", "architecture"):
                        val = data.get(key)
                        if val:
                            parts.append(str(val))
                    members = data.get("members")
                    if isinstance(members, list):
                        for member in members:
                            if isinstance(member, dict):
                                for key in ("code", "name"):
                                    val = member.get(key)
                                    if val:
                                        parts.append(str(val))
        return " ".join(parts).casefold()

    def _focus_sifu_filter(self) -> None:
        if hasattr(self, "sifu_filter"):
            self.sifu_filter.setFocus(Qt.OtherFocusReason)
            self.sifu_filter.selectAll()

    def _row_preferred_height(self, widgets: SifuRowWidgets) -> int:
        def list_height(lw: QListWidget) -> int:
            if lw.count() == 0: return 64
            total = 0
            for i in range(lw.count()):
                h = lw.sizeHintForRow(i)
                if h <= 0:
                    h = lw.item(i).sizeHint().height()
                total += h
            return max(64, total + 12)

        res_h = widgets.result.sizeHint().height() + 8
        return max(
            list_height(widgets.in_list),
            list_height(widgets.logic_list),
            list_height(widgets.out_list),
            res_h
        )

    def _update_row_height(self, row_idx: int) -> None:
        widgets = self.sifu_widgets.get(row_idx)
        if not widgets: return
        self.table.setRowHeight(row_idx, self._row_preferred_height(widgets))

    def _autosize_columns_initial(self):
        """One-time autosize by content once cell widgets are rendered."""
        if getattr(self, "_columns_sized_once", False):
            return
        hdr = self.table.horizontalHeader()
        from PyQt5.QtWidgets import QHeaderView

        # 0..2 inhaltlich bemessen, danach interaktiv setzen
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.resizeColumnsToContents()

        # Untergrenzen setzen, dann zurück auf Interactive für 0..2
        minw = [max(self.table.columnWidth(i), 140) for i in range(self.table.columnCount())]
        for i in range(3):
            hdr.setSectionResizeMode(i, QHeaderView.Interactive)
            self.table.setColumnWidth(i, minw[i])

        # Result-Spalte kompakt nach Inhalt und NICHT strecken
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hdr.setStretchLastSection(False)

        self._columns_sized_once = True

    def _finalize_layout(self) -> None:
        """
        Erzwingt einen konsistenten Tabellenzustand nach Restore/Autosize:
        - keine gestreckte letzte Spalte
        - Result (Spalte 3) nach Inhalt
        - Mindestbreiten für 0..2..3
        - Kappung, falls Result viel zu breit gespeichert wurde
        """
        hdr = self.table.horizontalHeader()
        from PyQt5.QtWidgets import QHeaderView
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        # sinnvolle Mindestbreiten
        min_widths = (360, 300, 360, 220)
        for i, mw in enumerate(min_widths):
            if self.table.columnWidth(i) < mw:
                self.table.setColumnWidth(i, mw)

        # Wenn Result zu breit gespeichert war, kappen
        w3 = self.table.columnWidth(3)
        if w3 > 500:
            self.table.setColumnWidth(3, 280)

    # ----- New Project / Add / Remove SIFU -----

    def _new_project_impl(self):
        """Actual implementation for 'New Project'. Used by fallback as well."""
        if self.table.rowCount() == 0:
            return
        reply = QMessageBox.question(
            self, "New Project",
            "Clear all SIFUs and start a new project?Libraries remain loaded.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        self._end_link_session(silent=True)
        self._link_session_counters.clear()
        # Clear table & metadata (keep libraries)
        self.table.clearContents(); self.table.setRowCount(0)
        self.rows_meta.clear(); self.sifu_widgets.clear()
        self.recalculate_all()
        self._reseed_link_counters()
        self.statusBar().showMessage("Project cleared", 1500)

    def _action_new_project_fallback(self):
        """Fallback in case _action_new_project is not bound (robust against patching mishaps)."""
        if self.table.rowCount() == 0:
            return
        reply = QMessageBox.question(
            self, "New Project",
            "Clear all SIFUs and start a new project?\nLibraries remain loaded.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        self._end_link_session(silent=True)
        self._link_session_counters.clear()
        # Clear table & metadata (keep libraries)
        self.table.clearContents(); self.table.setRowCount(0)
        self.rows_meta.clear(); self.sifu_widgets.clear()
        self.recalculate_all()
        self._reseed_link_counters()
        self.statusBar().showMessage("Project cleared", 1500)

    def _action_new_project(self):
        if self.table.rowCount() == 0:
            return
        reply = QMessageBox.question(
            self, "New Project",
            "Clear all SIFUs and start a new project?\nLibraries remain loaded.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        # Clear table & metadata (keep libraries)
        self.table.clearContents(); self.table.setRowCount(0)
        self.rows_meta.clear(); self.sifu_widgets.clear()
        self.recalculate_all()
        self.statusBar().showMessage("Project cleared", 1500)

    def _action_add_sifu(self):
        dlg = AddSifuDialog(self)
        if dlg.exec_():
            meta = dlg.get_values()
            self._append_sifu_row(meta)
            self.statusBar().showMessage("SIFU added", 1500)

    def _action_remove_sifu(self):
        row = self.table.currentRow()
        if row < 0 or row >= self.table.rowCount():
            return
        widgets = self.sifu_widgets.get(row)
        non_empty = any([
            widgets.in_list.count() > 0,
            widgets.logic_list.count() > 0,
            widgets.out_list.count() > 0
        ])
        if non_empty:
            r = QMessageBox.question(
                self, "Remove SIFU",
                "Selected SIFU contains components. Remove it?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if r != QMessageBox.Yes:
                return
        row_uid = self._row_uid_for_index(row)
        if row_uid and self._link_active_row_uid == row_uid:
            self._end_link_session(silent=True)
        if row_uid:
            self._link_session_counters.pop(row_uid, None)
        # Remove row from UI and metadata
        self.table.removeRow(row)
        self.rows_meta.pop(row)
        self.sifu_widgets.pop(row, None)

        # Rebuild headers and indices mapping
        new_map = {}
        for i in range(self.table.rowCount()):
            in_list = self.table.cellWidget(i, 0)
            logic   = self.table.cellWidget(i, 1)
            out_list= self.table.cellWidget(i, 2)
            result  = self.table.cellWidget(i, 3)
            if in_list and logic and out_list and result:
                # try reuse existing instance
                w = self.sifu_widgets.get(i)
                if not w:
                    w = SifuRowWidgets()
                    w.in_list = in_list; w.logic_list = logic; w.out_list = out_list; w.result = result
                new_map[i] = w
                meta = self.rows_meta[i]
                header = f"{meta['sifu_name']} SIL req {meta['sil_ required'] if 'sil_ required' in meta else meta['sil_required']} {meta['demand_mode_required']}"
                header = header.replace("sil_ required","sil_required")
                self.table.setVerticalHeaderItem(i, QTableWidgetItem(header))
        self.sifu_widgets = new_map
        self.recalculate_all()
        self._reseed_link_counters()
        self.statusBar().showMessage("SIFU removed", 1500)

    def _action_edit_sifu(self):
        row = self._current_row_index()
        self._edit_sifu_at_row(row)

    def _on_header_double_clicked(self, section: int):
        if 0 <= section < self.table.rowCount():
            self._edit_sifu_at_row(section)

    def _edit_sifu_at_row(self, row_idx: int):
        if row_idx < 0 or row_idx >= len(self.rows_meta): return
        meta = self.rows_meta[row_idx]
        dlg = EditSifuDialog(meta, self)
        if dlg.exec_():
            new_meta = dlg.get_values()
            meta["sifu_name"] = new_meta["sifu_name"]
            meta["sil_required"] = new_meta["sil_required"]
            meta["demand_mode_required"] = new_meta["demand_mode_required"]
            header = f"{meta['sifu_name']} \nRequired: {meta['sil_required']}\n {meta['demand_mode_required']}"
            self.table.setVerticalHeaderItem(row_idx, QTableWidgetItem(header))
            widgets = self.sifu_widgets.get(row_idx)
            if widgets and not meta.get("demand_mode_override"):
                widgets.result.combo.setCurrentText(meta["demand_mode_required"])
            self.recalculate_row(row_idx)
            self._reapply_sifu_filter()
            self.statusBar().showMessage("SIFU updated", 1500)

    def _append_sifu_row(self, meta: RowMeta):
        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)
        self.rows_meta.append(meta)
        self._ensure_row_uid(meta)

        widgets = SifuRowWidgets()
        self.sifu_widgets[row_idx] = widgets

        header = f"{meta['sifu_name']} \nRequired: {meta['sil_required']}\n {meta['demand_mode_required']}"
        self.table.setVerticalHeaderItem(row_idx, QTableWidgetItem(header))

        effective = self._effective_demand_mode(row_idx)
        widgets.result.combo.setCurrentText(effective)
        widgets.result.override_changed.connect(lambda val, r=row_idx: self._on_row_override_changed(r, val))

        self.table.setCellWidget(row_idx, 0, widgets.in_list)
        self.table.setCellWidget(row_idx, 1, widgets.logic_list)
        self.table.setCellWidget(row_idx, 2, widgets.out_list)
        self.table.setCellWidget(row_idx, 3, widgets.result)

        self._update_row_height(row_idx)
        self.recalculate_row(row_idx)
        self._reapply_sifu_filter()

    # ----- Add Component dialog -----
    def open_add_component_dialog(self, pref_kind: Optional[str] = None, insert_into_row: bool = False):
        dlg = AddComponentDialog(self, pref_kind=pref_kind)
        if dlg.exec_():
            d = dlg.get_values()
            kind = d["kind"]
            if kind == "sensor":
                self.sensor_lib.add_component(d)
            elif kind == "logic":
                self.logic_lib.add_component(d)
            else:
                self.act_lib.add_component(d)

            if d.get("insert") or insert_into_row:
                if kind == "sensor":
                    self._add_sensor_to_current_row(d)
                elif kind == "logic":
                    self._add_logic_to_current_row(d)
                else:
                    self._add_actuator_to_current_row(d)

# ==========================
# Self tests (no GUI) — unchanged
# ==========================

def _assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected}, got {actual}")

def run_selftests() -> None:
    _assert_equal(classify_sil_from_pfh(1e-9), "SIL 4", "PFH lower SIL4 bound")
    _assert_equal(classify_sil_from_pfh(5e-9), "SIL 4", "PFH mid SIL4")
    _assert_equal(classify_sil_from_pfh(1e-8), "SIL 3", "PFH lower SIL3 bound")
    _assert_equal(classify_sil_from_pfh(5e-8), "SIL 3", "PFH mid SIL3")
    _assert_equal(classify_sil_from_pfh(1e-7), "SIL 2", "PFH lower SIL2 bound")
    _assert_equal(classify_sil_from_pfh(5e-7), "SIL 2", "PFH mid SIL2")
    _assert_equal(classify_sil_from_pfh(1e-6), "SIL 1", "PFH lower SIL1 bound")
    _assert_equal(classify_sil_from_pfh(5e-6), "SIL 1", "PFH mid SIL1")
    _assert_equal(classify_sil_from_pfh(5e-4), "n.a.", "PFH out of range")
    _assert_equal(classify_sil_from_pfd(1e-5), "SIL 4", "PFD lower SIL4 bound")
    _assert_equal(classify_sil_from_pfd(5e-5), "SIL 4", "PFD mid SIL4")
    _assert_equal(classify_sil_from_pfd(1e-4), "SIL 3", "PFD lower SIL3 bound")
    _assert_equal(classify_sil_from_pfd(5e-4), "SIL 3", "PFD mid SIL3")
    _assert_equal(classify_sil_from_pfd(1e-3), "SIL 2", "PFD lower SIL2 bound")
    _assert_equal(classify_sil_from_pfd(5e-3), "SIL 2", "PFD mid SIL2")
    _assert_equal(classify_sil_from_pfd(1e-2), "SIL 1", "PFD lower SIL1 bound")
    _assert_equal(classify_sil_from_pfd(5e-2), "SIL 1", "PFD mid SIL1")
    _assert_equal(sil_rank("SIL 3"), 3, "rank SIL 3")
    _assert_equal(sil_rank("2"), 2, "rank '2'")
    _assert_equal(normalize_required_sil("SIL 2"), ("SIL 2", 2), "normalize 'SIL 2'")
    _assert_equal(normalize_required_sil(3), ("SIL 3", 3), "normalize int 3")
    print("Selftests OK (classify_sil_*, ranks, normalize).")

# ==========================
# main
# ==========================

def main():
    df = load_sifu_dataframe()
    app = QApplication(sys.argv)
    win = MainWindow(df)
    win.show()
    sys.exit(app.exec_())



# ==========================
# Enhancements: Proposals B, C, F, G (English UI)
# ==========================
from PyQt5.QtWidgets import QToolBar, QToolButton, QMenu, QAction
from PyQt5 import QtCore

def _make_split_button(default_action: QAction, menu: QMenu) -> QToolButton:
    btn = QToolButton()
    btn.setDefaultAction(default_action)
    btn.setPopupMode(QToolButton.MenuButtonPopup)
    btn.setMenu(menu)
    return btn

class EnhancedMainWindow(MainWindow):
    """Adds full menubar (File/Edit/View/Tools/Help), split-buttons for Save/Export,
    context enablement for SIFU actions, and modern QSS for menubar/toolbar.
    """
    def __init__(self, df):
        super().__init__(df)
        # Rebuild menus & toolbar (clear any pre-existing bars from base)
        self._recent_files = []
        self._current_assignment_path = None
        try:
            self._load_recent_files()
        except Exception:
            self._recent_files = []
        self._rebuild_menubar()
        #self._rebuild_toolbar()
        self._install_context_enablement()
        self._apply_qss_menu_toolbar_theme()
        self.statusBar().showMessage('Enhanced UI (B/C/F/G) active', 2000)

    # ---------------------- Menubar (B) ----------------------
    def _rebuild_menubar(self):
        mb = self.menuBar(); mb.clear()
        # File
        m_file = mb.addMenu('&File')
        self.act_new = QAction('New Project', self); self.act_new.setShortcut('Ctrl+Shift+N')
        self.act_open = QAction('Open…', self); self.act_open.setShortcut('Ctrl+O')
        self.act_save = QAction('Save', self); self.act_save.setShortcut('Ctrl+S')
        self.act_save_as = QAction('Save As…', self)
        self.act_export_html = QAction('Export HTML', self); self.act_export_html.setShortcut('Ctrl+Shift+E')
        self.act_exit = QAction('Exit', self)
        # Icons
        self.act_new.setIcon(self.style().standardIcon(self.style().SP_FileIcon))
        self.act_open.setIcon(self.style().standardIcon(self.style().SP_DialogOpenButton))
        self.act_save.setIcon(self.style().standardIcon(self.style().SP_DialogSaveButton))
        self.act_save_as.setIcon(self.style().standardIcon(self.style().SP_DialogSaveButton))
        self.act_export_html.setIcon(self.style().standardIcon(self.style().SP_ArrowRight))
        # Wire
        self.act_new.triggered.connect(getattr(self, '_action_new_project', self._action_new_project_fallback))
        self.act_open.triggered.connect(self._file_open)
        self.act_save.triggered.connect(self._file_save)
        self.act_save_as.triggered.connect(self._file_save_as)
        self.act_export_html.triggered.connect(self._action_export_html_report)
        self.act_exit.triggered.connect(self.close)
        # Build menu
        m_file.addAction(self.act_new)
        m_file.addAction(self.act_open)
        self._recent_menu = m_file.addMenu('Open Recent')
        self._rebuild_recent_menu()
        m_file.addSeparator()
        m_file.addAction(self.act_save)
        m_file.addAction(self.act_save_as)
        m_file.addSeparator()
        m_file.addAction(self.act_export_html)
        m_file.addSeparator()
        m_file.addAction(self.act_exit)

        # Edit
        m_edit = mb.addMenu('&Edit')
        self.act_add_sifu = QAction('Add SIFU', self); self.act_add_sifu.setShortcut('Ctrl+N')
        self.act_edit_sifu = QAction('Edit SIFU', self); self.act_edit_sifu.setShortcut('Ctrl+E')
        self.act_dup_sifu = QAction('Duplicate SIFU', self); self.act_dup_sifu.setShortcut('Ctrl+D')
        self.act_rem_sifu = QAction('Remove SIFU', self); self.act_rem_sifu.setShortcut('Ctrl+Del')
        self.act_add_comp = QAction('Add Component…', self); self.act_add_comp.setShortcut('Ctrl+Alt+N')
        self.act_add_sifu.triggered.connect(self._action_add_sifu)
        self.act_edit_sifu.triggered.connect(self._action_edit_sifu)
        self.act_dup_sifu.triggered.connect(self._action_duplicate_sifu)
        self.act_rem_sifu.triggered.connect(self._action_remove_sifu)
        self.act_add_comp.triggered.connect(self.open_add_component_dialog)
        m_edit.addActions([self.act_add_sifu, self.act_edit_sifu, self.act_dup_sifu, self.act_rem_sifu])
        m_edit.addSeparator()
        m_edit.addAction(self.act_add_comp)

        # View (reuse existing toggles if any)
        m_view = mb.addMenu('&View')
        self.toggle_sensor = QAction('Sensor Library', self, checkable=True, checked=self.sensor_lib.isVisible())
        self.toggle_logic = QAction('Logic Library', self, checkable=True, checked=self.logic_lib.isVisible())
        self.toggle_act = QAction('Actuator Library', self, checkable=True, checked=self.act_lib.isVisible())
        self.toggle_sensor.triggered.connect(lambda b: self.sensor_lib.setVisible(b))
        self.toggle_logic.triggered.connect(lambda b: self.logic_lib.setVisible(b))
        self.toggle_act.triggered.connect(lambda b: self.act_lib.setVisible(b))
        # Keep menus in sync with dock visibility
        self.sensor_lib.visibilityChanged.connect(lambda b: self.toggle_sensor.setChecked(b))
        self.logic_lib.visibilityChanged.connect(lambda b: self.toggle_logic.setChecked(b))
        self.act_lib.visibilityChanged.connect(lambda b: self.toggle_act.setChecked(b))
        m_view.addActions([self.toggle_sensor, self.toggle_logic, self.toggle_act])

        # Tools
        m_tools = mb.addMenu('&Tools')
        self.act_config = QAction('Configuration…', self); self.act_config.setShortcut('Ctrl+,')
        self.act_config.setIcon(self.style().standardIcon(self.style().SP_FileDialogDetailedView))
        self.act_config.triggered.connect(self._open_config_dialog)
        m_tools.addAction(self.act_config)
        # Help
        m_help = mb.addMenu('&Help')
        self.act_shortcuts = QAction('Keyboard Shortcuts', self)
        def _show_shortcuts():
            QtWidgets.QMessageBox.information(self, 'Shortcuts',
                'New Project: Ctrl+Shift+N\n'
                'Open: Ctrl+O\n'
                'Save: Ctrl+S\n'
                'Export HTML: Ctrl+Shift+E\n'
                'Add SIFU: Ctrl+N | Edit: Ctrl+E | Duplicate: Ctrl+D | Remove: Ctrl+Del\n'
                'Add Component: Ctrl+Alt+N\n'
                'Filter SIFUs: Ctrl+F')
        self.act_shortcuts.triggered.connect(_show_shortcuts)
        m_help.addAction(self.act_shortcuts)

    # ---------------------- Toolbar with split buttons (C) ----------------------
    def _rebuild_toolbar(self):
        # Remove existing toolbars created by base
        for tb in self.findChildren(QToolBar):
            self.removeToolBar(tb)
        tb = QToolBar('Actions', self)
        tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        tb.setIconSize(QtCore.QSize(20, 20))
        self.addToolBar(tb)
        # File group
        tb.addAction(self.act_new)
        tb.addAction(self.act_open)
        # Save split
        m_save = QMenu(tb); m_save.addAction(self.act_save); m_save.addAction(self.act_save_as)
        btn_save = _make_split_button(self.act_save, m_save)
        tb.addWidget(btn_save)
        # Export split (currently HTML only)
        m_export = QMenu(tb); m_export.addAction(self.act_export_html)
        btn_export = _make_split_button(self.act_export_html, m_export)
        tb.addWidget(btn_export)
        tb.addAction(self.act_config)
        tb.addSeparator()
        # SIFU group
        tb.addAction(self.act_add_sifu)
        tb.addAction(self.act_edit_sifu)
        tb.addAction(self.act_dup_sifu)
        tb.addAction(self.act_rem_sifu)
        tb.addSeparator()
        tb.addAction(self.act_add_comp)

    # ---------------------- Context enablement (F) ----------------------
    def _install_context_enablement(self):
        def _sync():
            row = self.table.currentRow()
            valid = (0 <= row < self.table.rowCount())
            self.act_edit_sifu.setEnabled(valid)
            self.act_dup_sifu.setEnabled(valid)
            self.act_rem_sifu.setEnabled(valid)
        self.table.currentCellChanged.connect(lambda *_: _sync())
        _sync()

    # ---------------------- Menu/Toolbar QSS (G) ----------------------
    def _apply_qss_menu_toolbar_theme(self):
        bg0 = '#FFFFFF'; border = '#DADCE0'
        qss = f"""
        QMenuBar {{ background: {bg0}; border-bottom: 1px solid {border}; }}
        QMenuBar::item {{ padding: 4px 10px; margin: 0 2px; border-radius: 6px; }}
        QMenuBar::item:selected {{ background: #EEF5FF; color: #111; }}
        QMenu {{ background: {bg0}; border: 1px solid {border}; padding: 4px 0; }}
        QMenu::item {{ padding: 6px 14px; border-radius: 6px; }}
        QMenu::item:selected {{ background: #EEF5FF; color: #111; }}
        QToolBar {{ background: {bg0}; border-bottom: 1px solid {border}; spacing: 6px; }}
        QToolButton {{ padding: 4px 8px; border: 1px solid transparent; border-radius: 6px; }}
        QToolButton:hover {{ background: #F3F6FF; border-color: #E6ECFF; }}
        QToolButton:checked {{ background: #E6F0FF; border-color: #BFD2FF; }}
        """
        self.setStyleSheet(self.styleSheet() + qss)

    # ---------------------- Recent files + Save/Open helpers (B/C) ----------------------
    def _set_current_path(self, path: str):
        self._current_assignment_path = path
        base = os.path.basename(path) if path else None
        self.setWindowTitle(f"SIL Calculator — {base}" if base else 'SIL Calculator')
        if path:
            self._add_recent_file(path)

    def _file_open(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open', '', 'YAML (*.yaml *.yml)')
        if not path:
            return
        self._file_open_direct(path)

    def _file_open_direct(self, path: str):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            self._rebuild_from_payload(data)
            QMessageBox.information(self, 'Import', f'Imported from {path}.')
            self.statusBar().showMessage(f'Imported {os.path.basename(path)}', 2000)
            self._set_current_path(path)
        except Exception as e:
            QMessageBox.critical(self, 'Import failed', str(e))

    def _file_save(self):
        if not getattr(self, '_current_assignment_path', None):
            return self._file_save_as()
        try:
            payload = self._collect_assignment_payload()
            with open(self._current_assignment_path, 'w', encoding='utf-8') as f:
                yaml.dump(payload, f, sort_keys=False, allow_unicode=True, Dumper=NumpySafeDumper)
            self.statusBar().showMessage(f"Saved to {os.path.basename(self._current_assignment_path)}", 2000)
        except Exception as e:
            QMessageBox.critical(self, 'Save failed', str(e))

    def _file_save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save As', 'sifu_assignment.yaml', 'YAML (*.yaml *.yml)')
        if not path:
            return
        try:
            payload = self._collect_assignment_payload()
            with open(path, 'w', encoding='utf-8') as f:
                yaml.dump(payload, f, sort_keys=False, allow_unicode=True, Dumper=NumpySafeDumper)
            QMessageBox.information(self, 'Save', f'Saved to {path}.')
            self.statusBar().showMessage(f"Saved to {os.path.basename(path)}", 2000)
            self._set_current_path(path)
        except Exception as e:
            QMessageBox.critical(self, 'Save failed', str(e))

    # Recent list stored in existing QSettings
    def _load_recent_files(self):
        try:
            rf = self.settings.value('recent_files', [])
            if isinstance(rf, list):
                self._recent_files = [s for s in rf if isinstance(s, str) and os.path.exists(s)]
            else:
                self._recent_files = []
        except Exception:
            self._recent_files = []

    def _save_recent_files(self):
        self.settings.setValue('recent_files', self._recent_files[:10])

    def _add_recent_file(self, path: str):
        ap = os.path.abspath(path)
        self._recent_files = [p for p in self._recent_files if os.path.abspath(p) != ap]
        self._recent_files.insert(0, ap)
        self._recent_files = self._recent_files[:10]
        self._save_recent_files()
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        if not hasattr(self, '_recent_menu'):
            return
        self._recent_menu.clear()
        if not self._recent_files:
            dummy = QAction('(Empty)', self); dummy.setEnabled(False)
            self._recent_menu.addAction(dummy)
            return
        for p in self._recent_files:
            act = QAction(p, self)
            act.triggered.connect(lambda _=None, path=p: self._file_open_direct(path))
            self._recent_menu.addAction(act)
        self._recent_menu.addSeparator()
        clear_act = QAction('Clear Recent', self)
        def _clear():
            self._recent_files = []
            self._save_recent_files()
            self._rebuild_recent_menu()
        clear_act.triggered.connect(_clear)
        self._recent_menu.addAction(clear_act)



# ===== Enhanced entry point =====
def main_enhanced():
    df = load_sifu_dataframe()
    app = QApplication(sys.argv)
    win = EnhancedMainWindow(df)
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        run_selftests()
        sys.exit(0)
    main_enhanced()
