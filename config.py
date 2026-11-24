"""Boréal Viandes – every tuning number of the simulation in one place.

Units: times in sim-seconds unless the name says otherwise, distances in
tiles (1 tile = 1 metre), temperatures in °C, money in Canadian dollars.
"""

# ------------------------------------------------------------------ window
SCREEN_W = 1600
SCREEN_H = 900
SIDEBAR_W = 400
FPS = 60
TILE_PX = 16
ZOOM_MIN = 0.25
ZOOM_MAX = 3.0
CAMERA_PAN_SPEED = 900          # screen pixels per real second (arrow keys)

COMPANY_NAME = "Boréal Viandes – Centre de distribution"
SAVE_FILE = "savegame.json"

# ------------------------------------------------------------------ time
REAL_SECONDS_PER_SIM_HOUR = 60.0   # at 1x one in-game hour lasts ~1 real minute
SPEEDS = [1, 2, 5, 10, 20]
TICK_SECONDS = 2.0                 # fixed sim step in the animated view
HEADLESS_TICK_SECONDS = 10.0       # larger step when only generating data
MAX_TICKS_PER_FRAME = 80
START_DATE = (2026, 12, 1)         # December: Christmas ham peak
START_HOUR = 5.5
RANDOM_SEED = 42
END_OF_DAY_SCREEN = True           # pause on a summary screen at midnight

# ------------------------------------------------------------------ map
MAP_W, MAP_H = 180, 92
BUILDING = (40, 4, 139, 76)        # x0, y0, x1, y1 (outer walls)
RECEIVING_DOOR_Y = [18, 30, 42, 54]
SHIPPING_DOOR_Y = [12, 22, 32, 42, 52, 62]
ROAD_Y0, ROAD_Y1 = 80, 89
RACK_LEVELS = 2
RACK_AISLE_W = 4                   # forklift aisle between back-to-back rack rows
RACK_CROSS_AISLE_W = 3             # aisle across the ends of the rack rows
RACK_RUN_MAX = 13                  # longer rack rows are split by a middle cross aisle
TRUCK_LEN = 16
TRUCK_W = 3
TRUCK_CAPACITY = 24                # pallets per trailer
PARKING_Y = [64, 68, 72]           # inbound waiting spots in the west yard

# ------------------------------------------------------------------ movement (tiles per sim-second)
WALK_SPEED = 1.25
JACK_SPEED = 1.0                   # walking with a loaded pallet jack
FORKLIFT_SPEED = 2.2
REACH_SPEED = 1.8
TRUCK_SPEED = 2.2
TRUCK_REVERSE_SPEED = 0.7
CORNER_SLOW_DIST = 1.5
CORNER_SLOW_FACTOR = 0.5
DOOR_OPEN_SECONDS = 20.0           # dock door roll-up time

# ------------------------------------------------------------------ task durations (sim-seconds)
UNLOAD_SCAN_S = 90                 # scan, probe the pallet temperature, label
DROP_S = 10
FORK_ENGAGE_S = 8
FORK_LIFT_S = 6
FORK_LIFT_PER_LEVEL_S = 10
REACH_LIFT_FACTOR = 0.7            # reach trucks lift faster
PICK_CASE_S = 18                   # catch-weight: scan each case label (≈100 cases/h with travel)
PICK_LINE_S = 20
WRAP_S = 90                        # stretch-wrap + label
LOAD_S = 40
QA_INSPECT_S = 600
PALLET_MAX_CASES = 60              # cases on one mixed outbound pallet
MEAL_BREAK_S = 1800

# ------------------------------------------------------------------ forklifts
FORKLIFTS = [("forklift", 5), ("reach", 3)]
BATTERY_DRAIN_PER_TILE = 0.02      # % per metre driven
BATTERY_DRAIN_PER_LIFT = 0.15      # % per lift cycle
BATTERY_IDLE_DRAIN_PER_H = 0.5
BATTERY_CHARGE_PER_H = 28.0
BATTERY_LOW = 25.0
BATTERY_MIN_TO_TAKE = 50.0
FORKLIFT_REPAIR_HOURS = (2, 6)
FORKLIFT_REPAIR_COST = 450.0

# ------------------------------------------------------------------ staff
SHIFTS = {"day": (6, 14), "evening": (14, 22), "night": (22, 6)}
ROLES = ["receiver", "forklift", "picker", "loader", "qa"]
HEADCOUNT = {     # calibrated so pickers run ~50 % busy and on-time ≈ 96 % (see SCENARIOS)
    "day":     {"receiver": 2, "forklift": 2, "picker": 4, "loader": 1, "qa": 1},
    "evening": {"receiver": 1, "forklift": 2, "picker": 4, "loader": 1, "qa": 1},
    "night":   {"receiver": 1, "forklift": 1, "picker": 2, "loader": 1, "qa": 0},
}
WAGES = {"receiver": 26.5, "forklift": 28.0, "picker": 25.0, "loader": 25.0, "qa": 31.0}
SHIFT_PREMIUM = {"day": 1.0, "evening": 1.05, "night": 1.12}
SKILL_SD = 0.15                    # worker skill ~ N(1, sd)
SICK_PROB = 0.03                   # chance a worker calls in sick for a shift

FIRST_NAMES = ["Marc", "Julie", "Sophie", "Martin", "Isabelle", "Patrick", "Nathalie",
               "Éric", "Mélanie", "Simon", "Karine", "Jean-François", "Geneviève",
               "Mathieu", "Valérie", "Alexandre", "Catherine", "Maxime", "Émilie",
               "Olivier", "Annie", "Sébastien", "Marie-Ève", "Guillaume", "Chantal",
               "Frédéric", "Audrey", "Vincent", "Josée", "Samuel", "Amélie", "Kevin"]
LAST_NAMES = ["Tremblay", "Gagnon", "Roy", "Côté", "Bouchard", "Gauthier", "Morin",
              "Lavoie", "Fortin", "Gagné", "Ouellet", "Pelletier", "Bélanger",
              "Lévesque", "Bergeron", "Leblanc", "Paquette", "Girard", "Simard",
              "Boucher", "Caron", "Beaulieu", "Cloutier", "Dubé", "Poirier"]

# ------------------------------------------------------------------ temperature zones
#        setpoint, min, max (spec), refrigeration kW at rest
ZONES = {
    "dock":      {"setpoint": 2.0,   "min": 0.0,   "max": 4.0,   "kw": 35.0},
    "fresh":     {"setpoint": 0.5,   "min": -1.0,  "max": 2.0,   "kw": 45.0},
    "processed": {"setpoint": 2.0,   "min": 0.0,   "max": 4.0,   "kw": 40.0},
    "freezer":   {"setpoint": -20.0, "min": -25.0, "max": -15.0, "kw": 140.0},
    "qa":        {"setpoint": 2.0,   "min": 0.0,   "max": 4.0,   "kw": 6.0},
}
ZONE_TAU_S = 1800.0                # refrigeration time constant
ROOM_DOOR_PASS_S = 25.0            # a cold-room door stays open this long per pass
ROOM_DOOR_LEAK = 3e-4              # heat exchange rate while a room door is open
ROOM_DOOR_STUCK_LEAK = 5e-4        # when a door is stuck open
DOCK_DOOR_LEAK = 2e-5              # per fully open dock door (dock seals)
TEMP_SENSOR_NOISE = 0.15
ALARM_HYSTERESIS = 0.3
EXCURSION_QA_MIN = 120             # pallet minutes out of spec before QA review
# product core temperature follows the room air with this time constant (thermal mass):
# a freezer door left open 1 h warms the air a lot but frozen cases only ~2 °C
PRODUCT_TAU_S = {"chilled": 4 * 3600, "frozen": 8 * 3600}
AMBIENT_BY_MONTH = [-12, -10, -4, 5, 12, 18, 21, 20, 15, 8, 1, -8]
AMBIENT_DAILY_SWING = 5.0
ENERGY_PRICE_KWH = 0.075
ENERGY_AMBIENT_FACTOR = 0.012      # extra load per °C of outdoor heat

# inbound temperature check: accept <= accept_max, QA hold <= qa_max, reject above
INBOUND_SPEC = {
    "fresh":     {"target": 1.0,   "sd": 1.0, "accept_max": 4.0,   "qa_max": 7.0},
    "processed": {"target": 2.0,   "sd": 1.0, "accept_max": 4.0,   "qa_max": 7.0},
    "freezer":   {"target": -19.0, "sd": 1.5, "accept_max": -15.0, "qa_max": -10.0},
}
REEFER_FAIL_WARMUP = (5.0, 12.0)   # °C added to pallets of a failed trailer
QA_RELEASE_PROB = {"near": 0.8, "far": 0.4}

# ------------------------------------------------------------------ products (fictional)
# code, name_fr, name_en, category, zone, kg min, kg max, shelf days,
# cases/pallet, value $/case, base demand cases/day (whole network), plant, season
SKUS = [
    ("P101", "Longe de porc désossée", "Boneless pork loin", "pork", "fresh", 9.2, 10.8, 14, 60, 92.0, 420, "PORC", None),
    ("P102", "Épaule de porc", "Pork shoulder", "pork", "fresh", 10.5, 12.5, 14, 56, 68.0, 300, "PORC", None),
    ("P103", "Côtelettes de porc", "Pork chops", "pork", "fresh", 4.6, 5.4, 10, 96, 48.0, 380, "PORC", None),
    ("V201", "Poitrines de poulet", "Chicken breasts", "poultry", "fresh", 4.7, 5.5, 9, 96, 64.0, 520, "VOLA", None),
    ("V202", "Cuisses de poulet", "Chicken thighs", "poultry", "fresh", 9.0, 11.0, 9, 60, 52.0, 300, "VOLA", None),
    ("V203", "Poulet entier", "Whole chicken", "poultry", "fresh", 11.5, 13.5, 10, 48, 58.0, 240, "VOLA", None),
    ("V204", "Dinde entière", "Whole turkey", "poultry", "fresh", 13.0, 16.0, 14, 40, 74.0, 40, "VOLA", "xmas"),
    ("T301", "Jambon fumé", "Smoked ham", "processed", "processed", 8.0, 10.0, 60, 64, 86.0, 180, "TRAN", "xmas"),
    ("T302", "Bacon tranché", "Sliced bacon", "processed", "processed", 4.9, 5.1, 45, 120, 62.0, 360, "TRAN", None),
    ("T303", "Saucisses déjeuner", "Breakfast sausages", "processed", "processed", 4.9, 5.1, 40, 120, 44.0, 300, "TRAN", None),
    ("T304", "Saucisses BBQ", "BBQ sausages", "processed", "processed", 5.8, 6.2, 40, 110, 49.0, 120, "TRAN", "bbq"),
    ("T305", "Charcuterie tranchée", "Sliced deli meats", "processed", "processed", 3.9, 4.1, 35, 140, 57.0, 340, "TRAN", None),
    ("C401", "Côtes levées surgelées", "Frozen pork ribs", "frozen", "freezer", 9.5, 10.5, 365, 70, 96.0, 160, "SURG", "bbq"),
    ("C402", "Ailes de poulet surgelées", "Frozen chicken wings", "frozen", "freezer", 9.0, 11.0, 365, 72, 71.0, 300, "SURG", None),
    ("C403", "Porc haché surgelé", "Frozen ground pork", "frozen", "freezer", 9.8, 10.2, 270, 80, 42.0, 200, "SURG", None),
]
CATEGORY_COLORS = {
    "pork": (232, 140, 150),
    "poultry": (240, 200, 110),
    "processed": (196, 92, 70),
    "frozen": (120, 180, 235),
}

# ------------------------------------------------------------------ supply plants (fictional)
PLANTS = {
    "PORC": {"fr": "Usine de porc – Beauce", "en": "Pork plant – Beauce",
             "hours": [1, 7, 13, 19], "late_mean": 10, "late_sd": 35},
    "VOLA": {"fr": "Usine de volaille – Lanaudière", "en": "Poultry plant – Lanaudière",
             "hours": [3, 9, 15, 21], "late_mean": 20, "late_sd": 45},
    "TRAN": {"fr": "Usine de transformation – Montérégie", "en": "Further-processing plant – Montérégie",
             "hours": [5, 14], "late_mean": 5, "late_sd": 25},
    "SURG": {"fr": "Entrepôt de congélation – Mauricie", "en": "Cold storage – Mauricie",
             "hours": [8, 17], "late_mean": 30, "late_sd": 60},
}
LATENESS_CLIP_MIN = (-60, 240)
PACK_AGE_DAYS = {"fresh": (0, 2), "processed": (1, 5), "freezer": (5, 60)}

# ------------------------------------------------------------------ inventory policy
COVER_DAYS = {"fresh": 3.5, "processed": 7.0, "freezer": 12.0}
MIN_INBOUND_PALLETS = 10           # a plant only sends another truck if each one carries at least this
MIN_REMAINING_DAYS = {"fresh": 3, "processed": 7, "freezer": 30}

# ------------------------------------------------------------------ customers (fictional)
# id, name, city, kind, size, route, stop (1 = delivered first)
STORES = [
    ("S12", "Marché Saint-Laurent #12", "Montréal", "grocery", 1.0, "R1", 1),
    ("S04", "Épicerie du Plateau #4", "Montréal", "grocery", 0.7, "R1", 2),
    ("S31", "SuperFrais Laval #31", "Laval", "grocery", 1.1, "R2", 1),
    ("S08", "Marché des Mille-Îles #8", "Terrebonne", "grocery", 0.8, "R2", 2),
    ("C03", "Club Entrepôt Gatineau #3", "Gatineau", "club", 1.8, "R3", 1),
    ("R01", "Bistro Le Vieux-Port", "Québec", "restaurant", 0.3, "R4", 1),
    ("S22", "Épicerie Fleurie Québec #22", "Québec", "grocery", 0.9, "R4", 2),
    ("S27", "Marché Sainte-Foy #27", "Québec", "grocery", 1.0, "R4", 3),
    ("S15", "Épicerie Sherbrooke Est #15", "Sherbrooke", "grocery", 0.8, "R5", 1),
    ("R02", "Resto-Grill Le Fumoir", "Granby", "restaurant", 0.35, "R5", 2),
    ("S09", "Marché Trois-Rivières #9", "Trois-Rivières", "grocery", 0.9, "R6", 1),
    ("C07", "Club Entrepôt Lévis #7", "Lévis", "club", 1.6, "R6", 2),
]
# route id -> departure hour, shipping door index (0..5)
ROUTES = {"R1": (5, 0), "R2": (8, 1), "R3": (11, 2), "R4": (14, 3), "R5": (17, 4), "R6": (20, 5)}
ORDER_WINDOW_H = (8, 14)           # orders arrive 14 h to 8 h before departure
CUTOFF_H = 4                       # wave released (allocated + picked) 4 h before departure
OUTBOUND_ARRIVE_BEFORE_H = 2.0
LOAD_RELAX_MIN = 30                # in the last 30 min, load in any order
DEPARTURE_GRACE_MIN = 15           # still "on time" up to 15 min late
DEPARTURE_MAX_WAIT_MIN = 60        # truck leaves with what it has after this

KIND_MIX = {                       # demand multiplier by store kind and category
    "grocery":    {"pork": 1.0, "poultry": 1.0, "processed": 1.0, "frozen": 1.0},
    "club":       {"pork": 0.9, "poultry": 0.9, "processed": 1.0, "frozen": 1.6},
    "restaurant": {"pork": 1.6, "poultry": 1.4, "processed": 0.7, "frozen": 0.5},
}
DEMAND_SCALE = 1.3                 # multiplies every SKU's base demand (network volume)
WEEKDAY_FACTOR = [1.0, 0.95, 1.0, 1.15, 1.2, 0.85, 0.6]   # Monday..Sunday
DEMAND_CV = 0.35
LINE_SKIP_PROB = 0.08
SEASONS = {   # (month, day) start inclusive, end inclusive, factor for season SKUs, factor for the rest
    "xmas": ((12, 1), (12, 24), 3.2, 1.08),
    "bbq":  ((6, 1), (9, 7), 2.4, 1.04),
}
POST_XMAS_LULL = ((12, 26), (12, 31), 0.75)
BBQ_HEAT_SENSITIVITY = 0.04        # BBQ demand +4 % per °C above 18 °C (summer)

# ------------------------------------------------------------------ quality
MISPICK_PROB = 0.004               # per case line, divided by worker skill
MISPICK_CATCH_PROB = 0.4           # caught at loading check

# ------------------------------------------------------------------ economy
STARTING_CASH = 250_000.0
DISTRIBUTION_FEE_RATE = 0.06       # revenue = product value × rate per case shipped
LATE_PENALTY_PER_ORDER = 250.0
SHORT_PENALTY_PER_CASE = 12.0
MISPICK_PENALTY = 35.0
EXPEDITE_COST = 380.0
FIXED_DAILY_COST = 9_000.0         # rent, maintenance, admin
REJECTED_LOAD_COST_SHARE = 1.0     # share of product value lost on pallets WE let go out of spec
REJECT_HANDLING_COST = 45.0        # $ per pallet refused at the door / failed inbound QA (supplier credits the product)
COMPLIANCE_TARGET = 0.98

# ------------------------------------------------------------------ random events (expected per day)
EVENT_RATES = {
    "late_truck": 1.5,
    "reefer_failure": 0.35,
    "freezer_door": 0.25,
    "forklift_breakdown": 0.4,
    "rush_order": 0.5,
    "recall": 0.07,
}
FREEZER_DOOR_STUCK_MIN = (20, 90)
LATE_TRUCK_EXTRA_MIN = (60, 240)
RECALL_AUTO_PULL_H = (1.0, 4.0)    # supervisor pulls the lot if the player does not
DISPOSE_AFTER_H = 2.0

# ------------------------------------------------------------------ data export
DATA_DIR = "data"
TEMP_LOG_EVERY_MIN = 5

# ------------------------------------------------------------------ scenarios (python main.py --scenario NAME)
SCENARIOS = {
    "baseline": {},
    "lean_staff": {"HEADCOUNT": {      # one picker fewer on day/evening, one forklift fewer
        "day":     {"receiver": 1, "forklift": 1, "picker": 3, "loader": 1, "qa": 1},
        "evening": {"receiver": 1, "forklift": 1, "picker": 3, "loader": 1, "qa": 1},
        "night":   {"receiver": 1, "forklift": 1, "picker": 2, "loader": 1, "qa": 0}}},
    "extra_pickers": {"HEADCOUNT": {   # +2 pickers day/evening, +1 night
        "day":     {"receiver": 2, "forklift": 2, "picker": 6, "loader": 1, "qa": 1},
        "evening": {"receiver": 1, "forklift": 2, "picker": 6, "loader": 1, "qa": 1},
        "night":   {"receiver": 1, "forklift": 1, "picker": 3, "loader": 1, "qa": 0}}},
    "summer_bbq": {"START_DATE": (2026, 6, 15)},
    "chaos": {"EVENT_RATES": {"late_truck": 4.0, "reefer_failure": 1.5, "freezer_door": 1.0,
                              "forklift_breakdown": 1.5, "rush_order": 1.5, "recall": 0.3}},
}


def apply_scenario(name):
    """Overwrite module-level settings with a named scenario's values."""
    if name not in SCENARIOS:
        raise SystemExit(f"Unknown scenario '{name}'. Choices: {', '.join(SCENARIOS)}")
    for key, value in SCENARIOS[name].items():
        globals()[key] = value
