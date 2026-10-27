# Source dataset

`ai_impact_on_students.csv` was supplied by the repository owner for this feature.
It contains 50,000 student records and 16 columns. The requested source is
[AI Usage & Student Academic Performance Analysis on Kaggle](https://www.kaggle.com/datasets/ranaghulamnabi/ai-usage-and-student-academic-performance-analysis).
The runtime does not contact Kaggle or need Kaggle credentials.

The file is preserved byte-for-byte. Its SHA-256 is recorded with every import.
No claim is made that the records establish causal effects or represent a
particular institution. Consult the source for dataset methodology and reuse terms.

The API imports this file before serving requests. A matching checksum is a no-op;
a changed, valid file replaces the shared survey snapshot in one transaction.
Account/session tables are independent and are never cleared by survey imports.

CSV contract: UTF-8 (optional BOM), comma-delimited, the 16 original columns,
unique non-empty Student_ID, finite numeric values in the eight measurement
columns. Blank/NA/N/A/null/none/NaN values become SQL/JSON null, not zero.
Missing measurements are excluded from averages; GPA change only includes rows
with both GPA measurements. Repeated Student_IDs, malformed rows, missing columns,
invalid measurements, >100,000 rows or >50 MiB fail validation before replacement.
