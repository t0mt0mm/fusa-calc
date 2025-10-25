# FuSa Calculator

## Overview
FuSa Calculator is a PyQt-based desktop tool for building and analysing Safety Functions (SIFUs). Within the application every safety function is managed as a **SIFU**—die Abkürzung für *Sicherheitsfunktion*, also “safety function”—with dedicated lanes for sensors, logic, and outputs. The tool calculates PFDavg and PFH metrics and exports HTML reports that visualise colour-coded component subgroups and their interconnections.

The repository ships with YAML libraries for sensors, logic, and actuators, sample assignments, and configuration hooks for importing Cause & Effect matrices or FuSa component catalogues.

## Features at a Glance
- **Lane-centric editor:** Manage each safety function (SIFU) across Sensor, Logic, and Output lanes with drag-and-drop chip widgets and in-place editing dialogs.
- **Link mode with colour-driven subgroups:** Assign components to cross-lane subgroups by choosing or picking a colour; linked chips show a coloured indicator dot, and the HTML export draws connectors between matching colours.
- **Live safety metrics:** Lane summaries and the overall SIFU result cell recompute immediately, and hover tooltips list subgroup totals alongside ungrouped contributions.
- **Rich exports:** Generate HTML dossiers featuring architecture overviews, subgroup summaries, connector lines, and formula references.
- **Data persistence:** Save or restore complete assignments (including subgroup colours) via YAML, or duplicate SIFUs while preserving metadata.

## Installation
1. Create and activate a virtual environment (optional but recommended).
2. Install dependencies:
   ```bash
   pip install PyQt5 PyYAML numpy pandas
   ```
   The GUI itself relies on PyQt5, while YAML import/export and numerical processing require PyYAML and NumPy. The helper scripts for spreadsheet integration expect pandas.

## Running the Application
Launch the enhanced GUI from the repository root:
```bash
python sifu_gui.py
```
Use `python sifu_gui.py --selftest` to run unit checks for SIL classification ranges.

### Loading Data
- **Assignment YAML:** Use *File → Open* to load `sifu_assignment.yaml` or your own export. All subgroup colours and connectors are restored.
- **Component libraries:** Sensor, logic, and actuator libraries are read from the YAML files in the repo and populate the add-component dialogs.
- **Cause & Effect imports:** Configure spreadsheet paths in `config.yaml` to pull safety-function definitions directly from project documentation.

## Daily Workflow
1. **Create or duplicate a SIFU:** Use the SIFU list to add, rename, or copy safety-function definitions.
2. **Populate lanes:** Drag existing chips or add new components via the toolbar. 1oo2 logic can be expanded into grouped widgets for redundant architectures.
3. **Edit component parameters:** Double-click a chip to adjust PFDavg, PFH, FIT, SIL capability, demand mode, or descriptive notes.
4. **Activate link mode:**
   - Toggle *Tools → Link mode* in the menubar or the toolbar button.
   - Choose a colour from *Tools → Link colour*; custom colours are supported.
   - Click chips across any lane to enrol or remove them from the active colour subgroup. Each chip shows a coloured dot; connectors are generated between every linked component following lane-specific edge rules.
5. **Inspect results:** Hover the overall result cell to see subgroup totals and ungrouped lane contributions in the current demand mode (PFDavg or PFH).
6. **Export:** Generate an HTML dossier via *File → Export → HTML report*. The report reproduces lane layouts, subgroup callouts, and connectors, followed by component tables and a formula appendix.

## Reliability Calculations
### Inputs
- **Demand mode:** Toggle between low-demand (PFDavg) and high-/continuous-demand (PFH) analysis; all lanes share the selection.
- **Component data:** Each chip stores PFDavg, PFH (1/h), FIT, SIL capability, beta factors, proof-test interval (TI), and mean time to repair (MTTR).

### Aggregation Rules
1. Components sharing the same normalised colour belong to one subgroup, independent of lane.
2. For each SIFU, the tool computes metrics per subgroup (summing all member channels once) and separately sums ungrouped components per lane.
3. The overall SIFU result is the sum of all subgroup totals plus every ungrouped component across the three lanes, ensuring each chip contributes exactly once.
4. Hover tooltips and HTML exports display subgroup membership, lane coverage, and PFD/PFH totals.

### Architecture Formulas
The HTML report’s formula appendix documents the governing equations:
- **1oo1 channel:**
  \[
  \mathrm{PFD}_{1oo1} = \lambda_{DU}\left(\tfrac{T_I}{2} + MTTR\right) + \lambda_{DD} MTTR
  \]
  \[
  \mathrm{PFH}_{1oo1} = \lambda_{DU}
  \]
- **1oo2 channel (beta model):**
  \[
  t_{CE} = \frac{\lambda_{DU}^{ind}}{\lambda_D^{ind}}\left(\tfrac{T_I}{2} + MTTR\right) + \frac{\lambda_{DD}^{ind}}{\lambda_D^{ind}} MTTR
  \]
  \[
  t_{GE} = \frac{\lambda_{DU}^{ind}}{\lambda_D^{ind}}\left(\tfrac{T_I}{3} + MTTR\right) + \frac{\lambda_{DD}^{ind}}{\lambda_D^{ind}} MTTR
  \]
  \[
  \mathrm{PFD}_{1oo2} = 2(1-\beta)^2(\lambda_D)^2 t_{CE} t_{GE} + \beta \lambda_{DU}\left(\tfrac{T_I}{2} + MTTR\right) + \beta_D \lambda_{DD} MTTR
  \]
  \[
  \mathrm{PFH}_{1oo2} = 2(1-\beta)\lambda_D^{ind}\lambda_{DU}^{ind} t_{CE} + \beta \lambda_{DU}
  \]
- **Supporting relations:**
  \(\lambda_D = \lambda_{DU} + \lambda_{DD}\), \(\lambda_{DU} = r_{DU}\lambda_D\), \(\lambda_{DD} = r_{DD}\lambda_D\), and \(\lambda_{DU}^{ind} = (1-\beta)\lambda_{DU}\).

## Reporting Highlights
- **Architecture overview:** Three-lane layout with per-chip dots and cross-lane connectors rendered via SVG; connector start and end points respect lane-specific rules (e.g., sensors connect from right edge to downstream lanes).
- **Subgroup summary box:** Lists each colour subgroup once, showing the colour swatch, participating lanes, member codes, and aggregated metrics.
- **Component tables & SIL summary:** Tabular breakdown of each lane plus SIL classification based on calculated sums.

## Keyboard & Productivity Tips
- `Ctrl+N` / `Ctrl+O` / `Ctrl+S` mirror the menubar file actions; toolbar buttons provide quick access.
- Right-click a lane to enter link mode from that context or to clear lane/SIFU subgroup assignments.
- Duplicate SIFUs to branch scenarios while preserving subgroup colours and demand modes.

## Troubleshooting
- **Missing Qt platform plugin:** Ensure PyQt5 is installed and your environment has access to a GUI backend (e.g., X11 on Linux, Windows subsystem, or macOS).
- **No connectors in HTML export:** Verify that components share the exact colour (hex or named) and that at least two lanes contain members; the exporter skips single-lane groups.
- **Unexpected SIL classification:** Run `python sifu_gui.py --selftest` to validate the classification boundaries.

## Licensing
Please refer to project documentation or contact the maintainers for licensing terms.
