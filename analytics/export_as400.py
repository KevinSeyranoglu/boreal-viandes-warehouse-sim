"""Export one run as an AS/400 (IBM i) WMS extract: DB2-style physical files, fixed width.

    python analytics/export_as400.py                          # data/baseline_seed42 -> data/as400/
    python analytics/export_as400.py --run data/chaos_seed42

What a legacy IBM i warehouse system hands to the analytics team:
- one file per physical file (ITMMST, LOCMST, ITHTRN, POHDR, PODTL, ORDHDR, ORDDTL, SHPHDR, CUSMST, VNDMST),
- 10-character field names with a 2-letter file prefix, dates as CYYMMDD numbers (C = 1 for 20xx),
  times as HHMMSS, fixed-width records in Windows-1252 (accents preserved),
- a layout per file (field, positions, type, description) and a CSV copy,
- sas/01_import_as400.sas, GENERATED from the same layouts, so positions always match.
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config as C  # noqa: E402
import masterdata as M  # noqa: E402

ENCODING = "cp1252"

# file -> (description, source table, [(field, type, length, decimals, source column or function, description)])
# type: A = alphanumeric, S = zoned numeric (signed), D = date CYYMMDD (7,0), T = time HHMMSS (6,0)


def cyymmdd(v):
    s = str(v)[:10]
    if not s or s == "nan" or len(s) < 10:
        return 0
    return (int(s[:4]) - 1900) // 100 * 1000000 + int(s[2:4]) * 10000 + int(s[5:7]) * 100 + int(s[8:10])


def hhmmss(v):
    s = str(v)
    return int(s[11:13] + s[14:16] + s[17:19]) if len(s) >= 19 else 0


LAYOUTS = {
    "ITMMST": ("Item master", "dim_sku", [
        ("IMITEM", "A", 10, 0, "sku_code", "Item number"),
        ("IMDESC", "A", 30, 0, "name_fr", "Description (French)"),
        ("IMDESE", "A", 30, 0, "name_en", "Description (English)"),
        ("IMGTIN", "A", 14, 0, "gtin_case", "GTIN-14 of the case"),
        ("IMGTEA", "A", 13, 0, "gtin_each", "GTIN-13 of the retail piece"),
        ("IMCAT", "A", 10, 0, "category", "Category"),
        ("IMZONE", "A", 2, 0, lambda r: M.ROOM_CODE[r["zone"]], "Storage room FR/TR/CG"),
        ("IMPCS", "S", 3, 0, "pieces_per_case", "Pieces per case"),
        ("IMUOM", "A", 2, 0, "uom_base", "Base unit of measure"),
        ("IMCTCH", "A", 1, 0, lambda r: "Y" if r["catch_weight"] == "1" else "N", "Catch weight Y/N"),
        ("IMNETW", "S", 7, 3, "net_kg_nominal", "Nominal net weight per case (kg)"),
        ("IMWMIN", "S", 7, 3, "case_kg_min", "Minimum case weight (kg)"),
        ("IMWMAX", "S", 7, 3, "case_kg_max", "Maximum case weight (kg)"),
        ("IMTARE", "S", 5, 3, "tare_kg", "Case tare (kg)"),
        ("IMGRSW", "S", 7, 3, "gross_kg_nominal", "Nominal gross weight per case (kg)"),
        ("IMLEN", "S", 3, 0, "case_length_cm", "Case length (cm)"),
        ("IMWID", "S", 3, 0, "case_width_cm", "Case width (cm)"),
        ("IMHGT", "S", 3, 0, "case_height_cm", "Case height (cm)"),
        ("IMCUBE", "S", 5, 1, "case_cube_l", "Case cube (litres)"),
        ("IMTI", "S", 2, 0, "ti", "Cases per layer (Ti)"),
        ("IMHI", "S", 2, 0, "hi", "Layers per pallet (Hi)"),
        ("IMCSPL", "S", 3, 0, "cases_per_pallet", "Cases per pallet"),
        ("IMSHLF", "S", 3, 0, "shelf_life_days", "Shelf life (days)"),
        ("IMTMIN", "S", 3, 0, "storage_min_c", "Storage minimum (deg C)"),
        ("IMTMAX", "S", 3, 0, "storage_max_c", "Storage maximum (deg C)"),
        ("IMVEND", "A", 4, 0, "plant_code", "Supplier (plant) code"),
        ("IMVITM", "A", 10, 0, "supplier_item", "Supplier item number"),
        ("IMBRND", "A", 20, 0, "brand", "Brand"),
        ("IMCOST", "S", 7, 2, "value_per_case", "Standard cost per case ($)"),
    ]),
    "LOCMST": ("Location master", "dim_location", [
        ("LMLOC", "A", 12, 0, "location", "Location code"),
        ("LMTYPE", "A", 10, 0, "loc_type", "Location type"),
        ("LMZONE", "A", 10, 0, "zone", "Temperature zone"),
        ("LMROW", "S", 2, 0, "room_row", "Rack row"),
        ("LMBAY", "S", 2, 0, "bay", "Bay"),
        ("LMLVL", "A", 1, 0, "level_code", "Level (A = floor)"),
        ("LMPICK", "A", 1, 0, lambda r: "Y" if r["pick_face"] == "1" else "N", "Pick face Y/N"),
        ("LMREACH", "A", 1, 0, lambda r: "Y" if r["reach_truck_required"] == "1" else "N", "Reach truck required Y/N"),
    ]),
    "ITHTRN": ("Inventory transaction history (one record per scan)", "fact_transactions", [
        ("THTXN", "S", 9, 0, "txn_id", "Transaction number"),
        ("THDATE", "D", 7, 0, "ts", "Scan date CYYMMDD"),
        ("THTIME", "T", 6, 0, "ts", "Scan time HHMMSS"),
        ("THTYPE", "A", 3, 0, "txn_type", "Transaction type (RCV, PUT, PCK...)"),
        ("THMVT", "A", 3, 0, "mvt_type", "SAP-equivalent movement type"),
        ("THLPN", "A", 18, 0, "sscc", "Licence plate (SSCC-18)"),
        ("THFLPN", "A", 18, 0, "from_sscc", "Source licence plate (picks)"),
        ("THITEM", "A", 10, 0, "sku_code", "Item number"),
        ("THGTIN", "A", 14, 0, "gtin", "GTIN-14"),
        ("THLOT", "A", 8, 0, "lot", "Lot number"),
        ("THQTY", "S", 7, 0, "cases", "Quantity (cases, negative = removed)"),
        ("THWGT", "S", 9, 3, "weight_kg", "Net weight (kg)"),
        ("THFLOC", "A", 12, 0, "from_loc", "From location"),
        ("THTLOC", "A", 12, 0, "to_loc", "To location"),
        ("THUSER", "A", 10, 0, "user_id", "Employee"),
        ("THEQP", "A", 8, 0, "equipment_id", "Equipment"),
        ("THDOCT", "A", 4, 0, "doc_type", "Document type (PO, SO, BOL, QA, ADJ)"),
        ("THDOC", "A", 10, 0, "doc_no", "Document number"),
        ("THRSN", "A", 30, 0, "reason", "Reason / comment"),
    ]),
    "POHDR": ("Purchase order / inbound trailer header", "fact_inbound_trucks", [
        ("PHPO", "A", 10, 0, "po_number", "Purchase order"),
        ("PHVEND", "A", 4, 0, "plant_code", "Supplier"),
        ("PHSDAT", "D", 7, 0, "scheduled_ts", "Appointment date"),
        ("PHSTIM", "T", 6, 0, "scheduled_ts", "Appointment time"),
        ("PHADAT", "D", 7, 0, "gate_ts", "Gate-in date"),
        ("PHATIM", "T", 6, 0, "gate_ts", "Gate-in time"),
        ("PHDDAT", "D", 7, 0, "dock_ts", "At-door date"),
        ("PHDTIM", "T", 6, 0, "dock_ts", "At-door time"),
        ("PHEDAT", "D", 7, 0, "unload_end_ts", "Unload-end date"),
        ("PHETIM", "T", 6, 0, "unload_end_ts", "Unload-end time"),
        ("PHDOOR", "S", 2, 0, "door", "Receiving door"),
        ("PHQORD", "S", 3, 0, "pallets_ordered", "Pallets ordered"),
        ("PHQRCV", "S", 3, 0, "pallets", "Pallets shipped by supplier"),
        ("PHQREJ", "S", 3, 0, "pallets_rejected", "Pallets refused at the door"),
        ("PHREEF", "A", 1, 0, lambda r: "Y" if r["reefer_failure"] == "1" else "N", "Reefer failure Y/N"),
    ]),
    "PODTL": ("Purchase order receipts (one record per pallet)", "fact_pallet_receipts", [
        ("PDPO", "A", 10, 0, "po_number", "Purchase order"),
        ("PDLPN", "A", 18, 0, "sscc", "Licence plate (SSCC-18)"),
        ("PDITEM", "A", 10, 0, "sku_code", "Item number"),
        ("PDLOT", "A", 8, 0, "lot", "Lot number"),
        ("PDQTY", "S", 5, 0, "cases", "Cases"),
        ("PDWGT", "S", 9, 3, "weight_kg", "Net weight (kg)"),
        ("PDPKDT", "D", 7, 0, "pack_date", "Pack date CYYMMDD"),
        ("PDBBDT", "D", 7, 0, "best_before", "Best-before date CYYMMDD"),
        ("PDTEMP", "S", 5, 1, "arrival_temp_c", "Probe temperature (deg C)"),
        ("PDDEC", "A", 1, 0, lambda r: {"accept": "A", "qa": "Q", "reject": "R"}[r["decision"]], "Decision A/Q/R"),
        ("PDRDAT", "D", 7, 0, "received_ts", "Receipt date"),
        ("PDRTIM", "T", 6, 0, "received_ts", "Receipt time"),
        ("PDUSER", "A", 10, 0, "receiver_id", "Receiver"),
    ]),
    "ORDHDR": ("Customer order header", "fact_orders", [
        ("OHORD", "A", 10, 0, lambda r: f"SO{int(r['order_id']):07d}", "Sales order"),
        ("OHCUST", "A", 6, 0, "store_id", "Customer"),
        ("OHROUT", "A", 4, 0, "route_id", "Route"),
        ("OHCDAT", "D", 7, 0, "created_ts", "Order date"),
        ("OHCTIM", "T", 6, 0, "created_ts", "Order time"),
        ("OHSDAT", "D", 7, 0, "scheduled_departure_ts", "Scheduled ship date"),
        ("OHSTIM", "T", 6, 0, "scheduled_departure_ts", "Scheduled ship time"),
        ("OHLINE", "S", 3, 0, "lines", "Lines"),
        ("OHQORD", "S", 6, 0, "cases_ordered", "Cases ordered"),
        ("OHQSHP", "S", 6, 0, "cases_shipped", "Cases shipped"),
        ("OHONTM", "A", 1, 0, lambda r: "Y" if r["on_time"] == "1" else "N", "On time Y/N"),
        ("OHLATE", "S", 5, 1, "late_min", "Minutes late"),
        ("OHRUSH", "A", 1, 0, lambda r: "Y" if r["rush"] == "1" else "N", "Rush order Y/N"),
        ("OHFINE", "S", 9, 2, "penalty", "Customer fine ($)"),
    ]),
    "ORDDTL": ("Customer order lines", "fact_order_lines", [
        ("ODORD", "A", 10, 0, lambda r: f"SO{int(r['order_id']):07d}", "Sales order"),
        ("ODITEM", "A", 10, 0, "sku_code", "Item number"),
        ("ODQORD", "S", 5, 0, "cases_ordered", "Cases ordered"),
        ("ODQALC", "S", 5, 0, "cases_allocated", "Cases allocated"),
        ("ODQPCK", "S", 5, 0, "cases_picked", "Cases picked"),
        ("ODQSHP", "S", 5, 0, "cases_shipped", "Cases shipped"),
    ]),
    "SHPHDR": ("Outbound trailer / bill of lading", "fact_shipments", [
        ("SHBOL", "A", 10, 0, "bol_number", "Bill of lading"),
        ("SHROUT", "A", 4, 0, "route_id", "Route"),
        ("SHDOOR", "S", 2, 0, "door", "Shipping door"),
        ("SHSDAT", "D", 7, 0, "scheduled_departure_ts", "Scheduled departure date"),
        ("SHSTIM", "T", 6, 0, "scheduled_departure_ts", "Scheduled departure time"),
        ("SHADAT", "D", 7, 0, "actual_departure_ts", "Actual departure date"),
        ("SHATIM", "T", 6, 0, "actual_departure_ts", "Actual departure time"),
        ("SHORDS", "S", 3, 0, "orders", "Orders"),
        ("SHPLTS", "S", 3, 0, "pallets", "Pallets"),
        ("SHCASE", "S", 6, 0, "cases", "Cases"),
        ("SHLATE", "S", 5, 1, "late_min", "Minutes late"),
    ]),
    "CUSMST": ("Customer master", "dim_store", [
        ("CMCUST", "A", 6, 0, "store_id", "Customer"),
        ("CMNAME", "A", 40, 0, "name", "Name"),
        ("CMCITY", "A", 20, 0, "city", "City"),
        ("CMTYPE", "A", 10, 0, "kind", "Channel"),
        ("CMROUT", "A", 4, 0, "route_id", "Route"),
        ("CMSTOP", "S", 2, 0, "stop", "Stop on route"),
    ]),
    "VNDMST": ("Supplier master", "dim_plant", [
        ("VMVEND", "A", 4, 0, "plant_code", "Supplier"),
        ("VMNAME", "A", 40, 0, "name_fr", "Name"),
    ]),
}


def positions(fields):
    pos, out = 1, []
    for name, typ, length, dec, _src, desc in fields:
        out.append((name, typ, length, dec, pos, pos + length - 1, desc))
        pos += length
    return out


def value(row, src):
    return src(row) if callable(src) else row[src]


def fmt(v, typ, length, dec):
    if typ == "D":
        return f"{cyymmdd(v):0{length}d}"
    if typ == "T":
        return f"{hhmmss(v):0{length}d}"
    if typ == "S":
        x = float(v) if str(v).strip() not in ("", "nan", "None") else 0.0
        s = f"{x:.{dec}f}" if dec else f"{int(round(x))}"
        if len(s) > length:
            raise ValueError(f"{v} does not fit S({length},{dec})")
        return s.rjust(length)
    s = "" if v is None else str(v)
    return s[:length].ljust(length)


def export(run_dir, out_dir, sas_dir=None):
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(os.path.join(out_dir, "layouts"), exist_ok=True)
    counts = {}
    for name, (desc, table, fields) in LAYOUTS.items():
        df = pd.read_csv(os.path.join(run_dir, table + ".csv"), dtype=str, keep_default_na=False)
        rows, csv_rows = [], []
        for _, r in df.iterrows():
            rec = {fname: fmt(value(r, src), typ, length, dec) for fname, typ, length, dec, src, _ in fields}
            rows.append("".join(rec.values()))
            csv_rows.append({k: v.strip() for k, v in rec.items()})
        with open(os.path.join(out_dir, name + ".TXT"), "w", encoding=ENCODING, errors="replace", newline="\r\n") as fh:
            fh.write("\n".join(rows) + ("\n" if rows else ""))
        pd.DataFrame(csv_rows, columns=[f[0] for f in fields]).to_csv(os.path.join(out_dir, name + ".CSV"),
                                                                     index=False, encoding=ENCODING)
        with open(os.path.join(out_dir, "layouts", name + ".layout.txt"), "w", encoding="utf-8") as fh:
            fh.write(f"{name}  {desc}  (record length {sum(f[2] for f in fields)}, {ENCODING})\n")
            fh.write(f"{'FIELD':10} {'FROM':>5} {'TO':>5} {'LEN':>4} TYPE DEC  DESCRIPTION\n")
            for fname, typ, length, dec, start, end, d in positions(fields):
                fh.write(f"{fname:10} {start:5d} {end:5d} {length:4d}  {typ}   {dec:2d}  {d}\n")
        counts[name] = len(rows)
    if sas_dir:
        write_sas_import(os.path.join(sas_dir, "01_import_as400.sas"))
    return counts


def write_sas_import(path):
    """SAS DATA steps for every file, generated from LAYOUTS (column input, CYYMMDD -> SAS dates)."""
    L = ["/* Generated by analytics/export_as400.py from the same layouts as the extract. Do not edit. */",
         "/* Reads the AS/400 fixed-width extract into the WMS library (see 00_setup.sas).              */", ""]
    for name, (desc, _table, fields) in LAYOUTS.items():
        lrecl = sum(f[2] for f in fields)
        L.append(f"/* {name}: {desc} */")
        L.append(f"data wms.{name.lower()};")
        L.append(f'  infile "&as400/{name}.TXT" lrecl={lrecl} truncover encoding="wlatin1" termstr=crlf;')
        inputs, conv, labels, fmts, drops = [], [], [], [], []
        for fname, typ, length, dec, start, end, d in positions(fields):
            if typ == "A":
                inputs.append(f"    @{start:<4d} {fname:10} ${length}.")
            elif typ in ("D", "T"):
                raw = f"_{fname[:9]}"
                inputs.append(f"    @{start:<4d} {raw:10} {length}.")
                drops.append(raw)
                if typ == "D":
                    conv.append(f"  if {raw} > 0 then {fname} = mdy(mod(int({raw}/100),100), mod({raw},100), "
                                f"1900 + 100*int({raw}/1000000) + mod(int({raw}/10000),100));")
                    fmts.append(f"{fname} yymmdd10.")
                else:
                    conv.append(f"  {fname} = hms(int({raw}/10000), mod(int({raw}/100),100), mod({raw},100));")
                    fmts.append(f"{fname} time8.")
            else:
                inputs.append(f"    @{start:<4d} {fname:10} {length}." + (f"{dec}" if dec else ""))
            labels.append(f'    {fname} = "{d}"')
        L.append("  input")
        L += inputs
        L.append("  ;")
        L += conv
        if fmts:
            L.append("  format " + " ".join(fmts) + ";")
        L.append("  label")
        L += labels
        L.append("  ;")
        if drops:
            L.append("  drop " + " ".join(drops) + ";")
        L.append("run;")
        L.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", default=os.path.join(ROOT, C.DATA_DIR, "baseline_seed42"))
    ap.add_argument("--out", default=os.path.join(ROOT, C.DATA_DIR, "as400"))
    args = ap.parse_args(argv)
    counts = export(args.run, args.out, sas_dir=os.path.join(ROOT, "sas"))
    for k, v in counts.items():
        print(f"{k:8} {v:>9,} records")
    print(f"-> {args.out}  (and sas/01_import_as400.sas)")


if __name__ == "__main__":
    main()
