"""French (Québec) / English text. French is the default; L toggles.

t(key, **kw) formats a string. Values of the keyword arguments listed in
VALUES are translated too (zone="freezer" -> "Congélateur").
"""
from __future__ import annotations

import config as C

LANGS = ("fr", "en")
_lang = "fr"

# key: (fr, en)
TEXT = {
    # ---- window / HUD
    "title": ("Boréal Viandes – Centre de distribution", "Boréal Viandes – Distribution Center"),
    "paused": ("PAUSE", "PAUSED"),
    "speed": ("Vitesse {x}x", "Speed {x}x"),
    "day_n": ("Jour {n}", "Day {n}"),
    "help": ("Espace pause · 1-5 vitesse · flèches/glisser déplacer · molette zoom · Orig. recentrer · L langue",
             "Space pause · 1-5 speed · arrows/drag pan · wheel zoom · Home recenter · L language"),
    "saved": ("Partie sauvegardée", "Game saved"),
    "loaded": ("Partie chargée", "Game loaded"),
    "no_save": ("Aucune sauvegarde", "No save file"),

    # ---- sidebar
    "money": ("Encaisse", "Cash"),
    "profit_today": ("Profit du jour", "Profit today"),
    "on_time": ("Livraisons à temps", "On-time delivery"),
    "fill_rate": ("Taux de service", "Fill rate"),
    "accuracy": ("Précision prélèvement", "Picking accuracy"),
    "cph": ("Caisses / heure", "Cases / hour"),
    "compliance": ("Conformité chaîne du froid", "Cold-chain compliance"),
    "spoilage": ("Pertes (périmés)", "Spoilage"),
    "energy": ("Énergie", "Energy"),
    "alarms": ("Alarmes température", "Temperature alarms"),
    "shipped_today": ("Caisses expédiées", "Cases shipped"),
    "open_orders": ("Commandes ouvertes", "Open orders"),
    "zone_fill": ("Occupation des zones", "Zone occupancy"),
    "event_log": ("Journal", "Event log"),
    "staff_on": ("Employés au travail", "Staff on shift"),
    "outside": ("Extérieur", "Outside"),

    # ---- map labels
    "area_charging": ("Recharge", "Charging"),
    "area_break": ("Cafétéria", "Break room"),
    "area_office": ("Bureau", "Office"),
    "area_receiving": ("Réception", "Receiving"),
    "area_shipping": ("Expédition", "Shipping"),
    "area_yard": ("Cour à remorques", "Trailer yard"),
    "door_n": ("Porte {n}", "Door {n}"),

    # ---- event log (simulation.log keys)
    "log_welcome": ("Bienvenue au centre de distribution Boréal Viandes.",
                    "Welcome to the Boréal Viandes distribution center."),
    "log_shift": ("Début du quart de {shift}", "Shift starts: {shift}"),
    "log_truck_in": ("Camion {truck} de {plant} arrivé ({late:+d} min)",
                     "Truck {truck} from {plant} arrived ({late:+d} min)"),
    "log_departed": ("Route {route} partie : {cases} caisses ({late:+d} min)",
                     "Route {route} departed: {cases} cases ({late:+d} min)"),
    "log_wave": ("Vague {route} lancée : {orders} commandes", "Wave {route} released: {orders} orders"),
    "log_alarm": ("ALARME : {zone} à {temp} °C", "ALARM: {zone} at {temp} °C"),
    "log_alarm_end": ("Fin d'alarme : {zone}", "Alarm cleared: {zone}"),
    "log_door_fixed": ("Porte refermée : {zone}", "Door closed: {zone}"),
    "log_expedite": ("Envoi express vers {store}", "Expedited delivery to {store}"),
    "log_hired": ("Embauche : {name} ({role}, {shift})", "Hired: {name} ({role}, {shift})"),
    "log_fired": ("Départ : {name} ({role})", "Let go: {name} ({role})"),
    "log_low_battery": ("Chariot {fid} : batterie faible", "Forklift {fid}: low battery"),
    "log_prioritized": ("Commande priorisée : {store}", "Order prioritized: {store}"),
    "log_qa_hold": ("Lot {lot} ({sku}) en retenue AQ : {temp} °C", "Lot {lot} ({sku}) on QA hold: {temp} °C"),
    "log_qa_release": ("Lot {lot} libéré par l'AQ", "Lot {lot} released by QA"),
    "log_rejected": ("Lot {lot} ({sku}) refusé : {temp} °C", "Lot {lot} ({sku}) rejected: {temp} °C"),
    "log_recall_auto": ("Le superviseur retire le lot {lot}", "Supervisor pulls lot {lot}"),
    "log_recall_done": ("Rappel du lot {lot} terminé en {hours} h", "Recall of lot {lot} done in {hours} h"),
    "log_recall_pulling": ("Retrait du lot {lot} lancé (réaction {minutes} min)",
                           "Pulling lot {lot} (response {minutes} min)"),
    "log_repaired": ("Chariot {fid} réparé", "Forklift {fid} repaired"),
    "log_short": ("Commande incomplète pour {store} : {cases} caisses manquantes",
                  "Short order for {store}: {cases} cases missing"),
    "log_spoiled": ("Lot {lot} ({sku}) périmé : {cases} caisses jetées",
                    "Lot {lot} ({sku}) expired: {cases} cases thrown out"),
    "log_zone_full": ("Zone pleine : {zone}", "Zone full: {zone}"),

    # ---- random events
    "ev_breakdown": ("Bris du chariot {fid} ({hours} h de réparation)", "Forklift {fid} broke down ({hours} h repair)"),
    "ev_door_stuck": ("Porte bloquée ouverte : {zone} ({minutes} min)", "Door stuck open: {zone} ({minutes} min)"),
    "ev_late_truck": ("Camion de {plant} retardé de {minutes} min", "Truck from {plant} delayed {minutes} min"),
    "ev_recall": ("RAPPEL : lot {lot} ({sku}), {pallets} palettes", "RECALL: lot {lot} ({sku}), {pallets} pallets"),
    "ev_reefer": ("Panne de groupe frigo : camion de {plant}", "Reefer failure: truck from {plant}"),
    "ev_rush": ("Commande urgente : {store} ({cases} caisses)", "Rush order: {store} ({cases} cases)"),
    "ev_season": ("Saison : {season}", "Season: {season}"),
    "ev_sick": ("Absence maladie : {name} ({role})", "Sick call: {name} ({role})"),
    "ev_injury": ("Accident de travail : {name}, {kind} ({days} j d'arrêt)",
                  "Workplace injury: {name}, {kind} ({days} days off)"),
    "ev_forklift": ("Incident chariot {fid} : {kind}", "Forklift {fid} incident: {kind}"),

    # ---- floating text
    "fx_alarm": ("Alarme {zone} !", "{zone} alarm!"),
    "fx_breakdown": ("Bris chariot {fid}", "Forklift {fid} down"),
    "fx_injury": ("Blessure !", "Injury!"),
    "fx_forklift": ("Collision !", "Collision!"),
    "fx_disposed": ("Lot {lot} jeté", "Lot {lot} disposed"),
    "fx_expedite": ("Envoi express", "Expedited"),
    "fx_qa_hold": ("Retenue AQ", "QA hold"),
    "fx_qa_ok": ("AQ OK", "QA OK"),
    "fx_recall": ("Rappel lot {lot}", "Recall lot {lot}"),
    "fx_rejected": ("Refusé", "Rejected"),
    "fx_shipped": ("+{amount:.0f} $", "+${amount:.0f}"),
    "fx_spoiled": ("Périmé", "Expired"),
}

# translated values for keyword arguments
VALUES = {
    "zone": {"dock": ("Quai", "Dock"), "fresh": ("Frais", "Fresh"),
             "processed": ("Charcuterie", "Processed"), "freezer": ("Congélateur", "Freezer"),
             "qa": ("Contrôle qualité", "QA hold")},
    "role": {"receiver": ("réceptionnaire", "receiver"), "taxi": ("taxi", "taxi driver"),
             "forklift": ("cariste (hauteur)", "reach-truck driver"),
             "picker": ("préparateur", "picker"), "loader": ("chargeur", "loader"), "qa": ("inspecteur AQ", "QA")},
    "shift": {"day": ("jour", "day"), "evening": ("soir", "evening"), "night": ("nuit", "night")},
    "season": {"xmas": ("Fêtes (jambon de Noël)", "Holidays (Christmas ham)"),
               "bbq": ("BBQ d'été", "Summer BBQ")},
    "plant": {code: (p["fr"], p["en"]) for code, p in C.PLANTS.items()},
    "kind": {"overexertion": ("effort excessif", "overexertion"),
             "slip_trip_fall": ("chute / glissade", "slip, trip or fall"),
             "struck_by_object": ("heurté par un objet", "struck by an object"),
             "caught_in": ("coincé / écrasé", "caught in or between"),
             "cold_stress_cut": ("froid / coupure", "cold stress or cut"),
             "pedestrian_struck": ("piéton heurté par un chariot", "pedestrian struck by a forklift"),
             "tip_over": ("renversement du chariot", "forklift tip-over"),
             "crushed_by_load": ("écrasé par la charge", "crushed by the load"),
             "other": ("autre", "other"),
             "rack_strike": ("palettier heurté", "rack strike"),
             "dropped_pallet": ("palette échappée", "dropped pallet"),
             "equipment_damage": ("chariot endommagé", "equipment damage")},
}


def lang() -> str:
    return _lang


def set_lang(code: str):
    global _lang
    if code not in LANGS:
        raise SystemExit(f"Unknown language '{code}'. Choices: {', '.join(LANGS)}")
    _lang = code


def toggle():
    set_lang("en" if _lang == "fr" else "fr")


def value(kind: str, v) -> str:
    pair = VALUES.get(kind, {}).get(v)
    if pair is None:
        return str(v)
    return pair[0] if _lang == "fr" else pair[1]


def t(key: str, **kw) -> str:
    pair = TEXT.get(key)
    if pair is None:
        return key
    text = pair[0] if _lang == "fr" else pair[1]
    if not kw:
        return text
    kw = {k: (value(k, v) if k in VALUES else v) for k, v in kw.items()}
    try:
        return text.format(**kw)
    except (KeyError, ValueError, IndexError):
        return text
