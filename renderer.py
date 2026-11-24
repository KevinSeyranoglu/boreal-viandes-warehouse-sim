"""Draws the warehouse: camera, floor plan, zones, racks, doors and agents.

Only reads the simulation state. Positions are interpolated between the
previous and the current sim tick (snapshot() + alpha) so 60 fps stays smooth
at any speed.
"""
from __future__ import annotations

import math

import pygame

import config as C
import i18n
from simulation import DOCKDOOR, FLOOR, RACK, ROAD, WALL, YARD

T = C.TILE_PX
VIEW_W = C.SCREEN_W - C.SIDEBAR_W

# ---- colours
TILE_COLORS = {
    YARD: (88, 98, 88),
    ROAD: (58, 60, 64),
    FLOOR: (196, 198, 194),
    WALL: (52, 56, 66),
    RACK: (90, 110, 140),
    DOCKDOOR: (70, 72, 80),
}
ZONE_TINT = {
    "dock": (190, 205, 215),
    "fresh": (178, 222, 210),
    "processed": (232, 196, 190),
    "freezer": (190, 214, 245),
    "qa": (236, 222, 160),
}
ROLE_COLORS = {
    "receiver": (60, 120, 220),
    "taxi": (20, 180, 190),
    "forklift": (240, 170, 30),
    "picker": (40, 170, 90),
    "loader": (150, 80, 200),
    "qa": (230, 70, 140),
}
MIXED_COLOR = (226, 228, 236)
FX_COLORS = {"good": (60, 200, 100), "warn": (245, 180, 40), "bad": (235, 60, 60), "info": (230, 230, 230)}
TEXT_DARK = (30, 32, 38)
TEXT_LIGHT = (240, 242, 245)
ALARM = (235, 40, 40)


def lerp(a, b, f):
    return a + (b - a) * f


class Fonts:
    """System sans font with real bold. `size` uses pygame's default-font scale (≈ 0.72 px)."""
    FACES = "notosans,dejavusans,liberationsans,arial"

    def __init__(self):
        self._cache = {}

    def get(self, size, bold=False):
        key = (size, bold)
        if key not in self._cache:
            self._cache[key] = pygame.font.SysFont(self.FACES, max(8, round(size * 0.72)), bold=bold)
        return self._cache[key]

    def render(self, text, size, color, bold=False):
        return self.get(size, bold).render(text, True, color)


# ====================================================================== camera
class Camera:
    """World pixel (at TILE_PX per tile) shown at the view's top-left, plus a zoom factor."""

    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.zoom = 1.0
        self.home()

    def home(self):
        mw, mh = C.MAP_W * T, C.MAP_H * T
        self.zoom = max(C.ZOOM_MIN, min(C.ZOOM_MAX, min(VIEW_W / mw, C.SCREEN_H / mh)))
        self.x = (mw - VIEW_W / self.zoom) / 2
        self.y = (mh - C.SCREEN_H / self.zoom) / 2

    def focus(self, tx, ty, zoom):
        """Centre the view on tile (tx, ty) at the given zoom."""
        self.zoom = max(C.ZOOM_MIN, min(C.ZOOM_MAX, zoom))
        self.x = tx * T - VIEW_W / self.zoom / 2
        self.y = ty * T - C.SCREEN_H / self.zoom / 2

    def pan(self, dx_screen, dy_screen):
        self.x -= dx_screen / self.zoom
        self.y -= dy_screen / self.zoom
        self._clamp()

    def zoom_at(self, factor, sx, sy):
        wx, wy = self.screen_to_world_px(sx, sy)
        self.zoom = max(C.ZOOM_MIN, min(C.ZOOM_MAX, self.zoom * factor))
        self.x = wx - sx / self.zoom
        self.y = wy - sy / self.zoom
        self._clamp()

    def _clamp(self):
        """Keep the view centre within the map plus a margin."""
        mw, mh = C.MAP_W * T, C.MAP_H * T
        hw, hh = VIEW_W / self.zoom / 2, C.SCREEN_H / self.zoom / 2
        margin = 200 / self.zoom
        self.x = max(-margin - hw, min(mw + margin - hw, self.x))
        self.y = max(-margin - hh, min(mh + margin - hh, self.y))

    def screen_to_world_px(self, sx, sy):
        return self.x + sx / self.zoom, self.y + sy / self.zoom

    def screen_to_tile(self, sx, sy):
        wx, wy = self.screen_to_world_px(sx, sy)
        return wx / T, wy / T

    def to_screen(self, tx, ty):
        """Tile coordinates (float) -> screen pixels."""
        return (tx * T - self.x) * self.zoom, (ty * T - self.y) * self.zoom

    def rect(self, x0, y0, w, h):
        sx, sy = self.to_screen(x0, y0)
        s = T * self.zoom
        return pygame.Rect(round(sx), round(sy), max(1, round(w * s)), max(1, round(h * s)))


# ====================================================================== renderer
class Renderer:
    def __init__(self, sim, fonts: Fonts):
        self.fonts = fonts
        self.cam = Camera()
        self.view = pygame.Rect(0, 0, VIEW_W, C.SCREEN_H)
        self.floaters = []          # [x, y, text_key, kw, colour key, age]
        self.fog = []               # [x, y, age]
        self.time = 0.0             # real seconds, for blinking and flashes
        self.set_sim(sim)

    def set_sim(self, sim):
        self.sim = sim
        self.base = self._build_base(sim.layout)
        self._scaled_key = None
        self.floaters.clear()
        self.fog.clear()

    # ------------------------------------------------------------ static floor plan
    def _build_base(self, L):
        surf = pygame.Surface((L.w * T, L.h * T))
        for y in range(L.h):
            row = y * L.w
            for x in range(L.w):
                v = L.tiles[row + x]
                col = TILE_COLORS[v]
                if v == FLOOR:
                    zone = L.zone_map.get(row + x)
                    if zone:
                        col = ZONE_TINT[zone]
                surf.fill(col, (x * T, y * T, T, T))
        # subtle tile grid on the building floor
        overlay = pygame.Surface((L.w * T, L.h * T), pygame.SRCALPHA)
        bx0, by0, bx1, by1 = C.BUILDING
        for x in range(bx0, bx1 + 2):
            pygame.draw.line(overlay, (0, 0, 0, 14), (x * T, by0 * T), (x * T, (by1 + 1) * T))
        for y in range(by0, by1 + 2):
            pygame.draw.line(overlay, (0, 0, 0, 14), (bx0 * T, y * T), ((bx1 + 1) * T, y * T))
        surf.blit(overlay, (0, 0))
        # rack bays (each 2 tiles tall)
        for slot in L.slots:
            if slot.level == 0:
                pygame.draw.rect(surf, (60, 74, 100), (slot.x * T, slot.y * T, T, 2 * T), 1)
        # freezer frost speckles (fixed pattern)
        fx0, fy0, fx1, fy1 = L.areas["freezer"]
        rnd = 12345
        for _ in range(900):
            rnd = (rnd * 1103515245 + 12345) & 0x7FFFFFFF
            px = fx0 * T + T + rnd % ((fx1 - fx0 - 1) * T)
            rnd = (rnd * 1103515245 + 12345) & 0x7FFFFFFF
            py = fy0 * T + T + rnd % ((fy1 - fy0 - 1) * T)
            surf.fill((236, 244, 255), (px, py, 2, 2))
        # road centre dashes
        mid = (C.ROAD_Y0 + C.ROAD_Y1 + 1) / 2 * T
        for x in range(0, L.w * T, 48):
            pygame.draw.line(surf, (220, 200, 90), (x, mid), (x + 24, mid), 2)
        # parking bays, chargers, break-room seats
        for px, py in C.PARKING:                      # trailer yard
            pygame.draw.rect(surf, (210, 210, 210), ((px - 8) * T, py * T - 2, 17 * T, T + 4), 1)
        for sp in L.spots:                            # drop points (P&D) for the reach trucks
            if sp.kind == "drop":
                pygame.draw.rect(surf, (230, 190, 40), (sp.x * T + 1, sp.y * T + 1, T - 2, T - 2), 2)
        for cx, cy in L.chargers:
            pygame.draw.rect(surf, (60, 160, 90), (cx * T + 2, cy * T + 2, T - 4, T - 4), 2)
        for sx, sy in L.seats:
            pygame.draw.circle(surf, (150, 120, 90), (sx * T + T // 2, sy * T + T // 2), T // 3)
        return surf

    # ------------------------------------------------------------ interpolation
    @staticmethod
    def snapshot(sim):
        snap = {}
        for w in sim.workers.values():
            if w.state != "off":
                snap[("w", w.id)] = (w.x, w.y)
        for f in sim.forklifts.values():
            snap[("f", f.id)] = (f.x, f.y)
        for tr in sim.trucks.values():
            snap[("t", tr.id)] = (tr.x, tr.y)
        return snap

    @staticmethod
    def _pos(key, x, y, prev, alpha):
        p = prev.get(key) if prev else None
        if p is None or abs(p[0] - x) + abs(p[1] - y) > 8:   # new or teleported: do not slide
            return x, y
        return lerp(p[0], x, alpha), lerp(p[1], y, alpha)

    # ------------------------------------------------------------ frame
    def draw(self, screen, prev=None, alpha=1.0, real_dt=0.0):
        self.time += real_dt
        screen.set_clip(self.view)
        screen.fill((40, 46, 42), self.view)
        self._blit_base(screen)
        self._draw_zone_overlays(screen)
        self._draw_rack_pallets(screen)
        self._draw_spot_pallets(screen)
        self._draw_doors(screen)
        self._draw_trucks(screen, prev, alpha)
        self._draw_workers(screen, prev, alpha)
        self._draw_forklifts(screen, prev, alpha)
        self._draw_night(screen)
        self._draw_labels(screen)
        self._update_fx(real_dt)
        self._draw_fx(screen)
        screen.set_clip(None)

    def _blit_base(self, screen):
        cam = self.cam
        if cam.zoom <= 1.0:                       # scale the whole map once per zoom level, then blit
            key = round(cam.zoom, 4)
            if getattr(self, "_scaled_key", None) != key:
                bw, bh = self.base.get_size()
                self._scaled = pygame.transform.smoothscale(self.base, (max(1, round(bw * key)), max(1, round(bh * key))))
                self._scaled_key = key
            screen.blit(self._scaled, (round(-cam.x * cam.zoom), round(-cam.y * cam.zoom)))
            return
        bw, bh = self.base.get_size()
        vw, vh = VIEW_W / cam.zoom, C.SCREEN_H / cam.zoom
        x0, y0 = max(0, int(cam.x)), max(0, int(cam.y))
        x1, y1 = min(bw, int(math.ceil(cam.x + vw)) + 1), min(bh, int(math.ceil(cam.y + vh)) + 1)
        if x1 <= x0 or y1 <= y0:
            return
        sub = self.base.subsurface((x0, y0, x1 - x0, y1 - y0))
        size = (max(1, round((x1 - x0) * cam.zoom)), max(1, round((y1 - y0) * cam.zoom)))
        screen.blit(pygame.transform.scale(sub, size),
                    (round((x0 - cam.x) * cam.zoom), round((y0 - cam.y) * cam.zoom)))

    # ------------------------------------------------------------ zones
    def _draw_zone_overlays(self, screen):
        flash = 0.5 + 0.5 * math.sin(self.time * 6)
        for z in self.sim.zones.values():
            if not (z.alarm or z.stuck_open):
                continue
            col = ALARM if z.alarm else (245, 180, 40)
            a = int(40 + 70 * flash) if z.alarm else 40
            for x0, y0, x1, y1 in z.rects:
                r = self.cam.rect(x0, y0, x1 - x0 + 1, y1 - y0 + 1).clip(self.view)
                if r.width and r.height:
                    ov = pygame.Surface(r.size, pygame.SRCALPHA)
                    ov.fill((*col, a))
                    screen.blit(ov, r.topleft)

    def _draw_labels(self, screen):
        sim, cam, L = self.sim, self.cam, self.sim.layout
        size = max(15, min(30, int(20 * cam.zoom)))
        for key in ("fresh", "processed", "freezer", "qa"):
            z = sim.zones[key]
            x0, y0, x1, y1 = L.areas[key]
            cx = (x0 + x1 + 1) / 2
            out = z.alarm or z.temp > z.tmax or z.temp < z.tmin
            col = ALARM if out else TEXT_DARK
            if key == "qa":                     # narrow room: name over temperature
                line = 1.3 * size * 0.72 / (T * cam.zoom)
                cy = (y0 + y1 + 1) / 2
                self._label(screen, i18n.value("zone", key), cx, cy - line / 2, size, TEXT_DARK, bold=True)
                self._label(screen, f"{z.temp:+.1f} °C", cx, cy + line / 2, size, col, bold=True)
            else:                               # cold rooms: corridor above the door
                self._label(screen, f"{i18n.value('zone', key)}  {z.temp:+.1f} °C", cx, y0 - 3.3, size,
                            col, bold=True)
        dock = sim.zones["dock"]
        for key, cx in (("area_receiving", C.BUILDING[0] + 9), ("area_shipping", C.BUILDING[2] - 9)):
            self._label(screen, f"{i18n.t(key)}  {dock.temp:+.1f} °C", cx, 6.5, max(11, size - 4), TEXT_DARK, bold=True)
        for key, area in (("area_charging", "charging"), ("area_break", "break"), ("area_office", "office")):
            x0, y0, x1, _ = L.areas[area]
            self._label(screen, i18n.t(key), (x0 + x1 + 1) / 2, y0 + 1.6, max(11, size - 6), TEXT_DARK)
        self._label(screen, f"{i18n.t('outside')} {sim.ambient():+.0f} °C", 20, 3, max(11, size - 4), TEXT_LIGHT)
        self._label(screen, i18n.t("area_yard"), C.PARKING[0][0] + 60, C.PARKING[0][1] - 2.2,
                    max(11, size - 4), TEXT_LIGHT, bold=True)
        if cam.zoom >= 0.7:
            n_in = len(C.RECEIVING_DOOR_Y)
            for d in L.doors:
                n = d.id + 1 if d.side == "in" else d.id - n_in + 1
                dx = d.x - 1.6 if d.side == "in" else d.x + 2.6
                self._label(screen, str(n), dx, d.y + 0.5, max(10, size - 8), TEXT_LIGHT)

    def _label(self, screen, text, tx, ty, size, color, bold=False):
        sx, sy = self.cam.to_screen(tx, ty)
        if not (-200 < sx < VIEW_W + 200 and -50 < sy < C.SCREEN_H + 50):
            return
        img = self.fonts.render(text, size, color, bold)
        screen.blit(img, (sx - img.get_width() / 2, sy - img.get_height() / 2))

    # ------------------------------------------------------------ pallets
    def _pallet_color(self, p):
        if p.mixed or p.sku is None:
            return MIXED_COLOR
        return C.CATEGORY_COLORS[self.sim.skus[p.sku].category]

    def _pallet_rect(self, screen, p, tx, ty, size=0.8):
        r = self.cam.rect(tx + (1 - size) / 2, ty + (1 - size) / 2, size, size)
        if not r.colliderect(self.view):
            return
        pygame.draw.rect(screen, self._pallet_color(p), r)
        if p.mixed and self.cam.zoom >= 0.6:   # stretch-wrapped outbound pallet
            pygame.draw.line(screen, (150, 160, 185), r.topleft, r.bottomright)
        if p.recalled or p.status == "qa_hold":
            pygame.draw.rect(screen, ALARM if p.recalled else (240, 200, 40), r, max(1, int(self.cam.zoom * 1.5)))
        elif self.cam.zoom >= 0.6:
            pygame.draw.rect(screen, (70, 60, 50), r, 1)

    def _draw_rack_pallets(self, screen):
        sim = self.sim
        n = C.RACK_LEVELS
        h = 2.0 / n                                         # a bay is 2 tiles deep
        for slot in sim.slots:
            if slot.pallet is not None:
                p = sim.pallets.get(slot.pallet)
                if p is not None:
                    r = self.cam.rect(slot.x + 0.1, slot.y + (n - 1 - slot.level) * h + 0.05, 0.8, h - 0.1)
                    if r.colliderect(self.view):
                        pygame.draw.rect(screen, self._pallet_color(p), r)
                        if p.recalled or p.status == "qa_hold":
                            pygame.draw.rect(screen, ALARM if p.recalled else (240, 200, 40), r, 1)
            elif slot.reserved_for == -1:                 # bay closed after a rack strike
                r = self.cam.rect(slot.x, slot.y + (n - 1 - slot.level) * h, 1, h)
                if r.colliderect(self.view):
                    pygame.draw.rect(screen, ALARM, r, 1)

    def _draw_spot_pallets(self, screen):
        sim = self.sim
        for sp in sim.spots:
            if sp.pallet is not None:
                p = sim.pallets.get(sp.pallet)
                if p is not None:
                    self._pallet_rect(screen, p, sp.x, sp.y)

    # ------------------------------------------------------------ doors
    def _draw_doors(self, screen):
        for d in self.sim.layout.doors:
            r = self.cam.rect(d.x, d.y - 1, 1, 3)
            if not r.colliderect(self.view):
                continue
            pygame.draw.rect(screen, (34, 34, 40), r)
            closed_h = int(r.height * (1 - d.open))
            if closed_h > 0:
                pygame.draw.rect(screen, (150, 110, 70), (r.x, r.y, r.width, closed_h))
                for k in range(1, 4):           # roll-up slats
                    yy = r.y + closed_h * k // 4
                    pygame.draw.line(screen, (110, 80, 50), (r.x, yy), (r.right - 1, yy))

    # ------------------------------------------------------------ trucks
    def _poly(self, cx, cy, heading, length, width, offset=0.0):
        """Rotated rectangle centred `offset` tiles ahead of (cx, cy) along heading."""
        c, s = math.cos(heading), math.sin(heading)
        cx, cy = cx + c * offset, cy + s * offset
        hl, hw = length / 2, width / 2
        return [self.cam.to_screen(cx + c * lx - s * ly, cy + s * lx + c * ly)
                for lx, ly in ((hl, hw), (hl, -hw), (-hl, -hw), (-hl, hw))]

    def _draw_trucks(self, screen, prev, alpha):
        blink = int(self.time * 2) % 2 == 0
        reach = (C.TRUCK_LEN + 4) * T * self.cam.zoom
        for tr in self.sim.trucks.values():
            if tr.state in ("scheduled", "queued", "gone"):
                continue
            x, y = self._pos(("t", tr.id), tr.x, tr.y, prev, alpha)
            if not self.view.inflate(reach * 2, reach * 2).collidepoint(self.cam.to_screen(x, y)):
                continue
            L, Wd = C.TRUCK_LEN, C.TRUCK_W
            trailer = self._poly(x, y, tr.heading, L - 3.2, Wd, offset=-1.6)
            pygame.draw.polygon(screen, (236, 238, 240), trailer)
            pygame.draw.polygon(screen, (90, 90, 100), trailer, 1)
            cab_col = (40, 90, 170) if tr.kind == "in" else (30, 140, 80)
            pygame.draw.polygon(screen, cab_col, self._poly(x, y, tr.heading, 2.8, Wd - 0.3, offset=L / 2 - 1.4))
            # reefer unit at the front of the trailer: blinks green, red when it failed
            on = ALARM if tr.reefer_fail else (60, 220, 120)
            pygame.draw.polygon(screen, on if blink else (70, 80, 80),
                                self._poly(x, y, tr.heading, 0.8, Wd - 0.8, offset=L / 2 - 3.6))

    # ------------------------------------------------------------ people and machines
    def _draw_workers(self, screen, prev, alpha):
        cam, sim = self.cam, self.sim
        rad = max(3, int(0.42 * T * cam.zoom))
        for w in sim.workers.values():
            if w.state == "off" or w.forklift is not None:
                continue
            x, y = self._pos(("w", w.id), w.x, w.y, prev, alpha)
            sx, sy = cam.to_screen(x, y)
            if not self.view.inflate(40, 40).collidepoint(sx, sy):
                continue
            if w.role == "taxi":
                pygame.draw.polygon(screen, (90, 90, 90), self._poly(x, y, w.heading, 2.2, 0.8, offset=1.2))
                for i, pid in enumerate(w.cargo[:C.TAXI_PALLETS]):
                    if pid in sim.pallets:
                        pygame.draw.polygon(screen, self._pallet_color(sim.pallets[pid]),
                                            self._poly(x, y, w.heading, 0.9, 0.8, offset=0.7 + i))
            elif w.jack_load or w.carrying is not None or (w.role == "picker" and w.task == "job"):
                if w.carrying in sim.pallets:
                    col = self._pallet_color(sim.pallets[w.carrying])
                else:
                    col = (120, 120, 120)
                pygame.draw.polygon(screen, col, self._poly(x, y, w.heading, 1.0, 0.8, offset=0.8))
                cases = sum(item[2] for item in w.jack_load)
                if cases and cam.zoom >= 0.8:      # the jack fills case by case
                    fill = min(1.0, cases / C.PALLET_MAX_CASES)
                    pygame.draw.polygon(screen, (190, 120, 90),
                                        self._poly(x, y, w.heading, fill, 0.5, offset=0.3 + fill / 2))
            pygame.draw.circle(screen, ROLE_COLORS[w.role], (sx, sy), rad)
            if cam.zoom >= 0.6:
                pygame.draw.circle(screen, (20, 20, 20), (sx, sy), rad, 1)

    def _draw_forklifts(self, screen, prev, alpha):
        cam, sim = self.cam, self.sim
        for f in sim.forklifts.values():
            x, y = self._pos(("f", f.id), f.x, f.y, prev, alpha)
            sx, sy = cam.to_screen(x, y)
            if not self.view.inflate(60, 60).collidepoint(sx, sy):
                continue
            c, s = math.cos(f.heading), math.sin(f.heading)
            for side in (-0.22, 0.22):          # forks
                a = cam.to_screen(x + c * 0.4 - s * side, y + s * 0.4 + c * side)
                b = cam.to_screen(x + c * 1.3 - s * side, y + s * 1.3 + c * side)
                pygame.draw.line(screen, (60, 60, 60), a, b, max(1, int(cam.zoom * 2)))
            if f.carrying in sim.pallets:
                grow = 1 + 0.15 * f.fork_h      # raised pallets look a bit bigger
                pygame.draw.polygon(screen, self._pallet_color(sim.pallets[f.carrying]),
                                    self._poly(x, y, f.heading, 0.85 * grow, 0.85 * grow, offset=0.85))
            body_col = (240, 190, 40) if f.kind == "forklift" else (240, 130, 40)
            if f.state == "broken":
                body_col = (150, 70, 60)
            body = self._poly(x, y, f.heading, 1.1, 0.9, offset=-0.15)
            pygame.draw.polygon(screen, body_col, body)
            pygame.draw.polygon(screen, (40, 40, 40), body, 1)
            if f.operator is not None:
                pygame.draw.circle(screen, ROLE_COLORS["forklift"], cam.to_screen(x - c * 0.2, y - s * 0.2),
                                   max(2, int(0.25 * T * cam.zoom)))
            if cam.zoom >= 0.5:                 # battery bar
                bw, bh = max(8, int(1.2 * T * cam.zoom)), max(2, int(0.18 * T * cam.zoom))
                bx, by = sx - bw / 2, sy - 0.95 * T * cam.zoom
                pygame.draw.rect(screen, (30, 30, 30), (bx, by, bw, bh))
                col = (60, 200, 90) if f.battery > C.BATTERY_LOW else ALARM
                pygame.draw.rect(screen, col, (bx, by, bw * f.battery / 100, bh))
                if f.state == "charging" and int(self.time * 2) % 2:
                    pygame.draw.rect(screen, (255, 255, 255), (bx, by, bw, bh), 1)
            if f.state == "broken":
                r = int(0.5 * T * cam.zoom)
                pygame.draw.line(screen, ALARM, (sx - r, sy - r), (sx + r, sy + r), 2)
                pygame.draw.line(screen, ALARM, (sx - r, sy + r), (sx + r, sy - r), 2)

    # ------------------------------------------------------------ day / night
    def _draw_night(self, screen):
        h = self.sim.hour()
        dark = max(0.0, (math.cos((h - 0.5) / 24 * 2 * math.pi) - 0.25) / 0.75)   # 1 at midnight, 0 by day
        if dark <= 0.01:
            return
        ov = pygame.Surface(self.view.size, pygame.SRCALPHA)
        ov.fill((10, 20, 50, int(110 * dark)))
        bx0, by0, bx1, by1 = C.BUILDING             # the building stays lit inside
        ov.fill((0, 0, 0, 0), self.cam.rect(bx0, by0, bx1 - bx0 + 1, by1 - by0 + 1))
        screen.blit(ov, (0, 0))

    # ------------------------------------------------------------ floating text and fog
    def _update_fx(self, real_dt):
        sim = self.sim
        for fx in sim.fx:
            if fx["kind"] == "text":
                self.floaters.append([fx["x"], fx["y"], fx["key"], fx["kw"], fx["color"], 0.0])
            elif fx["kind"] == "fog":
                self.fog.append([fx["x"], fx["y"], 0.0])
        sim.fx.clear()
        for f in self.floaters:
            f[5] += real_dt
        for f in self.fog:
            f[2] += real_dt
        self.floaters = [f for f in self.floaters if f[5] < 3.0][-40:]
        self.fog = [f for f in self.fog if f[2] < 2.5][-60:]

    def _draw_fx(self, screen):
        cam = self.cam
        for x, y, age in self.fog:
            r = max(2, int((0.6 + age * 0.9) * T * cam.zoom))
            puff = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(puff, (235, 245, 255, int(100 * (1 - age / 2.5))), (r, r), r)
            sx, sy = cam.to_screen(x, y)
            screen.blit(puff, (sx - r, sy - r))
        size = max(14, min(28, int(18 * cam.zoom)))
        for x, y, key, kw, col, age in self.floaters:
            sx, sy = cam.to_screen(x, y)
            sy -= age * 25
            text = i18n.t(key, **kw)
            alpha = int(255 * min(1.0, 3.0 - age))
            for dx, colour in ((1, (0, 0, 0)), (0, FX_COLORS.get(col, TEXT_LIGHT))):
                img = self.fonts.render(text, size, colour, bold=True)
                img.set_alpha(alpha // 2 if dx else alpha)
                screen.blit(img, (sx - img.get_width() / 2 + dx, sy + dx))
