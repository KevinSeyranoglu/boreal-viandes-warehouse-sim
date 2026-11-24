"""Grid navigation for forklifts and workers.

Two strategies on the same 4-connected floor grid:

* A* (Manhattan heuristic) for one-off destinations.
* A cached breadth-first "flow field" for destinations used again and again
  (rack aisles, staging spots, chargers). Once built, any agent anywhere can
  walk downhill to that goal in O(path length), which keeps the simulation
  fast enough to generate months of data in a few minutes.
"""
from __future__ import annotations

import heapq
from array import array
from collections import deque

FIELD_AFTER_REQUESTS = 2   # build a flow field the 2nd time a goal is requested
_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))


class NavGrid:
    def __init__(self, w: int, h: int, walkable: bytearray):
        self.w, self.h = w, h
        self.walk = walkable
        self._fields: dict[int, array] = {}
        self._requests: dict[int, int] = {}

    # ------------------------------------------------------------ helpers
    def is_walkable(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h and self.walk[y * self.w + x] == 1

    def nearest_walkable(self, x: int, y: int) -> tuple[int, int]:
        if self.is_walkable(x, y):
            return x, y
        seen = {(x, y)}
        q = deque([(x, y)])
        while q:
            cx, cy = q.popleft()
            for dx, dy in _DIRS:
                nx, ny = cx + dx, cy + dy
                if (nx, ny) in seen or not (0 <= nx < self.w and 0 <= ny < self.h):
                    continue
                if self.is_walkable(nx, ny):
                    return nx, ny
                seen.add((nx, ny))
                q.append((nx, ny))
        return x, y

    # ------------------------------------------------------------ public
    def find_path(self, start: tuple[float, float], goal: tuple[int, int]) -> list[list[float]]:
        """Corner waypoints (tile centres) from start to goal, start excluded."""
        sx, sy = self.nearest_walkable(int(start[0]), int(start[1]))
        gx, gy = self.nearest_walkable(goal[0], goal[1])
        if (sx, sy) == (gx, gy):
            return [[gx + 0.5, gy + 0.5]]
        gi = gy * self.w + gx
        field = self._fields.get(gi)
        if field is None:
            n = self._requests.get(gi, 0) + 1
            self._requests[gi] = n
            if n >= FIELD_AFTER_REQUESTS:
                field = self._build_field(gx, gy)
                self._fields[gi] = field
        tiles = self._descend(field, sx, sy) if field is not None else None
        if tiles is None:
            tiles = self.astar((sx, sy), (gx, gy))
        if not tiles:
            return [[gx + 0.5, gy + 0.5]]
        return self._corners(tiles)

    def astar(self, start: tuple[int, int], goal: tuple[int, int]) -> list[tuple[int, int]]:
        w = self.w
        walk = self.walk
        gx, gy = goal
        si = start[1] * w + start[0]
        gi = gy * w + gx
        came = {si: -1}
        cost = {si: 0}
        heap = [(abs(start[0] - gx) + abs(start[1] - gy), 0, si)]
        while heap:
            _, g, cur = heapq.heappop(heap)
            if cur == gi:
                break
            if g > cost[cur]:
                continue
            cx, cy = cur % w, cur // w
            for dx, dy in _DIRS:
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < w and 0 <= ny < self.h):
                    continue
                ni = ny * w + nx
                if walk[ni] != 1:
                    continue
                ng = g + 1
                if ng < cost.get(ni, 1 << 30):
                    cost[ni] = ng
                    came[ni] = cur
                    heapq.heappush(heap, (ng + abs(nx - gx) + abs(ny - gy), ng, ni))
        if gi not in came:
            return []
        out = []
        cur = gi
        while cur != -1:
            out.append((cur % w, cur // w))
            cur = came[cur]
        out.reverse()
        return out

    # ------------------------------------------------------------ internals
    def _build_field(self, gx: int, gy: int) -> array:
        w, h, walk = self.w, self.h, self.walk
        field = array("h", [-1]) * (w * h)
        gi = gy * w + gx
        field[gi] = 0
        q = deque([gi])
        while q:
            cur = q.popleft()
            d = field[cur] + 1
            cx = cur % w
            if cx + 1 < w and walk[cur + 1] == 1 and field[cur + 1] < 0:
                field[cur + 1] = d
                q.append(cur + 1)
            if cx > 0 and walk[cur - 1] == 1 and field[cur - 1] < 0:
                field[cur - 1] = d
                q.append(cur - 1)
            if cur + w < w * h and walk[cur + w] == 1 and field[cur + w] < 0:
                field[cur + w] = d
                q.append(cur + w)
            if cur - w >= 0 and walk[cur - w] == 1 and field[cur - w] < 0:
                field[cur - w] = d
                q.append(cur - w)
        return field

    def _descend(self, field: array, sx: int, sy: int):
        w = self.w
        cur = sy * w + sx
        if field[cur] < 0:
            return None
        out = [(sx, sy)]
        last = None
        while field[cur] > 0:
            want = field[cur] - 1
            cx = cur % w
            options = []
            if cx + 1 < w:
                options.append((1, cur + 1))
            if cx > 0:
                options.append((-1, cur - 1))
            options.append((w, cur + w))
            options.append((-w, cur - w))
            nxt = None
            for step, ni in options:
                if 0 <= ni < len(field) and field[ni] == want:
                    if step == last:       # prefer going straight: fewer corners
                        nxt = (step, ni)
                        break
                    if nxt is None:
                        nxt = (step, ni)
            if nxt is None:
                return None
            last, cur = nxt
            out.append((cur % w, cur // w))
        return out

    @staticmethod
    def _corners(tiles: list[tuple[int, int]]) -> list[list[float]]:
        pts = []
        for i in range(1, len(tiles)):
            if i == len(tiles) - 1:
                pts.append([tiles[i][0] + 0.5, tiles[i][1] + 0.5])
                break
            d0 = (tiles[i][0] - tiles[i - 1][0], tiles[i][1] - tiles[i - 1][1])
            d1 = (tiles[i + 1][0] - tiles[i][0], tiles[i + 1][1] - tiles[i][1])
            if d0 != d1:
                pts.append([tiles[i][0] + 0.5, tiles[i][1] + 0.5])
        return pts
