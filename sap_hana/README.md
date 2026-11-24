# SAP S/4HANA extract and HANA SQL

The same warehouse data as the AS/400 extract (`../sas/`), shaped the way an SAP S/4HANA system stores
it, with HANA SQL to create the tables, load them and answer the usual warehouse questions.

```bash
python analytics/export_sap.py            # data/baseline_seed42 -> data/sap/*.csv (+ 00 and 01 below)
python analytics/export_sap.py --check    # also run the analyses here, on DuckDB (no HANA needed)
```

## Tables

SAP field names. Dates are `YYYYMMDD` and times `HHMMSS` stored as text, as in the ABAP dictionary
(DATS / TIMS), so the analyses convert them with `TO_DATE` / `TO_TIMESTAMP` like real SAP reporting
does. Fields SAP does not have are customer fields (`ZZ...`).

| Table | Content | Built from |
|---|---|---|
| `MARA`, `MAKT`, `MARM` | Material, FR/EN descriptions, case and piece units with their GTINs | product master |
| `MCH1` | Batches: production date `HSDAT`, best-before `VFDAT`, vendor | pallet receipts |
| `LFA1`, `KNA1` | Vendors (the plants), customers (the stores, with route and stop) | plant and store masters |
| `EKKO`, `EKPO` | Purchase orders and items | inbound trucks, receipts |
| `MATDOC` | Material documents: 101 goods receipt, 122 return to vendor, 321 release from quality inspection (two items), 551 / 553 scrap, 601 goods issue | WMS scan log |
| `LTAP` | Warehouse tasks: every confirmed scan, source and destination bin, storage unit (SSCC); `ZZSCAN` keeps the scan type | WMS scan log |
| `VBAK`, `VBAP` | Sales orders and items (`AUART` ZRUS = rush order) | orders |
| `LIKP`, `LIPS` | Deliveries: planned and actual goods issue, shipping type (01 route truck, 02 expedited), one item per batch | orders, shipped lots |
| `VBFA` | Document flow: sales order to delivery | orders |

## Scripts

| File | What it does |
|---|---|
| `00_create_tables.sql` | `CREATE SCHEMA BOREAL` and one `CREATE COLUMN TABLE` per table (generated) |
| `01_import.sql` | `IMPORT FROM CSV FILE` for every table (generated) |
| `02_dock_to_stock.sql` | Minutes from goods receipt to the rack bin, per storage room (average and 90th percentile) |
| `03_otif_by_route.sql` | On time, in full and OTIF per route, through `VBFA` from orders to deliveries |
| `04_batch_trace.sql` | Recall: every customer that received a batch, cases, first and last goods issue |
| `05_vendor_quality.sql` | Per vendor: received, returned (122) and scrapped (553) cases, shelf life left at receipt |

In the baseline run, `05` shows the same thing as the spoilage analysis, from SAP data alone: the
poultry plant has the highest return rate (6.5 %) and the least shelf life left at receipt (8 days).

## Running it on SAP HANA

1. Get a HANA database: the free trial of **SAP HANA Cloud**, or SAP HANA express edition.
2. Run `00_create_tables.sql` in the SQL console (Database Explorer).
3. Load the CSV files: in HANA Cloud, *Import Data* on each table with the files from `data/sap/`; on a
   server you control, copy them to a folder HANA can read and run `01_import.sql` (change the path).
4. Run `02` to `05`.

**What was verified here:** the analyses have not been run on a HANA server. They are run on DuckDB
after a small translation of the few HANA-only spellings they use (`SECONDS_BETWEEN`, `DAYS_BETWEEN`,
`TO_DATE` / `TO_TIMESTAMP` with SAP formats, `NVARCHAR`, `CREATE COLUMN TABLE`, `DUMMY`); see
`hana_to_duckdb` in `analytics/export_sap.py`. `tests/test_sap.py` checks that their results equal the
simulation's own numbers (OTIF order by order, dock-to-stock, the batch trace, vendor receipts).
