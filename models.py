"""Plain dataclasses for everything the simulation tracks.

Objects reference each other by integer id (never by Python reference) so the
whole state can be dumped to JSON and loaded back.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields


@dataclass
class SKU:
    code: str
    name_fr: str
    name_en: str
    category: str          # pork / poultry / processed / frozen
    zone: str              # fresh / processed / freezer
    weight_min: float
    weight_max: float
    shelf_days: int
    cases_per_pallet: int
    value: float           # product value per case ($)
    base_demand: float     # cases per day for the whole network
    plant: str
    season: str | None = None

    @property
    def temp_class(self) -> str:
        return "frozen" if self.zone == "freezer" else "chilled"

    def name(self, lang: str) -> str:
        return self.name_fr if lang == "fr" else self.name_en


@dataclass
class Store:
    id: str
    name: str
    city: str
    kind: str              # grocery / club / restaurant
    size: float
    route: str
    stop: int              # 1 = delivered first, so loaded last


@dataclass
class Pallet:
    id: int
    sku: str | None        # None for mixed outbound pallets
    lot: int
    cases: int
    sscc: str = ""            # GS1 SSCC-18 licence plate on the pallet label
    pack_day: float = 0.0  # sim day index (can be negative = before the game started)
    bb_day: float = 0.0    # best-before, sim day index
    temp_c: float = 2.0
    status: str = "inbound"   # inbound, received, qa_hold, stored, staged_out, loaded,
                              # shipped, rejected, spoiled, recalled
    loc: str = "truck"        # truck, spot, slot, worker, forklift, gone
    ref: int | None = None    # id of the truck / spot / slot / worker / forklift
    plant: str = ""
    truck_id: int | None = None
    reserved: int = 0         # cases promised to pick jobs
    weight_kg: float = 0.0
    excursion_min: float = 0.0
    qa_reason: str = ""       # why it went to QA: inbound (supplier's liability) / excursion (ours)
    recalled: bool = False
    mixed: bool = False
    store: str | None = None
    order_id: int | None = None
    contents: list = field(default_factory=list)   # mixed pallets: [sku, lot, cases, kg]
    temp_class: str = "chilled"
    received_t: float | None = None
    x: float = 0.0            # last floor position (tile units), for drawing and floating text
    y: float = 0.0


@dataclass
class RackSlot:
    id: int
    zone: str
    x: int                 # rack tile column
    y: int                 # top tile of the 2-tile bay
    level: int
    ax: int                # aisle tile the operator stands on
    ay: int
    pallet: int | None = None
    reserved_for: int | None = None


@dataclass
class Spot:
    """A floor position for one pallet: inbound staging, outbound lane, QA cage or drop point."""
    id: int
    kind: str              # in / out / qa / drop (aisle-end pick-up point for reach trucks)
    x: int
    y: int
    door: int | None = None
    zone: str | None = None    # drop points: the cold room they serve
    pallet: int | None = None
    reserved: int | None = None


@dataclass
class Door:
    id: int
    side: str              # in / out
    x: int
    y: int
    open: float = 0.0      # 0 closed .. 1 fully rolled up
    truck: int | None = None


@dataclass
class Truck:
    id: int
    kind: str              # in / out
    origin: str            # plant code (in) or route id (out)
    state: str = "scheduled"   # scheduled, queued, approach, parked, docked, departing, gone
    dest: str = ""             # dock / park
    door: int | None = None
    park: int | None = None
    x: float = -30.0
    y: float = 82.0
    heading: float = 0.0       # radians, direction the cab points
    waypoints: list = field(default_factory=list)   # [x, y, reverse]
    pallets: list = field(default_factory=list)
    sched_t: float = 0.0
    planned_t: float = 0.0     # expected gate time after lateness
    arrive_t: float | None = None
    dock_t: float | None = None
    unload_end_t: float | None = None
    leave_t: float | None = None
    departure_t: float = 0.0   # outbound: scheduled departure
    reefer_fail: bool = False
    pallets_ordered: int = 0   # inbound: what we ordered (the plant may short-ship)
    aged_load: bool = False    # inbound: plant shipped older-than-usual product
    seq_violations: int = 0
    trail: list = field(default_factory=list)


@dataclass
class Order:
    id: int
    store: str
    route: str
    created_t: float
    cutoff_t: float
    departure_t: float
    lines: list = field(default_factory=list)   # dicts: sku, qty, alloc, picked, shipped
    status: str = "open"       # open, released, picked, closed
    priority: int = 0
    rush: bool = False
    pallets: list = field(default_factory=list)
    jobs_open: int = 0
    departed: bool = False
    on_truck: bool = True      # False once anything had to be expedited
    expedited: bool = False
    mispicks_uncaught: int = 0
    revenue: float = 0.0
    late_min: float = 0.0
    shipped_t: float | None = None


@dataclass
class Worker:
    id: int
    name: str
    role: str              # receiver / forklift / picker / loader / qa
    shift: str             # day / evening / night
    skill: float = 1.0
    state: str = "off"     # off, active, leaving
    task: str = ""         # '', idle, job, mount, charge, break, leave
    x: float = 117.5
    y: float = 9.5
    heading: float = 0.0
    path: list = field(default_factory=list)
    steps: list = field(default_factory=list)
    job: int | None = None
    forklift: int | None = None
    carrying: int | None = None
    cargo: list = field(default_factory=list)       # taxi: pallet ids on the rider jack (max TAXI_PALLETS)
    build_sscc: str = ""                            # picker: licence plate of the outbound pallet being built
    jack_load: list = field(default_factory=list)   # [sku, lot, cases, kg]
    injured_until: float = 0.0                      # off work (lost-time injury) until this sim time
    activity: str = ""
    break_at: float = 0.0
    break_done: bool = False
    sick: bool = False
    fired: bool = False
    on_since: float = 0.0
    hours: float = 0.0
    tasks_done: int = 0
    cases_picked: int = 0
    dist: float = 0.0
    mark_t: float = 0.0
    trail: list = field(default_factory=list)


@dataclass
class Forklift:
    id: int
    kind: str              # forklift / reach
    charger: int
    x: float = 0.0
    y: float = 0.0
    heading: float = 0.0
    battery: float = 100.0
    state: str = "idle"    # idle, busy, charging, broken
    operator: int | None = None
    reserved_by: int | None = None
    carrying: int | None = None
    fork_h: float = 0.0
    fork_target: float = 0.0
    pending_break: bool = False
    broken_until: float | None = None
    trail: list = field(default_factory=list)


@dataclass
class Job:
    id: int
    kind: str              # unload, putaway, move_qa, inspect, pick, load
    priority: float
    created_t: float
    pallet: int | None = None
    target: int | None = None   # slot id or spot id
    order: int | None = None
    truck: int | None = None
    picks: list = field(default_factory=list)
    reason: str = ""
    from_loc: str = ""          # location code the pallet was taken from (for the scan log)
    temp_class: str = "chilled"
    worker: int | None = None
    start_t: float | None = None


@dataclass
class Zone:
    key: str
    rects: list            # [[x0, y0, x1, y1], ...] inclusive tiles
    setpoint: float
    tmin: float
    tmax: float
    kw: float
    temp: float = 0.0
    door_open_s: float = 0.0
    stuck_open: bool = False
    alarm: bool = False
    kwh_today: float = 0.0
    door_passes_today: int = 0


def to_dict(obj) -> dict:
    return asdict(obj)


def from_dict(cls, data: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})
