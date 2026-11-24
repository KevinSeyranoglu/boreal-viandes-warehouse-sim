"""Warehouse master data: GS1 identifiers, pack data and location codes.

All identifiers are fictional but valid in form: GTIN-14 and SSCC-18 carry a correct GS1 check
digit, under a made-up company prefix in the GS1 Canada range (754).
"""
from __future__ import annotations

COMPANY_PREFIX = "7541234"                  # fictional GS1 Canada company prefix

# SKU -> pieces per case, piece description (fr, en), case tare kg, brand, supplier item code
PACK = {
    "P101": (4, ("longe sous vide", "vacuum-packed loin"), 0.55, "Boréal", "PORC-1101"),
    "P102": (2, ("épaule entière", "whole shoulder"), 0.60, "Boréal", "PORC-1102"),
    "P103": (10, ("barquette de 4 côtelettes", "tray of 4 chops"), 0.45, "Boréal", "PORC-1103"),
    "V201": (10, ("barquette de 2 poitrines", "tray of 2 breasts"), 0.45, "Lanaudière Volaille", "VOLA-2201"),
    "V202": (12, ("barquette de cuisses", "tray of thighs"), 0.55, "Lanaudière Volaille", "VOLA-2202"),
    "V203": (8, ("poulet entier ensaché", "bagged whole chicken"), 0.65, "Lanaudière Volaille", "VOLA-2203"),
    "V204": (2, ("dinde entière", "whole turkey"), 0.70, "Lanaudière Volaille", "VOLA-2204"),
    "T301": (4, ("jambon fumé désossé", "boneless smoked ham"), 0.55, "Montérégie Fumoir", "TRAN-3301"),
    "T302": (10, ("bacon tranché 500 g", "sliced bacon 500 g"), 0.40, "Montérégie Fumoir", "TRAN-3302"),
    "T303": (20, ("saucisses 250 g", "sausages 250 g"), 0.40, "Montérégie Fumoir", "TRAN-3303"),
    "T304": (12, ("saucisses BBQ 500 g", "BBQ sausages 500 g"), 0.45, "Montérégie Fumoir", "TRAN-3304"),
    "T305": (20, ("charcuterie tranchée 200 g", "sliced deli 200 g"), 0.35, "Montérégie Fumoir", "TRAN-3305"),
    "C401": (10, ("côtes levées 1 kg", "ribs 1 kg"), 0.60, "Mauricie Surgelés", "SURG-4401"),
    "C402": (5, ("sac d'ailes 2 kg", "2 kg bag of wings"), 0.60, "Mauricie Surgelés", "SURG-4402"),
    "C403": (20, ("porc haché 500 g", "ground pork 500 g"), 0.55, "Mauricie Surgelés", "SURG-4403"),
}
# cases per layer (Ti) -> case footprint in cm on a 48 x 40 in (122 x 102 cm) pallet
TI_FOOTPRINT = {8: (50, 30), 10: (40, 30), 11: (40, 27), 12: (40, 25), 14: (35, 24)}
TI_HI = {40: (8, 5), 48: (8, 6), 56: (8, 7), 60: (10, 6), 64: (8, 8), 70: (10, 7), 72: (12, 6), 80: (10, 8),
         96: (12, 8), 110: (11, 10), 120: (12, 10), 140: (14, 10)}
PALLET_TARE_KG = 25.0                       # wooden 48 x 40 pallet
PALLET_HEIGHT_CM = 150                      # max loaded height (pallet included)
ROOM_CODE = {"fresh": "FR", "processed": "TR", "freezer": "CG"}   # frais, transformés, congélateur
LEVEL_LETTER = "ABCDEFGH"                   # A = floor


def check_digit(digits: str) -> str:
    """GS1 mod-10 check digit (weights 3,1,3,... from the right)."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits)))
    return str((10 - total % 10) % 10)


def gtin14(indicator: int, item_ref: int) -> str:
    body = f"{indicator}{COMPANY_PREFIX}{item_ref:05d}"
    return body + check_digit(body)


def sscc(serial: int, extension: int = 0) -> str:
    body = f"{extension}{COMPANY_PREFIX}{serial:09d}"
    return body + check_digit(body)


def item_master(sku, zone_spec):
    """All WMS item-master fields for one SKU (models.SKU + its zone's temperature spec)."""
    pieces, piece, tare, brand, supplier_item = PACK[sku.code]
    ti, hi = TI_HI[sku.cases_per_pallet]
    length, width = TI_FOOTPRINT[ti]
    height = (PALLET_HEIGHT_CM - 15) // hi
    ref = int(sku.code[1:])
    net = round((sku.weight_min + sku.weight_max) / 2, 2)
    return {
        "gtin_case": gtin14(1, ref), "gtin_each": gtin14(0, ref)[1:],     # GTIN-13 on the retail piece
        "brand": brand, "supplier_item": supplier_item,
        "pieces_per_case": pieces, "piece_desc_fr": piece[0], "piece_desc_en": piece[1],
        "uom_base": "CS", "catch_weight": int(sku.weight_max - sku.weight_min > 0.5),
        "net_kg_nominal": net, "tare_kg": tare, "gross_kg_nominal": round(net + tare, 2),
        "case_length_cm": length, "case_width_cm": width, "case_height_cm": height,
        "case_cube_l": round(length * width * height / 1000, 1),
        "ti": ti, "hi": hi, "pallet_gross_kg_nominal": round(sku.cases_per_pallet * (net + tare) + PALLET_TARE_KG, 1),
        "storage_min_c": zone_spec["min"], "storage_max_c": zone_spec["max"],
        "country_of_origin": "CA", "lot_controlled": 1,
    }
