# -*- coding: utf-8 -*-
from dataclasses import dataclass
import random
from typing import Callable, List, Optional, Tuple

W, H = 10, 20

# 7-bag 定義（形狀代碼與顏色索引，顏色交由 client 決定也OK）
SHAPES = {
    "I": [
        [(0, 1), (1, 1), (2, 1), (3, 1)],
        [(2, 0), (2, 1), (2, 2), (2, 3)],
        [(0, 2), (1, 2), (2, 2), (3, 2)],
        [(1, 0), (1, 1), (1, 2), (1, 3)],
    ],
    "O": [
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
    ],
    "T": [
        [(1, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (2, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (1, 2)],
        [(1, 0), (0, 1), (1, 1), (1, 2)],
    ],
    "S": [
        [(1, 0), (2, 0), (0, 1), (1, 1)],
        [(1, 0), (1, 1), (2, 1), (2, 2)],
        [(1, 1), (2, 1), (0, 2), (1, 2)],
        [(0, 0), (0, 1), (1, 1), (1, 2)],
    ],
    "Z": [
        [(0, 0), (1, 0), (1, 1), (2, 1)],
        [(2, 0), (1, 1), (2, 1), (1, 2)],
        [(0, 1), (1, 1), (1, 2), (2, 2)],
        [(1, 0), (0, 1), (1, 1), (0, 2)],
    ],
    "J": [
        [(0, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (2, 2)],
        [(1, 0), (1, 1), (0, 2), (1, 2)],
    ],
    "L": [
        [(2, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (1, 2), (2, 2)],
        [(0, 1), (1, 1), (2, 1), (0, 2)],
        [(0, 0), (1, 0), (1, 1), (1, 2)],
    ],
}
ORDER = ["I", "O", "T", "S", "Z", "J", "L"]


@dataclass
class GravityPlan:
    mode: str
    drop_ms: int


@dataclass
class EngineSnapshot:
    board: List[List[int]]
    active: dict
    next3: List[str]
    hold: Optional[str]


def make_bag_rng(seed: int) -> Callable[[], Callable[[], str]]:
    """回傳『生成器工廠』：每個玩家調用一次，得到自己的 bag 取塊函數。"""
    def factory():
        rng = random.Random(seed)
        bag: List[str] = []

        def next_piece():
            nonlocal bag
            if not bag:
                bag = ORDER[:]
                rng.shuffle(bag)  # Fisher-Yates via random.shuffle
            p = bag.pop()
            return p
        return next_piece
    return factory


class TetrisEngine:
    def __init__(self, bag_rng: Callable[[], str]):
        self.board = [[0]*W for _ in range(H)]  # 0=empty, >0=color id
        self.bag_next = bag_rng
        self.queue: List[str] = [self.bag_next() for _ in range(5)]
        self.hold_slot: Optional[str] = None
        self.hold_used = False

        self.cur_shape: Optional[str] = None
        self.rot = 0
        self.x = 3
        self.y = 0
        self.top_out = False

    # ---------- utilities ----------
    def spawn_if_needed(self):
        if self.cur_shape is None:
            self.cur_shape = self.queue.pop(0)
            self.queue.append(self.bag_next())
            self.rot, self.x, self.y = 0, 3, 0
            if self.collide(self.x, self.y, self.cur_shape, self.rot):
                self.top_out = True

    def shape_cells(self, shape: str, rot: int):
        return SHAPES[shape][rot % 4]

    def collide(self, x, y, shape, rot) -> bool:
        for (dx, dy) in self.shape_cells(shape, rot):
            xx, yy = x + dx, y + dy
            if xx < 0 or xx >= W or yy < 0 or yy >= H:
                return True
            if self.board[yy][xx]:
                return True
        return False

    def lock_piece(self):
        # 將 active 方塊寫入 board
        color = 1 + ORDER.index(self.cur_shape)  # 1..7
        for (dx, dy) in self.shape_cells(self.cur_shape, self.rot):
            xx, yy = self.x + dx, self.y + dy
            if 0 <= xx < W and 0 <= yy < H:
                self.board[yy][xx] = color
        # 清行
        lines = 0
        new_rows = [row for row in self.board if any(v == 0 for v in row)]
        lines = H - len(new_rows)
        if lines:
            self.board = [[0]*W for _ in range(lines)] + new_rows
        # 下一顆
        self.cur_shape = None
        self.hold_used = False
        self.spawn_if_needed()
        # 計分：單純示例（1/3/5/8）
        score_delta = (0, 100, 300, 500, 800)[lines]
        return lines, score_delta

    # ---------- actions ----------
    def move(self, dx: int):
        if self.top_out or self.cur_shape is None:
            return
        nx = self.x + dx
        if not self.collide(nx, self.y, self.cur_shape, self.rot):
            self.x = nx

    def rotate(self, cw: bool = True):
        if self.top_out or self.cur_shape is None:
            return
        nr = (self.rot + (1 if cw else -1)) % 4
        # 簡單 SRS 躍移（只做一格微調）
        for sx in (0, -1, +1, -2, +2):
            if not self.collide(self.x + sx, self.y, self.cur_shape, nr):
                self.rot = nr
                self.x += sx
                return

    def soft_drop(self):
        if self.top_out or self.cur_shape is None:
            return (0, 0)
        ny = self.y + 1
        if not self.collide(self.x, ny, self.cur_shape, self.rot):
            self.y = ny
            return (0, 1)  # 軟降給 1 分
        # 落地鎖定
        return self.lock_piece()

    def hard_drop(self):
        if self.top_out or self.cur_shape is None:
            return (0, 0)
        dist = 0
        while not self.collide(self.x, self.y + 1, self.cur_shape, self.rot):
            self.y += 1
            dist += 1
        # 硬降額外分數（每格 2 分）
        lines, base = self.lock_piece()
        return lines, base + dist * 2

    def gravity_step(self):
        if self.top_out or self.cur_shape is None:
            return (0, 0)
        if not self.collide(self.x, self.y + 1, self.cur_shape, self.rot):
            self.y += 1
            return (0, 0)
        return self.lock_piece()

    def hold(self):
        if self.top_out or self.cur_shape is None:
            return
        if self.hold_used:  # 每回合只能 hold 一次
            return
        self.hold_used = True
        if self.hold_slot is None:
            self.hold_slot = self.cur_shape
            self.cur_shape = None
            self.spawn_if_needed()
        else:
            self.hold_slot, self.cur_shape = self.cur_shape, self.hold_slot
            self.rot, self.x, self.y = 0, 3, 0
            if self.collide(self.x, self.y, self.cur_shape, self.rot):
                self.top_out = True

    # ---------- snapshot ----------
    def snapshot(self, minified: bool = False) -> EngineSnapshot:
        active = None
        if self.cur_shape is not None:
            active = {"shape": self.cur_shape,
                      "x": self.x, "y": self.y, "rot": self.rot}
        nxt3 = self.queue[:3]
        board = self.board if not minified else self.minify_board(self.board)
        return EngineSnapshot(
            board=board,
            active=active,
            next3=nxt3,
            hold=self.hold_slot
        )

    @staticmethod
    def minify_board(board: List[List[int]]) -> List[List[int]]:
        # 觀戰縮圖可用：抽稀取樣（2x2 -> 1）
        out_h = len(board)//2
        out_w = len(board[0])//2
        mini = [[0]*out_w for _ in range(out_h)]
        for y in range(out_h):
            for x in range(out_w):
                block = (board[2*y][2*x] or board[2*y][2*x+1] or
                         board[2*y+1][2*x] or board[2*y+1][2*x+1])
                mini[y][x] = 1 if block else 0
        return mini

# ---------- utils ----------


def rle_encode_board(board: List[List[int]]) -> str:
    """簡單 RLE：逐行壓縮，e.g. '5x0,3x2,1x0|10x0|...' """
    rows = []
    for row in board:
        out = []
        last = row[0]
        cnt = 1
        for v in row[1:]:
            if v == last:
                cnt += 1
            else:
                out.append(f"{cnt}x{last}")
                last, cnt = v, 1
        out.append(f"{cnt}x{last}")
        rows.append(",".join(out))
    return "|".join(rows)
