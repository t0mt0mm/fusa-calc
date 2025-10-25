# FuSa Calculator

## Overview
FuSa Calculator is a PyQt-based desktop tool for building and analysing Safety Functions (SIFUs). Within the application every safety function is managed as a **SIFU**—the German abbreviation for *Sicherheitsfunktion*, i.e. “safety function”—with dedicated lanes for sensors, logic, and outputs. The tool calculates PFDavg and PFH metrics and exports HTML reports that visualise colour-coded component subgroups and their interconnections.

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
Launch the enhanced GUI from the repository root by executing the Python entry point included alongside this README.
Use the optional `--selftest` flag on that entry point to run unit checks for SIL classification ranges.

### Loading Data
- **Assignment exports:** Use *File → Open* to load previously saved safety-function collections. All subgroup colours and connectors are restored.
- **Component libraries:** Sensor, logic, and actuator libraries are read from the bundled YAML resources and populate the add-component dialogs.
- **Cause & Effect imports:** Configure spreadsheet paths in the project settings to pull safety-function definitions directly from project documentation. The expected workbook layout is described in the documentation folder.

## Docs folder & spreadsheet structure
The default configuration expects three artefacts inside the documentation directory:

- **Cause & Effect matrix workbook:** Contains the safety-function definitions that seed new SIFUs. Use the worksheet dedicated to the matrix (data typically starts on the fourth row). Required columns include status flags, SIFU labels, SIL levels, demand-mode keywords, and the safety-action description and reference. Keep supporting lookup terms in a separate definitions sheet so actuator substitution rules resolve correctly.
- **E/E overview workbook:** Maps plant identifiers (PID) to hardware modules used for component lookup. Multiple worksheets split the data by subsystem; each sheet starts on the third row with PID codes in column B and hardware identifiers in column C.
- **FuSa component catalogue (CSV):** Provides reliability master data per component, including identifiers and the properties referenced by the configuration (for example PFDavg, PFH, system capability, proof-test intervals, and repair times).

If you adapt the structure, update the relevant settings in the configuration so the import routines can parse the spreadsheets correctly.

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

## Automated Verification & Qualification Support
- A dedicated pytest suite exercises the core reliability routines (`calculate_single_channel` and the 1oo2 beta-model implementation) to confirm that the equations documented below remain intact, including edge cases such as zero common-cause factors and invalid DU/DD ratios.
- Additional fixtures emulate lane compositions with both grouped and ungrouped chips to validate the subgroup aggregation logic, ensuring every component contributes exactly once to the SIFU totals.
- A continuous integration workflow runs the suite on every push and pull request, providing an auditable evidence trail for tool-qualification dossiers.

## Reliability Calculations
### Inputs
- **Demand mode:** Toggle between low-demand (PFDavg) and high-/continuous-demand (PFH) analysis; all lanes share the selection.
- **Component data:** Each chip stores PFDavg, PFH (1/h), FIT, SIL capability, beta factors, proof-test interval (TI), and mean time to repair (MTTR).

### Global Assumptions
The configuration dialog (*Tools → Configuration → Assumptions*) exposes the global parameters that feed every channel calculation. The defaults shipped with the project are summarised below; adjust them to match the plant-level reliability programme before importing data or editing lanes.

| Symbol | Default | Meaning |
| --- | --- | --- |
| $T_I$ | 8760 h | Proof-test interval shared by all components. |
| $\text{MTTR}$ | 8 h | Mean time to repair after a detected failure. |
| $\beta$ | 0.10 | Common-cause fraction applied to dangerous undetected failures. |
| $\beta_D$ | 0.02 | Common-cause fraction applied to dangerous detected failures. |

If your programme tracks additional assumptions (e.g., partial-stroke test coverage), document them alongside these values when distributing reports so reviewers understand the calculation context.

### Aggregation Rules
1. Components sharing the same normalised colour belong to one subgroup, independent of lane.
2. For each SIFU, the tool computes metrics per subgroup (summing all member channels once) and separately sums ungrouped components per lane.
3. The overall SIFU result is the sum of all subgroup totals plus every ungrouped component across the three lanes, ensuring each chip contributes exactly once.
4. Hover tooltips and HTML exports display subgroup membership, lane coverage, and PFD/PFH totals.

### Architecture Formulas
The HTML report’s formula appendix documents the governing equations together with brief interpretations:

#### 1oo1 architecture
*Average probability and rate of dangerous failure for a single channel.*

$$
\mathrm{PFD}_{1\!\operatorname{oo}\!1} = \lambda_{DU}\left(\tfrac{T_I}{2} + MTTR\right) + \lambda_{DD} \cdot MTTR
$$

$$
\mathrm{PFH}_{1\!\operatorname{oo}\!1} = \lambda_{DU}
$$

#### 1oo2 architecture (beta model)
*Exposure times for independent portions feed into the redundant-channel reliability.*

$$
t_{CE} = \frac{\lambda_{DU}^{\mathrm{ind}}}{\lambda_D^{\mathrm{ind}}}\left(\tfrac{T_I}{2} + MTTR\right) + \frac{\lambda_{DD}^{\mathrm{ind}}}{\lambda_D^{\mathrm{ind}}} \cdot MTTR
$$

$$
t_{GE} = \frac{\lambda_{DU}^{\mathrm{ind}}}{\lambda_D^{\mathrm{ind}}}\left(\tfrac{T_I}{3} + MTTR\right) + \frac{\lambda_{DD}^{\mathrm{ind}}}{\lambda_D^{\mathrm{ind}}} \cdot MTTR
$$

*System-level demand and frequency metrics for the redundant set.*

$$
\mathrm{PFD}_{1\!\operatorname{oo}\!2} = 2(1-\beta)^2\lambda_D^2\, t_{CE}\, t_{GE} + \beta\, \lambda_{DU}\left(\tfrac{T_I}{2} + MTTR\right) + \beta_D\, \lambda_{DD}\, MTTR
$$

$$
\mathrm{PFH}_{1\!\operatorname{oo}\!2} = 2(1-\beta)\lambda_D^{\mathrm{ind}}\lambda_{DU}^{\mathrm{ind}} t_{CE} + \beta\, \lambda_{DU}
$$

#### Supporting relations
*Ratios and independent-channel adjustments used by both architectures.*

$$
\lambda_D = \lambda_{DU} + \lambda_{DD},\quad \lambda_{DU} = r_{DU}\lambda_D,\quad \lambda_{DD} = r_{DD}\lambda_D,\quad \lambda_{DU}^{\mathrm{ind}} = (1-\beta)\lambda_{DU},\quad \lambda_{DD}^{\mathrm{ind}} = (1-\beta_D)\lambda_{DD}
$$

### Variable Summary
Use the glossary below to keep symbols consistent between safety assessments and the generated HTML dossier.

| Symbol | Meaning |
| --- | --- |
| $t_{CE}$ | Exposure window for common-cause dangerous undetected failures. |
| $t_{GE}$ | Exposure window for general dangerous undetected failures. |
| $\lambda_{DU}$ | Dangerous undetected failure rate. |
| $\lambda_{DD}$ | Dangerous detected failure rate. |
| $\lambda_D$ | Total dangerous failure rate (detected + undetected). |
| $\lambda_D^{\mathrm{ind}}$ | Independent-channel dangerous failure rate (excludes common cause). |
| $\lambda_{DU}^{\mathrm{ind}}$ | Independent-channel dangerous undetected failure rate. |
| $\lambda_{DD}^{\mathrm{ind}}$ | Independent-channel dangerous detected failure rate. |
| $r_{DU}$ | Fraction of dangerous failures that are undetected. |
| $r_{DD}$ | Fraction of dangerous failures that are detected. |
| $\beta$ | Common-cause factor for dangerous undetected failures. |
| $\beta_D$ | Common-cause factor for dangerous detected failures. |
| $T_I$ | Proof-test interval. |
| $\text{MTTR}$ | Mean time to repair. |

## Reporting Highlights
- **Architecture overview:** Three-lane layout with per-chip dots and cross-lane connectors rendered via SVG; connector start and end points respect lane-specific rules (e.g., sensors connect from right edge to downstream lanes).
- **Subgroup summary box:** Lists each colour subgroup once, showing the colour swatch, participating lanes, member codes, and aggregated metrics.
- **Composition breakdown panel:** Summarises how the SIFU total derives from subgroup sums plus ungrouped lane contributions, mirroring the aggregation logic used in the application.
- **Component tables & SIL summary:** Tabular breakdown of each lane plus SIL classification based on calculated sums.

## Keyboard & Productivity Tips
- `Ctrl+N` / `Ctrl+O` / `Ctrl+S` mirror the menubar file actions; toolbar buttons provide quick access.
- Right-click a lane to enter link mode from that context or to clear lane/SIFU subgroup assignments.
- Duplicate SIFUs to branch scenarios while preserving subgroup colours and demand modes.

## Troubleshooting
- **Missing Qt platform plugin:** Ensure PyQt5 is installed and your environment has access to a GUI backend (e.g., X11 on Linux, Windows subsystem, or macOS).
- **No connectors in HTML export:** Verify that components share the exact colour (hex or named) and that at least two lanes contain members; the exporter skips single-lane groups.
- **Unexpected SIL classification:** Execute the GUI entry point with the `--selftest` flag to validate the classification boundaries.

## Licensing
Please refer to project documentation or contact the maintainers for licensing terms.
