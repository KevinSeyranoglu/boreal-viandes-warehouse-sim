"""Game controls on a dummy display (no window): keyboard zoom."""
from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
pg = pytest.importorskip("pygame")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config as C  # noqa: E402
import main  # noqa: E402
from simulation import Simulation  # noqa: E402


class Held(dict):
    def __getitem__(self, key):
        return self.get(key, False)


@pytest.fixture(scope="module")
def game():
    pg.init()
    g = main.Game(Simulation(seed=1), pg.display.set_mode((C.SCREEN_W, C.SCREEN_H)))
    g.paused = True
    yield g
    pg.quit()


def hold(game, monkeypatch, *keys, seconds=0.5):
    cam, view = game.renderer.cam, game.renderer.view
    cam.home()
    before = cam.zoom, cam.screen_to_world_px(view.centerx, view.centery)
    monkeypatch.setattr(pg.key, "get_pressed", lambda: Held({k: True for k in keys}))
    game.update(seconds)
    return before, (cam.zoom, cam.screen_to_world_px(view.centerx, view.centery))


@pytest.mark.parametrize("key, sign", [("K_PLUS", 1), ("K_EQUALS", 1), ("K_KP_PLUS", 1), ("K_PAGEUP", 1),
                                       ("K_MINUS", -1), ("K_KP_MINUS", -1), ("K_PAGEDOWN", -1)])
def test_keys_zoom_on_the_centre_of_the_view(game, monkeypatch, key, sign):
    (z0, c0), (z1, c1) = hold(game, monkeypatch, getattr(pg, key))
    assert (z1 - z0) * sign > 0
    assert c1 == pytest.approx(c0)


def test_both_keys_cancel_and_zoom_stays_in_limits(game, monkeypatch):
    (z0, _), (z1, _) = hold(game, monkeypatch, pg.K_PLUS, pg.K_MINUS)
    assert z1 == z0
    _, (z1, _) = hold(game, monkeypatch, pg.K_PLUS, seconds=10)
    assert z1 == C.ZOOM_MAX
    _, (z1, _) = hold(game, monkeypatch, pg.K_MINUS, seconds=10)
    assert z1 == C.ZOOM_MIN
