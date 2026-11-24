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
CAMERA_ZOOM_RATE = 2.5          # zoom factor per real second while +/- (or Page Up/Down) is held

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

# ------------------------------------------------------------------ site size (the layout is generated from these)
RECEIVING_DOORS = 6
SHIPPING_DOORS = 14
ROOMS = {"fresh": 5, "processed": 4, "freezer": 5}   # back-to-back rack pairs per cold room
RACK_LEVELS = 5                    # beam levels; level 0 is the floor, the rest need a reach truck
RACK_RUN = 22                      # tiles per rack run (11 two-tile bays)
RACK_SEGMENTS = 3                  # runs per row, separated by 2-tile cross aisles
PARKING_ROWS, PARKING_PER_ROW = 4, 8   # truck yard south of the road (trailers waiting for a door)
TRUCK_LEN = 16
TRUCK_W = 3
TRUCK_CAPACITY = 30                # max pallets on a 53' reefer trailer
TRUCK_CAPACITY_MIN = 28            # each inbound trailer is loaded to 28–30 pallets
OUTBOUND_TRUCK_CAPACITY = 30

# Dock layout. "split": receiving doors on the west wall, shipping doors on the east wall (flow-through).
# "shared": every door on the east wall both receives and ships (U-flow): no west dock, a narrower
# building; each door keeps its outbound staging by the wall and gets SHARED_IN_COLS columns of
# inbound staging behind it. An inbound trailer only takes a door whose next outbound trailer is not
# due within INBOUND_DOOR_BUFFER_H hours.
DOCK_LAYOUT = "split"
SHARED_IN_COLS = 5                 # inbound staging columns per door row (2 rows a door)
INBOUND_DOOR_BUFFER_H = 2.0        # hours kept free before a door's outbound trailer arrives


# ---- derived geometry (tiles). Don't edit: change the numbers above (apply_scenario re-derives it).
def _derive_geometry():
    global ROOM_Y0, ROOM_Y1, ROOM_X, BUILDING, RECEIVING_DOOR_Y, SHIPPING_DOOR_Y, ROAD_Y0, ROAD_Y1
    global IN_LANE_Y, OUT_LANE_Y, PARKING, MAP_W, MAP_H
    shared = DOCK_LAYOUT == "shared"
    bx0, by0 = 44, 4                                   # west wall, north wall
    room_w = {k: 5 * n + 5 for k, n in ROOMS.items()}  # wall + 2-wide pitch per pair + aisles
    ROOM_Y0 = by0 + 16                                 # north wall of the cold rooms
    ROOM_Y1 = ROOM_Y0 + 3 + RACK_SEGMENTS * RACK_RUN + (RACK_SEGMENTS - 1) * 2 + 3
    ROOM_X = {}
    x = bx0 + (4 if shared else 18)                    # west dock (receiving) only in the split layout
    for k, w in room_w.items():
        ROOM_X[k] = x
        x += w + 2
    bx1 = x + 16 + (SHARED_IN_COLS + 1 if shared else 0)   # east wall
    BUILDING = (bx0, by0, bx1, ROOM_Y1 + 4)            # x0, y0, x1, y1 (outer walls)
    RECEIVING_DOOR_Y = [] if shared else [ROOM_Y0 - 6 + i * ((BUILDING[3] - ROOM_Y0) // RECEIVING_DOORS)
                                          for i in range(RECEIVING_DOORS)]
    SHIPPING_DOOR_Y = [by0 + 8 + i * 6 for i in range(SHIPPING_DOORS)]   # shared: these doors do both
    ROAD_Y0, ROAD_Y1 = BUILDING[3] + 4, BUILDING[3] + 13
    IN_LANE_Y, OUT_LANE_Y = ROAD_Y0 + 2.5, ROAD_Y0 + 6.5
    PARKING = [(12 + 20 * i, ROAD_Y1 + 5 + 4 * r) for r in range(PARKING_ROWS) for i in range(PARKING_PER_ROW)]
    MAP_W = bx1 + 41
    MAP_H = PARKING[-1][1] + 4
    assert all(y + 2 < BUILDING[3] for y in SHIPPING_DOOR_Y + RECEIVING_DOOR_Y), "too many doors"


_derive_geometry()

# ------------------------------------------------------------------ movement (tiles per sim-second)
WALK_SPEED = 1.25
JACK_SPEED = 1.0                   # walking with a loaded pallet jack
TAXI_SPEED = 2.0                   # rider pallet jack ("taxi"), loaded or not
FORKLIFT_SPEED = 2.2
REACH_SPEED = 1.8
TRUCK_SPEED = 2.2
TRUCK_REVERSE_SPEED = 0.7
CORNER_SLOW_DIST = 1.5
CORNER_SLOW_FACTOR = 0.5
DOOR_OPEN_SECONDS = 20.0           # dock door roll-up time

# ------------------------------------------------------------------ task durations (sim-seconds)
UNLOAD_SCAN_S = 90                 # scan, probe the pallet temperature, label
DOCK_CHECKIN_S = 900               # paperwork, seal check, first probe before unloading starts
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
TAXI_PALLETS = 2                   # a taxi carries up to 2 pallets per trip (dock -> drop point)
TAXI_MAX_WAIT_S = 600              # ...and leaves with 1 if a pallet has waited this long
MEAL_BREAK_S = 1800

# ------------------------------------------------------------------ forklifts
FORKLIFTS = [("forklift", 4), ("reach", 14)]
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
ROLES = ["receiver", "taxi", "forklift", "picker", "loader", "qa"]
HEADCOUNT = {     # "forklift" = reach-truck drivers (put-away to height); "taxi" = dock -> drop point
    "day":     {"receiver": 5, "taxi": 2, "forklift": 3, "picker": 18, "loader": 3, "qa": 1},
    "evening": {"receiver": 2, "taxi": 1, "forklift": 2, "picker": 18, "loader": 3, "qa": 1},
    "night":   {"receiver": 3, "taxi": 2, "forklift": 2, "picker": 9, "loader": 2, "qa": 1},
}
WAGES = {"receiver": 26.5, "taxi": 26.5, "forklift": 28.0, "picker": 25.0, "loader": 25.0, "qa": 31.0}
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
    "dock":      {"setpoint": 2.0,   "min": 0.0,   "max": 4.0,   "kw": 90.0},
    "fresh":     {"setpoint": 0.5,   "min": -1.0,  "max": 2.0,   "kw": 115.0},
    "processed": {"setpoint": 2.0,   "min": 0.0,   "max": 4.0,   "kw": 100.0},
    "freezer":   {"setpoint": -20.0, "min": -25.0, "max": -15.0, "kw": 350.0},
    "qa":        {"setpoint": 2.0,   "min": 0.0,   "max": 4.0,   "kw": 8.0},
}
ZONE_TAU_S = 1800.0                # refrigeration time constant
ROOM_DOOR_PASS_S = 25.0            # a cold-room door stays open this long per pass
ROOM_DOOR_LEAK = 3e-4              # heat exchange rate while a room door is open (for a room of REF_ROOM_AREA)
ROOM_DOOR_STUCK_LEAK = 5e-4        # when a door is stuck open
REF_ROOM_AREA = 918                # m² the leak rates were tuned on; bigger rooms (more air) warm slower
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
# short_prob: chance each ordered pallet is not shipped; aged_prob: chance a whole load is old stock
PLANTS = {
    "PORC": {"fr": "Usine de porc – Beauce", "en": "Pork plant – Beauce",
             "hours": [3, 9], "late_mean": 10, "late_sd": 35, "short_prob": 0.03, "aged_prob": 0.06},
    "VOLA": {"fr": "Usine de volaille – Lanaudière", "en": "Poultry plant – Lanaudière",
             "hours": [3, 10], "late_mean": 20, "late_sd": 45, "short_prob": 0.07, "aged_prob": 0.09},
    "TRAN": {"fr": "Usine de transformation – Montérégie", "en": "Further-processing plant – Montérégie",
             "hours": [4], "late_mean": 5, "late_sd": 25, "short_prob": 0.02, "aged_prob": 0.04},
    "SURG": {"fr": "Entrepôt de congélation – Mauricie", "en": "Cold storage – Mauricie",
             "hours": [5], "late_mean": 30, "late_sd": 60, "short_prob": 0.05, "aged_prob": 0.05},
}
LATENESS_CLIP_MIN = (-60, 240)
PACK_AGE_DAYS = {"fresh": (0, 2), "processed": (1, 5), "freezer": (5, 60)}
AGED_EXTRA_DAYS = {"fresh": (3, 5), "processed": (10, 20), "freezer": (30, 90)}   # added on an aged load
ORDER_NOISE_CV = 0.20              # buyer's order quantity error (forecast + judgement)

# ------------------------------------------------------------------ inventory policy
COVER_DAYS = {"fresh": 2.0, "processed": 4.0, "freezer": 8.0}   # days of stock targeted on order
MIN_INBOUND_PALLETS = 26           # a plant only sends another truck if each one carries at least this
MIN_REMAINING_DAYS = {"fresh": 3, "processed": 7, "freezer": 30}

# ------------------------------------------------------------------ customers (fictional)
# 48 stores on 16 routes (3 stops each). Fixed list, so every run and dashboard sees the same network.
# id, name, city, kind, size, route, stop (1 = delivered first)
_CHAINS = {"grocery": ["Marché Saint-Laurent", "Épicerie du Quartier", "SuperFrais", "Marché Fleuri",
                       "Épicerie Boréale", "Marché du Village"],
           "club": ["Club Entrepôt"], "restaurant": ["Bistro", "Resto-Grill", "Brasserie"]}
_ROUTE_CITIES = ["Montréal", "Montréal", "Laval", "Longueuil", "Terrebonne", "Gatineau", "Québec", "Québec",
                 "Lévis", "Sherbrooke", "Trois-Rivières", "Granby", "Saint-Jérôme", "Drummondville",
                 "Saint-Hyacinthe", "Saguenay"]
_KINDS = ["grocery", "grocery", "restaurant", "grocery", "club", "grocery", "grocery", "restaurant"]
_SIZES = {"grocery": [0.7, 0.9, 1.0, 1.1, 1.2, 0.8], "club": [1.6, 1.8, 2.0], "restaurant": [0.25, 0.35, 0.3]}
STORES = []
for _r, _city in enumerate(_ROUTE_CITIES):
    for _stop in (1, 2, 3):
        _n = len(STORES)
        _kind = _KINDS[_n % len(_KINDS)]
        _chain = _CHAINS[_kind][_n % len(_CHAINS[_kind])]
        _prefix = {"grocery": "S", "club": "C", "restaurant": "H"}[_kind]
        _num = 10 + (_n * 7) % 89
        _name = f"{_chain} {_city} #{_num}" if _kind != "restaurant" else f"{_chain} {_city} {_n}"
        STORES.append((f"{_prefix}{_n + 1:02d}", _name, _city, _kind,
                       _SIZES[_kind][_n % len(_SIZES[_kind])], f"R{_r + 1:02d}", _stop))
# route id -> departure hour, shipping door index (0..SHIPPING_DOORS-1); one departure per hour 03:00–18:00
ROUTES = {f"R{i + 1:02d}": (3 + i, i % SHIPPING_DOORS) for i in range(len(_ROUTE_CITIES))}
ORDER_WINDOW_H = (8, 14)           # orders arrive 14 h to 8 h before departure
CUTOFF_H = 4                       # wave released (allocated + picked) 4 h before departure
OUTBOUND_ARRIVE_BEFORE_H = 2.0     # empty trailer pulled to its shipping door
OUTBOUND_YARD_BEFORE_H = 8.0       # carrier drops the empty trailer in the yard
LOAD_RELAX_MIN = 30                # in the last 30 min, load in any order
DEPARTURE_GRACE_MIN = 15           # still "on time" up to 15 min late
DEPARTURE_MAX_WAIT_MIN = 60        # truck leaves with what it has after this

KIND_MIX = {                       # demand multiplier by store kind and category
    "grocery":    {"pork": 1.0, "poultry": 1.0, "processed": 1.0, "frozen": 1.0},
    "club":       {"pork": 0.9, "poultry": 0.9, "processed": 1.0, "frozen": 1.6},
    "restaurant": {"pork": 1.6, "poultry": 1.4, "processed": 0.7, "frozen": 0.5},
}
DEMAND_SCALE = 6.5                 # multiplies every SKU's base demand (≈ 25,000 cases/day network)
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
LATE_PENALTY_SHARE = 0.03          # late order fine: 3 % of its product value (retailer OTIF programs,
                                   # e.g. Walmart charges 3 % of cost of goods on missed OTIF deliveries)
SHORT_PENALTY_PER_CASE = 12.0
MISPICK_PENALTY = 35.0
EXPEDITE_COST = 380.0
FIXED_DAILY_COST = 67_000.0        # rent, maintenance, admin, fleet, IT (≈ 4 % net margin at baseline)
REJECTED_LOAD_COST_SHARE = 1.0     # share of product value lost on pallets WE let go out of spec
REJECT_HANDLING_COST = 45.0        # $ per pallet refused at the door / failed inbound QA (supplier credits the product)
COMPLIANCE_TARGET = 0.98

# ------------------------------------------------------------------ random events (expected per day)
EVENT_RATES = {
    "late_truck": 4.0,
    "reefer_failure": 1.0,
    "freezer_door": 0.5,
    "forklift_breakdown": 1.5,
    "rush_order": 2.0,
    "recall": 0.07,
}
FREEZER_DOOR_STUCK_MIN = (20, 90)
LATE_TRUCK_EXTRA_MIN = (60, 240)
RECALL_AUTO_PULL_H = (1.0, 4.0)    # supervisor pulls the lot if the player does not
DISPOSE_AFTER_H = 2.0

# ------------------------------------------------------------------ incidents (injuries, forklift accidents)
# Rates are per hour worked (injuries) or per hour a forklift is driven (forklift accidents).
# Sources: lost-time injury rate 1.30 per 100 workers per year in transportation & warehousing
# (Ontario OHS report 2022-23); forklift accident types among 87 serious/fatal Québec cases
# (IRSST R-601): struck pedestrian 31 %, tip-over 28 %, crushed by the load 22 %, other 19 %.
# Values marked "assumption" have no Canadian statistic behind them and are documented as such.
FTE_HOURS_PER_YEAR = 2000
LOST_TIME_INJURY_RATE = 1.30 / 100 / FTE_HOURS_PER_YEAR     # per worker-hour
MEDICAL_AID_PER_LOST_TIME = 2.5    # assumption: treated injuries (back next shift) per lost-time injury
INJURY_TYPES = {                   # assumption: typical warehouse mix (manual handling dominates)
    "overexertion": 0.40, "slip_trip_fall": 0.22, "struck_by_object": 0.18,
    "caught_in": 0.08, "cold_stress_cut": 0.12,
}
INJURY_DAYS_LOST = (10, 1.0, 180)  # assumption: lognormal median days off, sigma, cap
INJURY_INDEMNITY_SHARE = 0.90      # CNESST income replacement: 90 % of net salary (cost model)
FORKLIFT_INJURY_RATE = 1.5 * LOST_TIME_INJURY_RATE           # assumption: drivers 1.5x average risk, per driven hour
FORKLIFT_INJURY_TYPES = {"pedestrian_struck": 0.31, "tip_over": 0.28, "crushed_by_load": 0.22, "other": 0.19}
FORKLIFT_DAMAGE_PER_INJURY = 30    # assumption: Bird's safety triangle (1 serious : 30 property damage)
FORKLIFT_DAMAGE_TYPES = {"rack_strike": 0.45, "dropped_pallet": 0.35, "equipment_damage": 0.20}   # assumption
RACK_REPAIR_HOURS = (4, 24)        # damaged bay out of service
RACK_REPAIR_COST = 900.0
DROPPED_PALLET_LOSS = (0.10, 0.50) # share of the pallet's cases destroyed
INCIDENT_RATE_MULT = 1.0           # scenario knob

# ------------------------------------------------------------------ data export
DATA_DIR = "data"
CASE_SCANS = False                 # also log every case scanned at picking (fact_case_scans; ~25k rows/day)
TEMP_LOG_EVERY_MIN = 5

# ------------------------------------------------------------------ scenarios (python main.py --scenario NAME)
SCENARIOS = {
    "baseline": {},
    "lean_staff": {"HEADCOUNT": {      # 2 pickers fewer per shift (1 at night), one receiver fewer on day
        "day":     {"receiver": 4, "taxi": 2, "forklift": 3, "picker": 16, "loader": 3, "qa": 1},
        "evening": {"receiver": 2, "taxi": 1, "forklift": 2, "picker": 16, "loader": 3, "qa": 1},
        "night":   {"receiver": 3, "taxi": 2, "forklift": 2, "picker": 8, "loader": 2, "qa": 1}}},
    "extra_pickers": {"HEADCOUNT": {   # +4 pickers day/evening, +2 night
        "day":     {"receiver": 5, "taxi": 2, "forklift": 3, "picker": 22, "loader": 3, "qa": 1},
        "evening": {"receiver": 2, "taxi": 1, "forklift": 2, "picker": 22, "loader": 3, "qa": 1},
        "night":   {"receiver": 3, "taxi": 2, "forklift": 2, "picker": 11, "loader": 2, "qa": 1}}},
    "summer_bbq": {"START_DATE": (2026, 6, 15)},
    "chaos": {"EVENT_RATES": {"late_truck": 10.0, "reefer_failure": 4.0, "freezer_door": 2.0,
                              "forklift_breakdown": 5.0, "rush_order": 5.0, "recall": 0.3},
              "INCIDENT_RATE_MULT": 3.0},
    "shared_dock": {"DOCK_LAYOUT": "shared"},   # U-flow: 14 doors on one wall receive and ship
}


def apply_scenario(name):
    """Overwrite module-level settings with a named scenario's values. Call it before importing
    simulation (which reads the geometry at import)."""
    if name not in SCENARIOS:
        raise SystemExit(f"Unknown scenario '{name}'. Choices: {', '.join(SCENARIOS)}")
    for key, value in SCENARIOS[name].items():
        globals()[key] = value
    _derive_geometry()
