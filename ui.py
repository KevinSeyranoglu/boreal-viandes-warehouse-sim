"""Right-hand sidebar: clock, speed, KPIs, zone temperatures and the event log.

Reads sim.kpis(), sim.zones and sim.logbook; never changes the simulation.
"""
from __future__ import annotations

import pygame

import config as C
import i18n
from renderer import ALARM, VIEW_W
from simulation import DAY

BG = (28, 31, 38)
PANEL = (38, 42, 52)
TEXT = (226, 229, 235)
MUTED = (150, 156, 170)
GOOD = (80, 200, 120)
WARN = (245, 180, 40)
LVL_COLORS = {"info": MUTED, "warn": WARN, "bad": ALARM, "event": (120, 180, 255)}
PAD = 14


def pct(v):
    return "–" if v is None else f"{v * 100:.1f} %"


def money(v):
    v = round(v)                    # avoid "-0 $"
    s = f"{abs(v):,}".replace(",", " ")
    return ("-" if v < 0 else "") + (s + " $" if i18n.lang() == "fr" else "$" + s)


class Sidebar:
    def __init__(self, fonts):
        self.fonts = fonts
        self.rect = pygame.Rect(VIEW_W, 0, C.SIDEBAR_W, C.SCREEN_H)

    def text(self, screen, s, x, y, size=20, color=TEXT, bold=False, right=False):
        img = self.fonts.render(s, size, color, bold)
        screen.blit(img, (x - img.get_width(), y) if right else (x, y))
        return img.get_height()

    def draw(self, screen, sim, speed, paused):
        screen.fill(BG, self.rect)
        pygame.draw.line(screen, (70, 76, 90), self.rect.topleft, self.rect.bottomleft, 2)
        x0, x1 = self.rect.x + PAD, self.rect.right - PAD
        y = PAD
        k = sim.kpis()

        # ---- header: company, date, clock, speed
        y += self.text(screen, i18n.t("title"), x0, y, 20, MUTED)
        d = sim.date()
        self.text(screen, f"{d:%Y-%m-%d}  {d:%H:%M}", x0, y + 4, 34, TEXT, bold=True)
        state = i18n.t("paused") if paused else i18n.t("speed", x=speed)
        self.text(screen, state, x1, y + 10, 22, WARN if paused else GOOD, bold=True, right=True)
        y += 36
        shift = i18n.value("shift", sim.current_shift())
        on = sum(1 for w in sim.workers.values() if w.state != "off")
        y += self.text(screen, f"{i18n.t('day_n', n=int(sim.t // DAY) + 1)} · {shift} · "
                               f"{i18n.t('staff_on')}: {on}", x0, y, 19, MUTED) + 8

        # ---- KPIs
        comp = k["compliance"]
        rows = [
            ("money", money(k["money"]), None),
            ("profit_today", money(k["profit_today"]), GOOD if round(k["profit_today"]) >= 0 else ALARM),
            ("on_time", pct(k["on_time"]), None),
            ("fill_rate", pct(k["fill_rate"]), None),
            ("accuracy", pct(k["accuracy"]), None),
            ("compliance", pct(comp), None if comp is None else (GOOD if comp >= C.COMPLIANCE_TARGET else ALARM)),
            ("cph", "–" if k["cph_today"] is None else f"{k['cph_today']:.0f}", None),
            ("shipped_today", str(k["cases_shipped"]), None),
            ("open_orders", str(k["open_orders"]), None),
            ("spoilage", money(k["spoilage"]), ALARM if k["spoilage"] > 0 else None),
            ("energy", money(k["energy"]), None),
            ("alarms", str(k["alarms"]), ALARM if k["active_alarms"] else None),
        ]
        pygame.draw.rect(screen, PANEL, (x0 - 6, y, x1 - x0 + 12, len(rows) * 23 + 10), border_radius=6)
        y += 6
        for key, val, col in rows:
            self.text(screen, i18n.t(key), x0, y, 20, MUTED)
            self.text(screen, val, x1, y, 20, col or TEXT, bold=True, right=True)
            y += 23
        y += 14

        # ---- zones: temperature + occupancy bar
        y += self.text(screen, i18n.t("zone_fill"), x0, y, 20, MUTED, bold=True) + 4
        for key in ("fresh", "processed", "freezer"):
            z = sim.zones[key]
            out = z.alarm or z.temp > z.tmax or z.temp < z.tmin
            self.text(screen, i18n.value("zone", key), x0, y, 19, TEXT)
            self.text(screen, f"{z.temp:+.1f} °C", x0 + 150, y, 19, ALARM if out else GOOD, bold=True)
            fill = k["fill"].get(key, 0.0)
            bar = pygame.Rect(x0 + 230, y + 3, x1 - x0 - 230, 12)
            pygame.draw.rect(screen, PANEL, bar, border_radius=3)
            pygame.draw.rect(screen, WARN if fill > 0.9 else (90, 150, 230),
                             (bar.x, bar.y, int(bar.width * fill), bar.height), border_radius=3)
            y += 22
        y += 12

        # ---- event log, newest first
        y += self.text(screen, i18n.t("event_log"), x0, y, 20, MUTED, bold=True) + 4
        for entry in reversed(sim.logbook):
            if y + 19 > self.rect.bottom - 30:
                break
            t = entry["t"] % DAY
            self.text(screen, f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}", x0, y, 17, MUTED)
            self._clipped(screen, i18n.t(entry["key"], **entry["kw"]), x0 + 44, y, x1 - x0 - 44, 17,
                          LVL_COLORS.get(entry["lvl"], MUTED))
            y += 19

        # ---- key help
        self._clipped(screen, i18n.t("help"), x0, self.rect.bottom - 22, x1 - x0, 15, MUTED)

    def _clipped(self, screen, s, x, y, width, size, color):
        font = self.fonts.get(size)
        if font.size(s)[0] > width:
            while s and font.size(s + "…")[0] > width:
                s = s[:-1]
            s += "…"
        screen.blit(font.render(s, True, color), (x, y))


def flash_message(screen, fonts, text, age):
    """Short centred notice (saved / loaded) that fades out over 2 s."""
    if age > 2.0:
        return
    img = fonts.render(text, 30, (255, 255, 255), bold=True)
    bg = pygame.Surface((img.get_width() + 30, img.get_height() + 16), pygame.SRCALPHA)
    bg.fill((0, 0, 0, 160))
    a = int(255 * min(1.0, 2.0 - age))
    bg.set_alpha(a)
    img.set_alpha(a)
    x = VIEW_W // 2 - bg.get_width() // 2
    screen.blit(bg, (x, 20))
    screen.blit(img, (x + 15, 28))
