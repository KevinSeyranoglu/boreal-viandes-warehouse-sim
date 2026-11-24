"""Boréal Viandes – entry point.

    python main.py                                   animated game (French; L = English)
    python main.py --headless --days 180 --seed 42   generate data in data/<scenario>_seed<seed>/
    python main.py --scenario lean_staff             any scenario from config.SCENARIOS
    python main.py --record videos/day.mp4 --hours 24 --speed 20 --camera site
                                                     render offscreen to an MP4 (needs ffmpeg)

pygame is imported only for the animated game, so headless runs work without it.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

import config as C
import i18n

# --record camera presets: tile the view centres on, zoom (None = whole site)
_BX0, _BY0, _BX1, _BY1 = C.BUILDING
CAMERAS = {
    "site": None,
    "receiving": (_BX0 - 2, (C.ROOM_Y0 + C.ROOM_Y1) / 2, 0.8),         # receiving doors, staging, trailers
    "shipping": (_BX1 + 2, (C.ROOM_Y0 + C.ROOM_Y1) / 2, 0.8),          # shipping doors and outbound lanes
    "freezer": (C.ROOM_X["freezer"] + 15, (C.ROOM_Y0 + C.ROOM_Y1) / 2, 0.9),
    "picking": ((_BX0 + _BX1) / 2, C.ROOM_Y0 + 20, 0.65),
    "yard": (_BX0 + 10, (C.RECEIVING_DOOR_Y[0] + C.PARKING[-1][1]) / 2, 0.5),   # receiving doors + trailer yard
    "taxi": (C.ROOM_X["fresh"] - 6, C.ROOM_Y0 - 2, 1.4),                 # dock -> drop points
}


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=C.COMPANY_NAME)
    ap.add_argument("--headless", action="store_true", help="no window: run fast and write CSV data")
    ap.add_argument("--days", type=int, default=30, help="days to simulate in headless mode")
    ap.add_argument("--seed", type=int, default=C.RANDOM_SEED)
    ap.add_argument("--scenario", default="baseline", help=f"one of: {', '.join(C.SCENARIOS)}")
    ap.add_argument("--lang", default="fr", choices=i18n.LANGS)
    ap.add_argument("--out", default=None, help="headless output folder (default data/<scenario>_seed<seed>)")
    rec = ap.add_argument_group("video recording")
    rec.add_argument("--record", metavar="FILE.mp4", help="render offscreen to a video instead of opening a window")
    rec.add_argument("--hours", type=float, default=24.0, help="sim hours to record")
    rec.add_argument("--speed", type=int, default=20, help="sim speed while recording (like keys 1-5)")
    rec.add_argument("--camera", default="site", choices=list(CAMERAS))
    rec.add_argument("--warmup", type=float, default=0.0, help="sim hours to skip before recording starts")
    rec.add_argument("--fps", type=int, default=30)
    return ap.parse_args(argv)


# ====================================================================== headless
def run_headless(args):
    from datalog import CsvLog
    from simulation import DAY, Simulation

    out = args.out or os.path.join(C.DATA_DIR, f"{args.scenario}_seed{args.seed}")
    log = CsvLog(out)
    sim = Simulation(seed=args.seed, datalog=log)
    end = sim.t + args.days * DAY
    t0 = time.time()
    last_day = -1
    while sim.t < end:
        sim.step(C.HEADLESS_TICK_SECONDS)
        sim.fx.clear()
        sim.summary_ready = None
        day = int(sim.t // DAY)
        if day != last_day:
            last_day = day
            k = sim.kpis()
            on_time = "–" if k["on_time"] is None else f"{k['on_time'] * 100:.1f}%"
            print(f"\r{sim.day_str(day)}  day {day}/{args.days}  cash {sim.money:,.0f} $  on-time {on_time}",
                  end="", flush=True)
    log.close(sim)
    print(f"\nDone in {time.time() - t0:.1f} s -> {out}")


# ====================================================================== game
class Game:
    def __init__(self, sim, screen):
        import pygame

        from renderer import Fonts, Renderer
        from ui import Sidebar

        self.pg = pygame
        self.sim = sim
        self.screen = screen
        self.fonts = Fonts()
        self.renderer = Renderer(sim, self.fonts)
        self.sidebar = Sidebar(self.fonts)
        self.speed_i = 0
        self.paused = False
        self.acc = 0.0              # sim-seconds waiting to be stepped
        self.prev = None            # positions before the last tick, for interpolation
        self.drag = None
        self.notice = None          # [text key, age]
        self.running = True

    @property
    def speed(self):
        return C.SPEEDS[self.speed_i]

    # ------------------------------------------------------------ input
    def handle(self, ev):
        pg = self.pg
        cam = self.renderer.cam
        if ev.type == pg.QUIT:
            self.running = False
        elif ev.type == pg.KEYDOWN:
            if ev.key == pg.K_ESCAPE:
                self.running = False
            elif ev.key == pg.K_SPACE:
                self.paused = not self.paused
            elif pg.K_1 <= ev.key <= pg.K_5:
                self.speed_i = ev.key - pg.K_1
            elif ev.key == pg.K_l:
                i18n.toggle()
                pg.display.set_caption(i18n.t("title"))
            elif ev.key == pg.K_HOME:
                cam.home()
            elif ev.key == pg.K_F5:
                self.sim.save(C.SAVE_FILE)
                self.notice = ["saved", 0.0]
            elif ev.key == pg.K_F9:
                self.load()
        elif ev.type == pg.MOUSEBUTTONDOWN and ev.button in (1, 2, 3) and ev.pos[0] < self.renderer.view.right:
            self.drag = ev.pos
        elif ev.type == pg.MOUSEBUTTONUP and ev.button in (1, 2, 3):
            self.drag = None
        elif ev.type == pg.MOUSEMOTION and self.drag is not None:
            cam.pan(ev.pos[0] - self.drag[0], ev.pos[1] - self.drag[1])
            self.drag = ev.pos
        elif ev.type == pg.MOUSEWHEEL:
            mx, my = pg.mouse.get_pos()
            if mx < self.renderer.view.right:
                cam.zoom_at(1.15 ** ev.y, mx, my)

    def load(self):
        from simulation import Simulation

        if not os.path.exists(C.SAVE_FILE):
            self.notice = ["no_save", 0.0]
            return
        self.sim = Simulation.load(C.SAVE_FILE)
        self.renderer.set_sim(self.sim)
        self.prev = None
        self.acc = 0.0
        self.notice = ["loaded", 0.0]

    # ------------------------------------------------------------ update / draw
    def update(self, real_dt):
        pg = self.pg
        keys = pg.key.get_pressed()
        step = C.CAMERA_PAN_SPEED * real_dt
        dx = (keys[pg.K_LEFT] - keys[pg.K_RIGHT]) * step
        dy = (keys[pg.K_UP] - keys[pg.K_DOWN]) * step
        if dx or dy:
            self.renderer.cam.pan(dx, dy)
        if self.notice:
            self.notice[1] += real_dt
        if self.paused:
            return
        self.acc += real_dt * self.speed * 3600.0 / C.REAL_SECONDS_PER_SIM_HOUR
        n = int(self.acc // C.TICK_SECONDS)
        if n > C.MAX_TICKS_PER_FRAME:       # too slow to keep up: drop the backlog
            n = C.MAX_TICKS_PER_FRAME
            self.acc = n * C.TICK_SECONDS
        for i in range(n):
            if i == n - 1:
                self.prev = self.renderer.snapshot(self.sim)
            self.sim.step(C.TICK_SECONDS)
            self.acc -= C.TICK_SECONDS
        self.sim.summary_ready = None       # end-of-day screen comes in Phase 4

    def draw(self, real_dt):
        from ui import flash_message

        alpha = 1.0 if self.paused else min(1.0, self.acc / C.TICK_SECONDS)
        self.renderer.draw(self.screen, self.prev, alpha, real_dt)
        self.sidebar.draw(self.screen, self.sim, self.speed, self.paused)
        if self.notice:
            flash_message(self.screen, self.fonts, i18n.t(self.notice[0]), self.notice[1])


def run_game(args):
    import pygame

    from simulation import Simulation

    pygame.init()
    screen = pygame.display.set_mode((C.SCREEN_W, C.SCREEN_H))
    pygame.display.set_caption(i18n.t("title"))
    clock = pygame.time.Clock()
    game = Game(Simulation(seed=args.seed), screen)
    while game.running:
        real_dt = min(clock.tick(C.FPS) / 1000.0, 0.1)
        for ev in pygame.event.get():
            game.handle(ev)
        game.update(real_dt)
        game.draw(real_dt)
        pygame.display.flip()
    pygame.quit()


def run_record(args):
    """Drive the real Game offscreen at a fixed frame step and pipe RGB frames into ffmpeg."""
    if shutil.which("ffmpeg") is None:
        raise SystemExit("--record needs ffmpeg on the PATH (sudo apt install ffmpeg)")
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame

    from simulation import Simulation

    pygame.init()
    screen = pygame.display.set_mode((C.SCREEN_W, C.SCREEN_H))
    sim = Simulation(seed=args.seed)
    for _ in range(int(args.warmup * 3600 / C.TICK_SECONDS)):
        sim.step(C.TICK_SECONDS)
    sim.fx.clear()
    game = Game(sim, screen)
    game.speed_i = min(range(len(C.SPEEDS)), key=lambda i: abs(C.SPEEDS[i] - args.speed))
    preset = CAMERAS[args.camera]
    if preset:
        game.renderer.cam.focus(*preset)

    out = args.record
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{C.SCREEN_W}x{C.SCREEN_H}", "-r", str(args.fps), "-i", "-",
           "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", out]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    dt = 1.0 / args.fps
    sim_per_frame = dt * game.speed * 3600.0 / C.REAL_SECONDS_PER_SIM_HOUR
    frames = max(1, round(args.hours * 3600 / sim_per_frame))
    t0 = time.time()
    try:
        for i in range(frames):
            game.update(dt)
            game.draw(dt)
            enc.stdin.write(pygame.image.tobytes(screen, "RGB"))
            if i % args.fps == 0:
                print(f"\r{game.sim.date():%Y-%m-%d %H:%M}  frame {i}/{frames}", end="", flush=True)
    finally:
        enc.stdin.close()
        enc.wait()
        pygame.quit()
    if enc.returncode:
        raise SystemExit(f"ffmpeg failed (exit {enc.returncode})")
    print(f"\n{frames / args.fps:.0f} s video ({args.hours:g} sim h at {game.speed}x) "
          f"in {time.time() - t0:.0f} s -> {out}")


def main(argv=None):
    args = parse_args(argv)
    i18n.set_lang(args.lang)
    C.apply_scenario(args.scenario)
    if args.headless:
        run_headless(args)
    elif args.record:
        run_record(args)
    else:
        run_game(args)


if __name__ == "__main__":
    sys.exit(main())
