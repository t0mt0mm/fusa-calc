# Spreadsheet inputs for FuSa Calculator

The default configuration in [`config.yaml`](../config.yaml) expects three data sources inside this directory. Update the paths or indices if your workbook layout deviates.

## Cause & Effect matrix (`PSI129_Cosmos_SAS060400 - Rev07 - MeOH 500 C&E Matrix.xlsx`)
- **Worksheet:** `Cause-And-Effect-Matrix`
- **Header rows:** Data starts at row 4 (1-based indexing).
- **Required columns:**
  - Column 1 (A): status flag; only rows equal to `complete` are imported.
  - Column 4 (D): Safety-function name (SIFU label).
  - Column 6 (F): Target SIL level.
  - Column 13 (M): Criteria / safety action description.
  - Column 19 (S): Demand mode keyword (`low`, `high`, etc.).
  - Column 20 (T): Safety action reference used to resolve actuators.
- **Lookups:** Optional sheet `Definitions` should contain the actuator substitution terms defined under `ce_matrix.terms_vs_actuators` in the configuration.

## E/E overview (`ELMO_Interfaces_MeOH500_240209_local.xlsx`)
- **Worksheets:** `Aktoren Sensoren H2MO`, `Aktoren Sensoren FCMO 500kW`, `Aktoren Sensoren Interfacearea`.
- **Header rows:** Data starts at row 3.
- **Columns:**
  - Column 2 (B): PID code.
  - Column 3 (C): PDM / hardware module code.
- **Sheet selection:** PID patterns in `config.yaml > ee_overview.modules_vs_sheets` determine which worksheet is searched.

## FuSa component data (`FusaData.csv`)
- **Identifier column:** `comp_id` matches PID or PDM codes used in assignments.
- **Reliability properties:** Provide the columns mapped in `config.yaml > fusa.col_names_vs_comp_properties`, such as `pfd_avg`, `pfh_avg`, and `sys_cap`.
- **Encoding:** CSV must be UTF-8 with a header row.

Adjust column indices, sheet names, or file paths in `config.yaml` if your organisation uses different naming schemes.
