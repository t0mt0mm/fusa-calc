# Spreadsheet inputs for FuSa Calculator

The default configuration expects three data sources inside this directory. Update the configuration if your workbook layout deviates.

## Cause & Effect matrix workbook
- **Worksheet:** Use the sheet that carries the matrix; data typically starts at row 4 (1-based indexing).
- **Required columns:**
  - Column 1 (A): status flag; only rows equal to `complete` are imported.
  - Column 4 (D): Safety-function name (SIFU label).
  - Column 6 (F): Target SIL level.
  - Column 13 (M): Criteria / safety action description.
  - Column 19 (S): Demand mode keyword (`low`, `high`, etc.).
  - Column 20 (T): Safety action reference used to resolve actuators.
- **Lookups:** Keep actuator substitution terms in a dedicated definitions sheet so the importer can resolve them.

## E/E overview workbook
- **Worksheets:** Split by subsystem (for example, dedicated sheets per production area).
- **Header rows:** Data starts at row 3.
- **Columns:**
  - Column 2 (B): PID code.
  - Column 3 (C): PDM / hardware module code.
- **Sheet selection:** PID patterns configured for the importer determine which worksheet is searched.

## FuSa component catalogue (CSV)
- **Identifier column:** `comp_id` matches PID or PDM codes used in assignments.
- **Reliability properties:** Provide the columns mapped in the importer configuration, such as `pfd_avg`, `pfh_avg`, and `sys_cap`.
- **Encoding:** CSV must be UTF-8 with a header row.

Adjust column indices, sheet names, or file paths in the configuration if your organisation uses different naming schemes.
