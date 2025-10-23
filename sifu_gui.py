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
from typing import Dict, Tuple, List, Optional, Union, Any
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTableWidget, QTableWidgetItem, QListWidget, QListWidgetItem, QLabel, QDockWidget, QLineEdit, QToolBar, QAction, QToolButton, QFileDialog, QMessageBox, QHBoxLayout, QVBoxLayout, QFrame, QStyle, QDialog, QFormLayout, QDialogButtonBox, QDoubleSpinBox, QAbstractSpinBox, QComboBox, QSpinBox, QShortcut, QSizePolicy, QHeaderView, QAbstractItemView
)
from PyQt5.QtGui import QPainter, QColor, QFont, QPen, QKeySequence, QPixmap, QImage
from datetime import datetime
import yaml
import numpy as np
import html
from pathlib import Path
# ==========================


def new_instance_id() -> str:
    return uuid.uuid4().hex

# ==========================
# Tooltip helper (HTML)
# ==========================

def make_html_tooltip(title: str, pfd: Optional[float], pfh: Optional[float], syscap: Any,
                      pdm_code: str = "", pfh_entered_fit: Optional[float] = None,
                      pfd_entered_fit: Optional[float] = None,
                      extra_fields: Optional[Dict[str, Any]] = None) -> str:
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

    return f"<html><b>{esc(title)}</b><br><table>{''.join(rows)}</table></html>"

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
            'TI': 8760.0, 'MTTR': 8.0, 'beta': 0.1, 'beta_D': 0.02, 'C_PST': 0.3, 'T_PST': 168.0
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
        add_param('C_PST',"C_PST", 0, 1.0, 3, 0.01, "Proof test coverage constant.")
        add_param('T_PST',"T_PST", 0, 1e6, 2, 1.0, "Proof test duration.", "h")
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
            self.fields['C_PST'].setValue(self._defaults['C_PST'])
            self.fields['T_PST'].setValue(self._defaults['T_PST'])
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
# Result cell (badge + subtext + demand-mode combo)
# ==========================

class ResultCell(QWidget):
    override_changed = QtCore.pyqtSignal(str)  # 'High demand' or 'Low demand'
    def __init__(self, parent=None):
        super().__init__(parent)
        self.badge = QLabel("–")
        self.badge.setObjectName("SilBadge")
        self.badge.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Subtext lines
        self.lbl_demand = QLabel("–")
        self.lbl_req = QLabel("–")
        self.lbl_calc = QLabel("–")
        self.lbl_metric = QLabel("–")
        for lbl in (self.lbl_demand, self.lbl_req, self.lbl_calc, self.lbl_metric):
            lbl.setObjectName("ResultSubtext")

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
        self.combo.currentTextChanged.connect(lambda _t: (_shrink_to_content(), self.override_changed.emit(self.combo.currentText())))

        # Layout
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(3)
        left.addWidget(self.badge)

        demand_row = QHBoxLayout()
        demand_row.setContentsMargins(0, 0, 0, 0)
        demand_row.setSpacing(6)
        demand_row.addWidget(self.lbl_demand)
        demand_row.addWidget(self.combo)
        demand_row.addStretch(1)  # Combo klebt am Label, Rest filler
        left.addLayout(demand_row)

        left.addWidget(self.lbl_req)
        left.addWidget(self.lbl_calc)
        left.addWidget(self.lbl_metric)
        left.addStretch(1)

        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(10)
        root.addLayout(left, 1)

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
        kind = d.get("kind", "")
        text = d.get("code") or d.get("name") or item.text()

        w = QWidget()
        w.setProperty("kind", kind)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)

        lbl = QLabel(str(text))
        lbl.setObjectName("ChipLabel")
        lbl.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        lbl.adjustSize()
        lay.addWidget(lbl)

        # ensure enough vertical room
        w.setMinimumHeight(30)
        sh = w.sizeHint()
        try:
            h0 = sh.height()
            sh.setHeight(max(h0, 38))
        except Exception:
            pass
        item.setSizeHint(sh)
        self.setItemWidget(item, w)

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
        action = m.exec_(self.mapToGlobal(pos))
        if action == act_del:
            for item in self.selectedItems():
                self.takeItem(self.row(item))
            self.window().statusBar().showMessage("Removed component", 2000)
            self.window().recalculate_all()
        elif action == act_add:
            self.window().open_add_component_dialog(pref_kind=self.allowed_kind, insert_into_row=True)

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
        super().mousePressEvent(event)

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

                    widget = QWidget()
                    widget.setProperty("kind", "actuator")  # for accent styling
                    lay = QHBoxLayout(widget)
                    lay.setContentsMargins(8, 4, 8, 4)
                    lay.setSpacing(8)

                    # compact badge between chips
                    badge = QLabel("← 1oo2 →")
                    badge.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
                    badge.setStyleSheet(
                        "QLabel{color:#555; background:#eee; border:1px solid #ddd; "
                        "border-radius:10px; padding:4px 10px; font-size:11px;font-weight: bold}"
                    )
                    badge.setFixedWidth(badge.sizeHint().width())
                    badge.adjustSize()  # <-- passt die Größe an den Inhalt an

                    lay.addWidget(self._make_chip_label(t_name))
                    lay.addWidget(badge)
                    lay.addWidget(self._make_chip_label(s_name))

                    # ensure enough vertical room
                    widget.setMinimumHeight(30)
                    sh1 = widget.sizeHint()
                    try:
                        h01 = sh1.height()
                        sh1.setHeight(max(h01, 38))
                    except Exception:
                        pass
                    grp_item.setSizeHint(sh1)
                    self.setItemWidget(grp_item, widget)

                    self.takeItem(target_row)
                    self.insertItem(target_row, grp_item)
                    self.setItemWidget(grp_item, widget)

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

                    widget = QWidget()
                    widget.setProperty("kind", "sensor")
                    lay = QHBoxLayout(widget)
                    lay.setContentsMargins(8, 4, 8, 4)
                    lay.setSpacing(8)

                    badge = QLabel("← 1oo2 →")
                    badge.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
                    badge.setStyleSheet("QLabel{color:#555; background:#eee; border:1px solid #ddd; border-radius:10px; padding:4px 10px; font-size:11px;font-weight: bold}")
                    badge.setFixedWidth(badge.sizeHint().width())
                    badge.adjustSize()

                    lay.addWidget(self._make_chip_label(t_name))
                    lay.addWidget(badge)
                    lay.addWidget(self._make_chip_label(s_name))

                    widget.setMinimumHeight(30)
                    sh1 = widget.sizeHint()
                    try:
                        h01 = sh1.height()
                        sh1.setHeight(max(h01, 38))
                    except Exception:
                        pass
                    grp_item.setSizeHint(sh1)
                    self.setItemWidget(grp_item, widget)

                    self.takeItem(target_row)
                    self.insertItem(target_row, grp_item)
                    self.setItemWidget(grp_item, widget)

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
            'C_PST': 0.3,  # [–]
            'T_PST': 168.0 # [h]
        }
        self.du_dd_ratios = {'sensor': (0.7, 0.3), 'logic': (0.6, 0.4), 'actuator': (0.6, 0.4)}

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
        QWidget[kind="sensor"] {{ border-left:4px solid {sensor_accent}; padding-left:8px; }}
        QWidget[kind="logic"] {{ border-left:4px solid {logic_accent}; padding-left:8px; }}
        QWidget[kind="actuator"] {{ border-left:4px solid {actuator_accent}; padding-left:8px; }}

        QLabel#SilBadge {{
            font-weight:700; border:1px solid #cfcfcf; border-radius: 8px; padding: 6px 8px; background: {bg0}; color: #111;
        }}
        QLabel#SilBadge[state="ok"] {{ background: #E6F4EA; border-color: #98D8A4; color: {success}; }}
        QLabel#SilBadge[state="bad"]{{ background: #FEECEE; border-color: #F1B3B3; color: {danger}; }}

        QComboBox#DemandCombo {{
            padding: 1px 6px; border: 1px solid #cfcfcf; border-radius: 6px; background: {bg0};
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
        """Build an HTML tooltip for a 1oo2 group. Starts with <qt> so Qt renders it as HTML."""
        def esc(x: Any) -> str:
            s = "" if x is None else str(x)
            return html.escape(s)
        def fp(x):
            return "–" if x is None else f"{float(x):.6f}"
        def fh(x):
            return "–" if x is None else f"{float(x):.3e} 1/h"
        c1 = esc(m1.get("code", "?")); c2 = esc(m2.get("code", "?"))
        pfd1 = m1.get("pfd", m1.get("pfd_avg", None)); pfh1 = m1.get("pfh", m1.get("pfh_avg", None))
        pfd2 = m2.get("pfd", m2.get("pfd_avg", None)); pfh2 = m2.get("pfh", m2.get("pfh_avg", None))
        pfd_g = self._group_pfd_1oo2_grouped(m1, m2, group, mode_key)
        pfh_g = self._group_pfh_1oo2_grouped(m1, m2, group, mode_key)
        return (
            "<qt>"
            f"<div style='font-weight:600;'>1oo2 Group — {c1} ∥ {c2}</div>"
            "<table style='border-collapse:collapse; margin-top:4px;'>"
            "<tr><td style='padding-right:8px;'><b>PFDavg (group):</b></td>"
            f"<td>{fp(pfd_g)}</td></tr>"
            "<tr><td style='padding-right:8px;'><b>PFHavg (group):</b></td>"
            f"<td>{fh(pfh_g)}</td></tr>"
            "</table>"
            "<table style='border-collapse:collapse; margin-top:6px;'>"
            "<tr><th style='text-align:left;padding-right:10px;'>Member</th>"
            "<th style='text-align:left;padding-right:10px;'>PFDavg</th>"
            "<th style='text-align:left;'>PFHavg</th></tr>"
            f"<tr><td>{c1}</td><td>{fp(pfd1)}</td><td>{fh(pfh1)}</td></tr>"
            f"<tr><td>{c2}</td><td>{fp(pfd2)}</td><td>{fh(pfh2)}</td></tr>"
            "</table>"
            "</qt>"
        )

    def _refresh_group_tooltips_in_row(self, row_idx: int) -> None:
        """Update tooltips for all 1oo2 groups in Output/Actuator of the given row."""
        widgets = self.sifu_widgets.get(row_idx)
        if not widgets: return
        mode = self._effective_demand_mode(row_idx) if 0 <= row_idx < len(self.rows_meta) else ""
        mode_key = "low_demand" if "low" in str(mode).lower() else "high_demand"
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
                d = (it.data(Qt.UserRole) or {}).copy()

                # 1oo2-Gruppe separat behandeln
                if d.get("group") and d.get("architecture") == "1oo2":
                    members = d.get("members", [])
                    m1 = members[0] if len(members) > 0 else {}
                    m2 = members[1] if len(members) > 1 else {}
                    # Neues Gruppen-Item
                    grp_item = QListWidgetItem(f"{m1.get('code','?')} + {m2.get('code','?')}")
                    grp_item.setData(
                        Qt.UserRole,
                        {
                            "group": True,
                            "architecture": "1oo2",
                            "members": [m1.copy(), m2.copy()],
                            "kind": group_kind,
                        },
                    )
                    # Tooltip + Darstellung ähnlich wie beim Import
                    grp_item.setToolTip(self._tooltip_for_1oo2(m1, m2, group_kind))
                    widget = QWidget(); widget.setProperty("kind", group_kind)
                    lay = QHBoxLayout(widget); lay.setContentsMargins(8,4,8,4); lay.setSpacing(8)
                    badge = QLabel("1oo2"); badge.setStyleSheet(
                        "QLabel{font-size:11px; padding:4px 10px; border-radius:12px; background:#eee; border:1px solid #ddd;}"
                    )
                    # Reuse ChipList helper for members' labels
                    lblA = dst_widgets.out_list._make_chip_label(m1.get("code","?")) if group_kind=="actuator" else QLabel(m1.get("code","?"))
                    lblB = dst_widgets.out_list._make_chip_label(m2.get("code","?")) if group_kind=="actuator" else QLabel(m2.get("code","?"))
                    lay.addWidget(lblA); lay.addWidget(badge); lay.addWidget(lblB)
                    grp_item.setSizeHint(widget.sizeHint())
                    dst_list.addItem(grp_item)
                    dst_list.setItemWidget(grp_item, widget)
                else:
                    # Normales Einzel-Item neu erzeugen
                    name = d.get("name") or d.get("code") or "Item"
                    pfd = float(d.get("pfd", d.get("pfd_avg", 0.0)) or 0.0)
                    pfh = float(d.get("pfh", d.get("pfh_avg", 0.0)) or 0.0)
                    syscap = d.get("syscap", d.get("sys_cap", ""))
                    pdm = d.get("pdm_code", "")
                    pfh_fit = d.get("pfh_fit") if "pfh_fit" in d else None
                    pfd_fit = d.get("pfd_fit") if "pfd_fit" in d else None
                    new_item = self._make_item(str(name), pfd, pfh, syscap, pdm_code=pdm,
                                            kind=group_kind, pfh_fit=pfh_fit, pfd_fit=pfd_fit)
                    dst_list.addItem(new_item)
                    dst_list.attach_chip(new_item)

        _clone_list(src_widgets.in_list,    dst_widgets.in_list,    "sensor")
        _clone_list(src_widgets.logic_list, dst_widgets.logic_list, "logic")
        _clone_list(src_widgets.out_list,   dst_widgets.out_list,   "actuator")

        # --- Höhe und Ergebnis neu berechnen
        self._update_row_height(new_row)
        self.recalculate_row(new_row)
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
        return new_data

    def _build_html_report(self) -> str:
        '''Build a self-contained HTML report (print-friendly) with all SIFUs,
        their components, assumptions, DU/DD ratios and computed results.'''
        import html as _html
        from datetime import datetime as _dt
        dt = _dt.now().strftime('%Y-%m-%d %H:%M')

        def esc(x):
            return _html.escape('' if x is None else str(x))

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

        def fmt_fit(x):
            try:
                return f"{float(x) * 1e9:.2f}"
            except Exception:
                return "–"

        # Collect all data using existing helpers
        payload = {"sifus": []}
        for row_idx in range(len(self.rows_meta)):
            meta = self.rows_meta[row_idx]
            widgets = self.sifu_widgets[row_idx]
            sensors = self._collect_list_items(widgets.in_list)
            logic = self._collect_list_items(widgets.logic_list)
            outputs = self._collect_list_items(widgets.out_list)
            mode = self._effective_demand_mode(row_idx)
            mode_key = "low_demand" if "low" in mode.lower() else "high_demand"
            pfd_sum, pfh_sum = self._sum_lists((widgets.in_list, widgets.logic_list, widgets.out_list), mode_key)
            sil_calc = classify_sil_from_pfh(pfh_sum) if 'high' in mode.lower() else classify_sil_from_pfd(pfd_sum)
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
                "sil_calc": sil_calc,
                "ok": ok,
                "req_sil": req_sil_str,
                "uid": uid,
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
        .member-caption { display:block; color:#6b7280; font-size:11px; margin-top:2px; }
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
        .arch-lanes { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }
        .lane { border:1px solid #e5e7eb; border-radius:12px; padding:12px 14px; background:#fff; box-shadow:0 6px 18px rgba(15,23,42,0.04); display:flex; flex-direction:column; }
        .formula-section { margin: 32px 0 12px; }
        .formula-section > p { margin: 4px 0 18px; }
        .formula-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px; }
        .formula-card { border:1px solid #e5e7eb; border-radius:14px; padding:16px 18px; background:#f9fafb; box-shadow:0 8px 20px rgba(15,23,42,0.05); }
        .formula-card h4 { margin: 0 0 8px; font-size: 15px; }
        .formula { font-size: 15px; margin: 10px 0; text-align: center; }
        .formula-desc { color:#4b5563; font-size: 12px; line-height: 1.5; margin: 0 0 6px; }
        .variables-card { margin-top: 18px; }
        .variables-table { width: 100%; border-collapse: collapse; }
        .variables-table td { border: none; padding: 4px 8px; font-size: 12px; }
        .variables-table tr:nth-child(even) { background: transparent; }
        .variables-table td.symbol { font-family: 'STIX Two Math', 'Times New Roman', serif; white-space: nowrap; font-weight: 600; }
        .variables-table td.desc { color:#374151; }
        .lane-header { font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; color:#1f2937; margin-bottom:10px; }
        .lane-cards { display:flex; flex-direction:column; gap:4px; }
        .lane-card { border:1px solid #e5e7eb; border-radius:10px; padding:8px 10px; background:#f9fafb; border-left:4px solid transparent; display:flex; flex-direction:column; gap:6px; }
        .lane-card.group { background:#f5f3ff; border-color:#c7d2fe; border-left-color:#6366f1; }
        .lane-card.empty { border-style: dashed; color:#9ca3af; background:#fff; border-left-color:transparent; }
        .lane--sensors .lane-card { border-left-color:#0EA5E9; }
        .lane--logic .lane-card { border-left-color:#22C55E; }
        .lane--actuators .lane-card { border-left-color:#A855F7; }
        .lane-card-header { display:flex; align-items:center; justify-content:space-between; gap:8px; }
        .lane-title { font-size:13px; font-weight:600; color:#111827; margin:0; }
        .lane-subtitle { font-size:11px; color:#6b7280; margin:0; }
        .lane-metrics { display:flex; flex-wrap:wrap; gap:6px; font-size:11px; color:#374151; }
        .lane-metrics span { white-space:nowrap; padding:0 6px; border-radius:999px; background:#fff; border:1px solid #e5e7eb; }
        .lane-pill { display:inline-flex; align-items:center; padding:2px 6px; border-radius:999px; background:#e5e7eb; color:#374151; font-size:10px; letter-spacing:0.05em; text-transform:uppercase; }
        .lane-members { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:4px; }
        .lane-member { border:1px solid #d1d5db; border-radius:8px; padding:4px 6px; background:#fff; border-left:3px solid transparent; display:flex; flex-direction:column; gap:4px; }
        .lane--sensors .lane-member { border-left-color:#0EA5E9; }
        .lane--logic .lane-member { border-left-color:#22C55E; }
        .lane--actuators .lane-member { border-left-color:#A855F7; }
        .lane-member h4 { font-size:11px; margin:0; color:#1f2937; }
        .lane-member .lane-metrics { margin:0; gap:4px; font-size:10px; }
        .lane-member .lane-metrics span { background:#f8fafc; border:1px solid #e2e8f0; padding:0 5px; }
        .lane-group-meta { font-size:11px; color:#4b5563; }
        .lane-note { font-size:11px; color:#6b7280; margin-top:4px; }
        @media print { .page { padding: 0; } .no-print { display:none; } }
        '''

        def build_architecture_lanes(sensors: List[dict], logic: List[dict], actuators: List[dict]) -> str:
            stage_defs = [
                ("sensors", "Sensors / Inputs", sensors or []),
                ("logic", "Logic", logic or []),
                ("actuators", "Outputs / Actuators", actuators or []),
            ]

            stage_payload: List[Tuple[str, str, List[Dict[str, Any]]]] = []

            for stage_key, stage_title, entries in stage_defs:
                cards: List[Dict[str, Any]] = []
                for idx, entry in enumerate(entries):
                    architecture = entry.get("architecture")
                    instance_id = entry.get("instance_id") if isinstance(entry.get("instance_id"), str) else None
                    base_label = entry.get("code") or entry.get("name") or f"{stage_title} {idx + 1}"
                    pfd_val = entry.get("pfd_avg", entry.get("pfd"))
                    pfh_val = entry.get("pfh_avg", entry.get("pfh"))
                    sil_val = entry.get("sys_cap", entry.get("syscap", ""))
                    pdm_val = entry.get("pdm_code", "")

                    if architecture == "1oo2" and entry.get("members"):
                        members_payload: List[Dict[str, Any]] = []
                        member_codes: List[str] = []
                        for m_idx, member in enumerate(entry.get("members", [])):
                            if not isinstance(member, dict):
                                continue
                            member_label = member.get("code") or member.get("name") or f"Member {m_idx + 1}"
                            member_codes.append(member_label)
                            members_payload.append({
                                "label": member_label,
                                "name": member.get("name"),
                                "pfd": member.get("pfd_avg", member.get("pfd")),
                                "pfh": member.get("pfh_avg", member.get("pfh")),
                                "sil": member.get("sys_cap", member.get("syscap", "")),
                                "pdm": member.get("pdm_code", ""),
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
                        })

                stage_payload.append((stage_key, stage_title, cards))

            if all(not cards for _, _, cards in stage_payload):
                return ""

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

            html_parts: List[str] = ['<div class="arch-lanes">']
            for stage_key, stage_title, cards in stage_payload:
                html_parts.append(f'<div class="lane lane--{stage_key}">')
                html_parts.append(f'<div class="lane-header">{esc(stage_title)}</div>')
                html_parts.append('<div class="lane-cards">')
                if not cards:
                    html_parts.append('<div class="lane-card empty">No components listed</div>')
                for card in cards:
                    classes = ["lane-card"]
                    if card["type"] == "group":
                        classes.append("group")
                    class_attr = " ".join(classes)
                    html_parts.append(f'<div class="{class_attr}">')
                    html_parts.append('<div class="lane-card-header">')
                    html_parts.append(f'<div class="lane-title">{esc(card["label"])}</div>')
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
                    if card["type"] == "group":
                        members = card.get("members", [])
                        if members:
                            html_parts.append(f'<div class="lane-group-meta">Members ({len(members)})</div>')
                            html_parts.append('<div class="lane-members">')
                            for member in members:
                                html_parts.append('<div class="lane-member">')
                                html_parts.append(f'<h4>{esc(member.get("label", "Member"))}</h4>')
                                member_metrics = render_metrics(member.get("pfd"), member.get("pfh"), member.get("sil"), member.get("pdm"))
                                if member_metrics:
                                    html_parts.append(member_metrics)
                                else:
                                    html_parts.append('<div class="lane-note">No reliability data</div>')
                                html_parts.append('</div>')
                            html_parts.append('</div>')
                        else:
                            html_parts.append('<div class="lane-note">Group members unavailable</div>')
                    html_parts.append('</div>')
                html_parts.append('</div>')
                html_parts.append('</div>')
            html_parts.append('</div>')
            return ''.join(html_parts)

        # Build HTML
        parts = []
        parts.append('<!doctype html><html><head><meta charset="utf-8">')
        parts.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
        parts.append('<title>SIFU Report</title>')
        parts.append('<script>window.MathJax = {tex: {inlineMath: [["$","$"],["\\(","\\)"]], displayMath: [["\\[","\\]"],["$$","$$"]]}};</script>')
        parts.append('<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>')
        parts.append(f'<style>{css}</style>')
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

        # Assumptions & Ratios
        parts.append('<div class="grid">')
        parts.append('<div class="card">')
        parts.append('<h3>Global Assumptions</h3>')
        parts.append('<table><tbody>')
        parts.append(f'<tr><th>TI — Proof-test interval [h]</th><td class="right">{asm.get("TI", 0):.2f}</td></tr>')
        parts.append(f'<tr><th>MTTR — Mean time to repair [h]</th><td class="right">{asm.get("MTTR", 0):.2f}</td></tr>')
        parts.append(f'<tr><th>beta — CCF (DU) [–]</th><td class="right">{asm.get("beta", 0):.4f}</td></tr>')
        parts.append(f'<tr><th>beta_D — CCF (DD) [–]</th><td class="right">{asm.get("beta_D", 0):.4f}</td></tr>')
        parts.append(f'<tr><th>C_PST [–]</th><td class="right">{asm.get("C_PST", 0):.3f}</td></tr>')
        parts.append(f'<tr><th>T_PST [h]</th><td class="right">{asm.get("T_PST", 0):.2f}</td></tr>')
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

        # Base formulas
        parts.append('<div class="formula-section">')
        parts.append('<h2>Base Formulas</h2>')
        parts.append('<p class="muted small">Reference relations for IEC 61508 compliant assessments of simple 1oo1 and 1oo2 safety functions.</p>')
        parts.append('<div class="formula-grid">')
        parts.append('<div class="formula-card">')
        parts.append('<h4>1oo1 Architecture</h4>')
        parts.append('<p class="formula">\\[\mathrm{PFD}_{1oo1} = \lambda_{DU}\,(T_I/2 + MTTR) + \lambda_{DD}\,MTTR\\]</p>')
        parts.append('<p class="formula-desc">Average probability of dangerous failure on demand while the channel is in operation, proof testing, or repair.</p>')
        parts.append('<p class="formula">\\[\mathrm{PFH}_{1oo1} = \lambda_{DU}\\]</p>')
        parts.append('<p class="formula-desc">Dangerous failure rate in high or continuous demand scenarios for a single channel.</p>')
        parts.append('</div>')
        parts.append('<div class="formula-card">')
        parts.append('<h4>1oo2 Architecture</h4>')
        parts.append('<p class="formula">\\[t_{CE} = \frac{1}{2(1-\beta)\,\lambda_{DU,ind} + 2(1-\beta_D)\,\lambda_{DD,ind}}\\]</p>')
        parts.append('<p class="formula-desc">Mean exposure time until the first channel becomes dangerous undetected, considering independent and detected portions.</p>')
        parts.append('<p class="formula">\\[t_{GE} = t_{CE} + MTTR\\]</p>')
        parts.append('<p class="formula-desc">Mean time window where both channels can be unavailable, combining exposure and repair.</p>')
        parts.append('<p class="formula">\\[\mathrm{PFD}_{ind} = 2(1-\beta)\,\lambda_{DU,ind}\,t_{CE} + \frac{(1-\beta)^2\,\lambda_{DU,ind}^2\,(T_I/2 + MTTR)^2}{3}\\]</p>')
        parts.append('<p class="formula-desc">Average probability contribution from independent dangerous undetected failures.</p>')
        parts.append('<p class="formula">\\[\mathrm{PFD}_{CCF} = \beta\,\lambda_{DU}\,(T_I/2 + MTTR)\\]</p>')
        parts.append('<p class="formula-desc">Common-cause contribution that mirrors the exposure of a single channel.</p>')
        parts.append('<p class="formula">\\[\mathrm{PFD}_{1oo2} = \mathrm{PFD}_{ind} + \mathrm{PFD}_{CCF}\\]</p>')
        parts.append('<p class="formula-desc">Total average probability of failure on demand for a 1oo2 redundant set.</p>')
        parts.append('<p class="formula">\\[\mathrm{PFH}_{1oo2} = 2(1-\beta)\,\lambda_{DU,ind}\,t_{CE} + \beta\,\lambda_{DU}\\]</p>')
        parts.append('<p class="formula-desc">Dangerous failure rate combining independent and common-cause parts.</p>')
        parts.append('</div>')
        parts.append('<div class="formula-card variables-card">')
        parts.append('<h4>Variable Summary</h4>')
        parts.append('<table class="variables-table">')
        parts.append('<tr><td class="symbol">\lambda_D</td><td class="desc">total dangerous failure rate</td></tr>')
        parts.append('<tr><td class="symbol">\lambda_{DU}</td><td class="desc">dangerous undetected failure rate</td></tr>')
        parts.append('<tr><td class="symbol">\lambda_{DD}</td><td class="desc">dangerous detected failure rate</td></tr>')
        parts.append('<tr><td class="symbol">\lambda_{DU,ind}</td><td class="desc">independent portion of \(\lambda_{DU}\)</td></tr>')
        parts.append('<tr><td class="symbol">\lambda_{DD,ind}</td><td class="desc">independent portion of \(\lambda_{DD}\)</td></tr>')
        parts.append('<tr><td class="symbol">\beta,\;\beta_D</td><td class="desc">common-cause factors for undetected / detected failures</td></tr>')
        parts.append('<tr><td class="symbol">T_I</td><td class="desc">proof-test interval</td></tr>')
        parts.append('<tr><td class="symbol">MTTR</td><td class="desc">mean time to repair</td></tr>')
        parts.append('<tr><td class="symbol">t_{CE}</td><td class="desc">channel exposure time (first failure window)</td></tr>')
        parts.append('<tr><td class="symbol">t_{GE}</td><td class="desc">global exposure time until both channels fail</td></tr>')
        parts.append('<tr><td class="symbol">r_{DU},\;r_{DD}</td><td class="desc">DU / DD ratios per subsystem</td></tr>')
        parts.append('</table>')
        parts.append('<p class="formula-desc">Independent failure rates relate via \(\lambda_{DU,ind} = (1-\beta)\lambda_{DU}\) and \(\lambda_{DD,ind} = (1-\beta_D)\lambda_{DD}\); the total dangerous rate is \(\lambda_D = \lambda_{DU} + \lambda_{DD}\).</p>')
        parts.append('</div>')
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

            arch_html = build_architecture_lanes(s['sensors'], s['logic'], s['actuators'])
            if arch_html:
                parts.append('<div class="architecture">')
                parts.append('<h3>Architecture overview</h3>')
                parts.append(arch_html)
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
                        parts.append('<tr class="group-row">'
                                     f'<td><div class="group-label"><span class="pill arch">1oo2</span>'
                                     f'<span class="group-title">{esc(group_title)}</span></div></td>'
                                     f'<td class="right">{fmt_pfd(pfd_g)}</td>'
                                     f'<td class="right">{fmt_pfh(pfh_g)}</td>'
                                     f'<td class="right">{fmt_fit(pfh_g)}</td>'
                                     '<td>—</td><td>—</td></tr>')
                        for m_idx, m in enumerate(members, 1):
                            code_val = m.get('code') or m.get('name') or f'Member {m_idx}'
                            name_val = m.get('name')
                            label_html = f'<span class="member-tag">{esc(code_val)}</span>'
                            if name_val and name_val != code_val:
                                label_html += f'<span class="member-caption">{esc(name_val)}</span>'
                            parts.append('<tr class="group-member">'
                                         f'<td>{label_html}</td>'
                                         f'<td class="right">{fmt_pfd(m.get("pfd_avg", m.get("pfd")))}</td>'
                                         f'<td class="right">{fmt_pfh(m.get("pfh_avg", m.get("pfh")))}</td>'
                                         f'<td class="right">{fmt_fit(m.get("pfh_avg", m.get("pfh")))}</td>'
                                         f'<td>{esc(m.get("sys_cap", m.get("syscap", "")) or "—")}</td>'
                                         f'<td>{esc(m.get("pdm_code", "") or "—")}</td>'
                                         '</tr>')
                    else:
                        parts.append('<tr>'
                                     f'<td>{esc(it.get("code", it.get("name","?")))}</td>'
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
        parts.append('</div></body></html>')

        return '\n'.join(parts)

    def _collect_assignment_payload(self) -> dict:
        out = {"sifus": []}
        for row_idx in range(len(self.rows_meta)):
            meta = self.rows_meta[row_idx]
            widgets = self.sifu_widgets[row_idx]
            sensors = self._collect_list_items(widgets.in_list)
            logic   = self._collect_list_items(widgets.logic_list)
            outputs = self._collect_list_items(widgets.out_list)
            mode = self._effective_demand_mode(row_idx)
            mode_key = "low_demand" if "low" in mode.lower() else "high_demand"
            pfd_sum, pfh_sum = self._sum_lists((widgets.in_list, widgets.logic_list, widgets.out_list), mode_key)
            sil_calc = classify_sil_from_pfh(pfh_sum) if "high" in mode.lower() else classify_sil_from_pfd(pfd_sum)
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
                    m1, m2 = act.get("members", [{}, {}])
                    t_name = m1.get("code", "?"); s_name = m2.get("code", "?")
                    members: List[dict] = []
                    for payload in (m1, m2):
                        payload = copy.deepcopy(payload)
                        if not isinstance(payload.get('instance_id'), str) or not payload.get('instance_id'):
                            payload['instance_id'] = new_instance_id()
                        members.append(payload)
                    grp_item = QListWidgetItem(f"{t_name} + {s_name}")
                    grp_item.setData(Qt.UserRole, {'group': True, 'architecture': '1oo2', 'members': members, 'kind': 'actuator', 'instance_id': act.get('instance_id', new_instance_id())})
                    # Tooltip
                    tooltip_m1 = members[0] if members else {}
                    tooltip_m2 = members[1] if len(members) > 1 else {}
                    grp_item.setToolTip(self._tooltip_for_1oo2(tooltip_m1, tooltip_m2, "actuator"))
                    widget = QWidget(); widget.setProperty("kind", "actuator")
                    lay = QHBoxLayout(widget); lay.setContentsMargins(8,4,8,4); lay.setSpacing(8)
                    badge = QLabel("1oo2"); badge.setStyleSheet("QLabel{font-size:11px; padding:4px 10px; border-radius:12px; background:#eee; border:1px solid #ddd;}")
                    lay.addWidget(self.sifu_widgets[row_idx].out_list._make_chip_label(t_name))
                    lay.addWidget(badge)
                    lay.addWidget(self.sifu_widgets[row_idx].out_list._make_chip_label(s_name))
                    grp_item.setSizeHint(widget.sizeHint())
                    widgets.out_list.addItem(grp_item); widgets.out_list.setItemWidget(grp_item, widget)
                else:
                    item = self._make_item(act.get("code", "?"), act.get("pfd_avg", 0.0), act.get("pfh_avg", 0.0), act.get("sys_cap", ""), act.get("pdm_code", ""), kind="actuator", extra_fields=act)
                    widgets.out_list.addItem(item)
                    widgets.out_list.attach_chip(item)

            self._update_row_height(row_idx)

        if self.table.columnCount() == 4:
            self.table.setColumnWidth(0, 360); self.table.setColumnWidth(1, 300); self.table.setColumnWidth(2, 360)

        self.recalculate_all()

    # ----- collect list items -----
    def _collect_list_items(self, lw: QListWidget) -> List[dict]:
        items: List[dict] = []
        for i in range(lw.count()):
            item = lw.item(i)
            if not item:
                continue
            d = item.data(Qt.UserRole) or {}
            if d.get('group') and d.get('architecture') == '1oo2':
                normalized_members: List[dict] = []
                members_payload: List[dict] = []
                for member in d.get('members', []):
                    if not isinstance(member, dict):
                        continue
                    member_copy = copy.deepcopy(member)
                    member_id = member_copy.get('instance_id')
                    if not isinstance(member_id, str) or not member_id:
                        member_id = new_instance_id()
                        member_copy['instance_id'] = member_id
                    normalized_members.append(member_copy)
                    members_payload.append({
                        'code': member_copy.get('code'),
                        'name': member_copy.get('name'),
                        'pfd_avg': float(member_copy.get('pfd', member_copy.get('pfd_avg', 0.0)) or 0.0),
                        'pfh_avg': float(member_copy.get('pfh', member_copy.get('pfh_avg', 0.0)) or 0.0),
                        'sys_cap': member_copy.get('sys_cap', member_copy.get('syscap', '')),
                        'pdm_code': member_copy.get('pdm_code'),
                        'instance_id': member_id,
                    })
                if normalized_members != d.get('members'):
                    new_payload = copy.deepcopy(d)
                    new_payload['members'] = normalized_members
                    item.setData(Qt.UserRole, new_payload)
                    d = new_payload
                member_a = normalized_members[0] if normalized_members else {}
                member_b = normalized_members[1] if len(normalized_members) > 1 else {}
                pfd_grp = self._group_pfd_1oo2_grouped(member_a, member_b, 'actuator')
                pfh_grp = self._group_pfh_1oo2_grouped(member_a, member_b, 'actuator')
                items.append({
                    'architecture': '1oo2',
                    'members': members_payload,
                    'pfd_avg': float(pfd_grp),
                    'pfh_avg': float(pfh_grp),
                    'instance_id': d.get('instance_id'),
                })
            else:
                inst_id = d.get('instance_id')
                if not isinstance(inst_id, str) or not inst_id:
                    inst_id = new_instance_id()
                    d = copy.deepcopy(d)
                    d['instance_id'] = inst_id
                    item.setData(Qt.UserRole, d)
                items.append({
                    'code': d.get('code') or d.get('name'),
                    'name': d.get('name'),
                    'pfd_avg': float(d.get('pfd', 0.0)),
                    'pfh_avg': float(d.get('pfh', 0.0)),
                    'sys_cap': d.get('syscap', d.get('sys_cap', '')),
                    'pdm_code': d.get('pdm_code', ''),
                    'kind': d.get('kind'),
                    'instance_id': inst_id,
                })
        return items

    # ----- effective mode -----
    def _effective_demand_mode(self, row_idx: int) -> str:
        meta = self.rows_meta[row_idx]
        return meta.get("demand_mode_override") or meta.get("demand_mode_required", "High demand")

    # ----- sums + display (math unchanged) -----
    def _lambda_from_component(self, d: dict, mode_key: str) -> float:
        TI = float(self.assumptions['TI'])
        pfd = float(d.get('pfd', d.get('pfd_avg', 0.0)))
        pfh = float(d.get('pfh', d.get('pfh_avg', 0.0)))
        if mode_key == "low_demand":
            return (2.0 * pfd / TI) if TI > 0 else 0.0
        return pfh

    def _ratios(self, group: str) -> Tuple[float, float]:
        du, dd = self.du_dd_ratios.get(group, (0.6, 0.4))
        tot = du + dd
        if tot <= 0: return 0.6, 0.4
        return du / tot, dd / tot

    def _estimate_lambda_dd(self, pfd: float, pfh: float, group: str,
                            mode_key: str = "low_demand") -> float:
        TI = float(self.assumptions['TI'])
        if mode_key == "low_demand":
            lam = (2.0 * pfd / TI) if TI > 0 else 0.0
        else:
            lam = float(pfh)
        du_ratio, dd_ratio = self._ratios(group)
        return lam * (dd_ratio if du_ratio == 0 else (dd_ratio / du_ratio))

    def _group_pfd_1oo2_grouped(self, d1: dict, d2: dict, group: str,
                                mode_key: str = "low_demand") -> float:
        beta = float(self.assumptions['beta']); beta_D = float(self.assumptions['beta_D'])
        TI = float(self.assumptions['TI']); MTTR = float(self.assumptions['MTTR'])
        du_ratio, dd_ratio = self._ratios(group)
        lam1 = self._lambda_from_component(d1, mode_key)
        lam2 = self._lambda_from_component(d2, mode_key)
        lam_du_1 = du_ratio * lam1; lam_du_2 = du_ratio * lam2
        lam_dd_1 = dd_ratio * lam1; lam_dd_2 = dd_ratio * lam2
        lam_du_total = lam_du_1 + lam_du_2
        lam_dd_total = lam_dd_1 + lam_dd_2
        lam_du_ind = (1.0 - beta) * lam_du_total
        lam_dd_ind = (1.0 - beta_D) * lam_dd_total
        lam_d_ind = lam_du_ind + lam_dd_ind
        if lam_d_ind <= 0.0:
            pfd_ind = 0.0
            tCE = 0.0
            tGE = 0.0
        else:
            w_DU = lam_du_ind / lam_d_ind
            w_DD = lam_dd_ind / lam_d_ind
            tCE = w_DU * (TI / 2.0 + MTTR) + w_DD * MTTR
            tGE = w_DU * (TI / 3.0 + MTTR) + w_DD * MTTR
            pfd_ind = 2.0 * (lam_d_ind ** 2) * tCE * tGE
        pfd_du_ccf = beta * lam_du_total * (TI / 2.0 + MTTR)
        pfd_dd_ccf = beta_D * lam_dd_total * MTTR
        return pfd_ind + pfd_du_ccf + pfd_dd_ccf

    def _group_pfh_1oo2_grouped(self, d1: dict, d2: dict, group: str,
                                mode_key: str = "low_demand") -> float:
        beta = float(self.assumptions['beta']); beta_D = float(self.assumptions['beta_D'])
        MTTR = float(self.assumptions['MTTR']); TI = float(self.assumptions.get('TI', 0.0))
        du_ratio, dd_ratio = self._ratios(group)
        lam1 = self._lambda_from_component(d1, mode_key)
        lam2 = self._lambda_from_component(d2, mode_key)
        lam_du_1 = du_ratio * lam1; lam_du_2 = du_ratio * lam2
        lam_dd_1 = dd_ratio * lam1; lam_dd_2 = dd_ratio * lam2
        lam_du_total = lam_du_1 + lam_du_2
        lam_dd_total = lam_dd_1 + lam_dd_2
        lam_du_ind = (1.0 - beta) * lam_du_total
        lam_dd_ind = (1.0 - beta_D) * lam_dd_total
        lam_d_ind = lam_du_ind + lam_dd_ind
        if lam_d_ind <= 0.0:
            pfh_ind = 0.0
            tCE = 0.0
        else:
            w_DU = lam_du_ind / lam_d_ind
            w_DD = lam_dd_ind / lam_d_ind
            tCE = w_DU * (TI / 2.0 + MTTR) + w_DD * MTTR
            pfh_ind = 2.0 * lam_d_ind * lam_du_ind * tCE
        pfh_ccf = beta * lam_du_total
        return pfh_ind + pfh_ccf

    def _sum_lists(self, lists: Tuple[QListWidget, QListWidget, QListWidget],
                   mode_key: str) -> Tuple[float, float]:
        pfd_sum = 0.0; pfh_sum = 0.0
        TI = float(self.assumptions['TI']); MTTR = float(self.assumptions['MTTR'])

        def group_of(idx: int) -> str:
            return ('sensor', 'logic', 'actuator')[idx]

        for idx, lw in enumerate(lists):
            group = group_of(idx)
            for i in range(lw.count()):
                item = lw.item(i)
                if item is None: continue
                ud = item.data(Qt.UserRole) or {}
                if ud.get('group') and ud.get('architecture') == '1oo2':
                    m1, m2 = ud.get('members', [{}, {}])
                    pfd_sum += self._group_pfd_1oo2_grouped(m1, m2, group, mode_key)
                    pfh_sum += self._group_pfh_1oo2_grouped(m1, m2, group, mode_key)
                else:
                    lam = self._lambda_from_component(ud, mode_key)
                    du_ratio, dd_ratio = self._ratios(group)
                    lam_DU = du_ratio * lam; lam_DD = dd_ratio * lam
                    pfh_sum += lam_DU
                    pfd_sum += lam_DU * (TI / 2.0 + MTTR) + lam_DD * MTTR

        return pfd_sum, pfh_sum

    # ----- recalc & UI update -----
    def recalculate_row(self, row_idx: int):
        if row_idx < 0 or row_idx >= len(self.rows_meta): return
        widgets = self.sifu_widgets.get(row_idx)
        if not widgets: return  # can happen after remove
        mode = self._effective_demand_mode(row_idx)
        mode_key = "low_demand" if "low" in mode.lower() else "high_demand"
        pfd_sum, pfh_sum = self._sum_lists((widgets.in_list, widgets.logic_list, widgets.out_list), mode_key)
        is_high = (mode_key == "high_demand")
        if is_high:
            sil_calc = classify_sil_from_pfh(pfh_sum)
            metric = f"PFHsum = {pfh_sum:.3e} 1/h"
            demand_txt = "High demand"
        else:
            sil_calc = classify_sil_from_pfd(pfd_sum)
            metric = f"PFDsum = {pfd_sum:.6f} (–)"
            demand_txt = "Low demand"

        req_sil_str, req_rank_raw = normalize_required_sil(self.rows_meta[row_idx].get('sil_required', 'n.a.'))
        req_rank = int(req_rank_raw)
        calc_rank = sil_rank(sil_calc)
        ok = (calc_rank >= req_rank) and (calc_rank > 0)

        widgets.result.badge.setText(f"{sil_calc} {'✓' if ok else '✕'}")
        widgets.result.badge.setProperty("state", "ok" if ok else "bad")
        widgets.result.badge.style().unpolish(widgets.result.badge); widgets.result.badge.style().polish(widgets.result.badge)

        widgets.result.lbl_demand.setText(f"Demand mode:")
        widgets.result.combo.setCurrentText(demand_txt)
        widgets.result.lbl_req.setText(f"Required: {req_sil_str}")
        widgets.result.lbl_calc.setText(f"Calculated: {sil_calc}")
        widgets.result.lbl_metric.setText(metric)
        widgets.result.setToolTip(f"{demand_txt}\nRequired: {req_sil_str}\nCalculated: {sil_calc}\n{metric}")

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
        # Clear table & metadata (keep libraries)
        self.table.clearContents(); self.table.setRowCount(0)
        self.rows_meta.clear(); self.sifu_widgets.clear()
        self.recalculate_all()
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
        # Clear table & metadata (keep libraries)
        self.table.clearContents(); self.table.setRowCount(0)
        self.rows_meta.clear(); self.sifu_widgets.clear()
        self.recalculate_all()
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
