# SAS programs: analysis of the AS/400 WMS extract

Many Québec food distributors run their warehouse system on an IBM AS/400 (IBM i) and analyse its
extracts in SAS. This folder reproduces that setup with the simulated warehouse:

```bash
python analytics/export_as400.py          # data/baseline_seed42 -> data/as400/*.TXT (+ .CSV, layouts/)
```

| Program | What it does |
|---|---|
| `00_setup.sas` | Paths (set `root`), the `WMS` library, a format for the transaction types |
| `01_import_as400.sas` | **Generated** from the extract layouts: one DATA step per file, column input at the exact positions, CYYMMDD → SAS dates, HHMMSS → SAS times, labels |
| `02_dock_to_stock.sas` | Minutes from receiving scan to put-away, by room and by hour of arrival |
| `03_picker_productivity.sas` | Cases and lines per scanning hour per picker, quartiles, box plot |
| `04_lot_trace.sas` | `%trace(lot=)`: receipts, every scan, outbound pallets and customers reached (recall) |
| `05_supplier_scorecard.sas` | Punctuality, short shipments, refusals, yard wait, shelf life left at receipt |
| `06_order_service.sas` | OTIF and fines by route, month and customer (PROC TABULATE) |

## The extract

Ten physical files, fixed width, Windows-1252, CRLF. Field names use the AS/400 convention: a 2-letter
file prefix and at most 10 characters. Dates are `CYYMMDD` numbers (C = 1 for 20xx) and times are `HHMMSS`.
Each file's layout (positions, types, descriptions) is in `data/as400/layouts/`.

| File | Content | Key |
|---|---|---|
| `ITMMST` | Item master: GTINs, pieces per case, net/tare/gross weight, catch weight, case dimensions and cube, Ti × Hi, shelf life, storage temperatures, supplier item | `IMITEM` |
| `LOCMST` | Locations: rack slots `ROOM-ROW-BAY-LEVEL` (e.g. `FR-03-17-C`), dock staging, drop points, QA cage, doors | `LMLOC` |
| `ITHTRN` | **Transaction history, one record per scan**: receive, taxi, put-away, QA, pick, build, load, ship, write-offs. Licence plate (SSCC-18), source licence plate, item, GTIN, lot, cases, weight, from and to location, employee, equipment, document | `THTXN` |
| `POHDR` / `PODTL` | Inbound trailers per purchase order (appointment, gate, door, unload times) and the pallets received (SSCC, lot, pack and best-before dates, probe temperature, decision) | `PHPO` / `PDLPN` |
| `ORDHDR` / `ORDDTL` | Customer orders and lines | `OHORD` |
| `SHPHDR` | Outbound trailers (bill of lading) | `SHBOL` |
| `CUSMST`, `VNDMST` | Customers and suppliers | |

Transaction types: `RCV` received, `RQA` received to QA, `REJ` refused at the door, `TXI` taxi dock →
drop point, `PUT` put-away, `QAM` moved to QA, `QRL`/`QRJ`/`RTV` QA release/scrap/return to vendor,
`PCK` picked onto an outbound pallet, `BLD` outbound pallet wrapped and labelled, `LOD` loaded,
`SHP` goods issue, `SPL` expired, `ADJ` damage, `RCL` recall removal, `DSP` disposed. `THMVT` gives
the SAP movement type with the same meaning (101, 122, 321, 553, 601, 551, 344) for readers used to SAP.

**Note:** these programs were written for SAS 9.4 / SAS Viya but could not be run in this environment
(no SAS licence here). The extract layouts are verified automatically (`tests/test_wms.py` reads every
file back at the documented positions), so any fix needed would be in the SAS syntax, not the data.
