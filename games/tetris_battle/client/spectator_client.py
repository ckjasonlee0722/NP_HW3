# clients/spectator_client.py
import argparse
import json
import socket
import struct
import threading
import time
import sys
import pygame
import os

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
MAX_LEN = 65536
BOARD_W, BOARD_H = 10, 20
CELL = 18
MARGIN = 16
GRID = (60, 62, 66)
PANEL = (30, 32, 36)
BG = (18, 20, 22)
WHITE = (235, 235, 235)
ACCENT = (255, 160, 35)

PIECE_COLORS = {
    1: (45, 205, 255), 2: (255, 215, 55), 3: (190, 90, 255),
    4: (95, 230, 120), 5: (250, 90, 110), 6: (90, 140, 255), 7: (255, 165, 95),
}
ORDER = ["I", "O", "T", "S", "Z", "J", "L"]
SHAPES = {
    "I": [[(0, 1), (1, 1), (2, 1), (3, 1)], [(2, 0), (2, 1), (2, 2), (2, 3)],
          [(0, 2), (1, 2), (2, 2), (3, 2)], [(1, 0), (1, 1), (1, 2), (1, 3)]],
    "O": [[(1, 0), (2, 0), (1, 1), (2, 1)]]*4,
    "T": [[(1, 0), (0, 1), (1, 1), (2, 1)], [(1, 0), (1, 1), (2, 1), (1, 2)],
          [(0, 1), (1, 1), (2, 1), (1, 2)], [(1, 0), (0, 1), (1, 1), (1, 2)]],
    "S": [[(1, 0), (2, 0), (0, 1), (1, 1)], [(1, 0), (1, 1), (2, 1), (2, 2)],
          [(1, 1), (2, 1), (0, 2), (1, 2)], [(0, 0), (0, 1), (1, 1), (1, 2)]],
    "Z": [[(0, 0), (1, 0), (1, 1), (2, 1)], [(2, 0), (1, 1), (2, 1), (1, 2)],
          [(0, 1), (1, 1), (1, 2), (2, 2)], [(1, 0), (0, 1), (1, 1), (0, 2)]],
    "J": [[(0, 0), (0, 1), (1, 1), (2, 1)], [(1, 0), (2, 0), (1, 1), (1, 2)],
          [(0, 1), (1, 1), (2, 1), (2, 2)], [(1, 0), (1, 1), (0, 2), (1, 2)]],
    "L": [[(2, 0), (0, 1), (1, 1), (2, 1)], [(1, 0), (1, 1), (1, 2), (2, 2)],
          [(0, 1), (1, 1), (2, 1), (0, 2)], [(0, 0), (1, 0), (1, 1), (1, 2)]],
}


def _readn(s, n):
    buf = b""
    while len(buf) < n:
        b = s.recv(n - len(buf))
        if not b:
            raise ConnectionError("socket closed")
        buf += b
    return buf


def recv_msg(s):
    hdr = _readn(s, 4)
    (ln,) = struct.unpack("!I", hdr)
    if not (0 < ln <= MAX_LEN):
        raise ValueError("bad length")
    body = _readn(s, ln)
    return json.loads(body.decode("utf-8"))


def send_msg(s, obj):
    body = json.dumps(obj, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    if not (0 < len(body) <= MAX_LEN):
        raise ValueError("too large")
    s.sendall(struct.pack("!I", len(body)) + body)


def draw_grid(surf, x, y, w, h, cell):
    pygame.draw.rect(surf, GRID, (x-1, y-1, w*cell+2, h*cell+2), 1)
    for i in range(w):
        pygame.draw.line(surf, GRID, (x+i*cell, y), (x+i*cell, y+h*cell), 1)
    for j in range(h):
        pygame.draw.line(surf, GRID, (x, y+j*cell), (x+w*cell, y+j*cell), 1)


def draw_board(surf, x, y, board, cell):
    for j, row in enumerate(board):
        for i, v in enumerate(row):
            if v:
                col = PIECE_COLORS.get(int(v), (180, 180, 180))
                pygame.draw.rect(
                    surf, col, (x+i*cell+1, y+j*cell+1, cell-2, cell-2), border_radius=3)


def draw_active(surf, x, y, active, cell):
    if not active:
        return
    shape = active.get("shape")
    px = active.get("x", 0)
    py = active.get("y", 0)
    rot = active.get("rot", 0)
    if shape not in SHAPES:
        return
    color = PIECE_COLORS.get(ORDER.index(shape)+1, (200, 200, 200))
    for dx, dy in SHAPES[shape][rot % 4]:
        bx, by = px+dx, py+dy
        if 0 <= bx < BOARD_W and 0 <= by < BOARD_H:
            pygame.draw.rect(surf, color, (x+bx*cell+1, y+by *
                             cell+1, cell-2, cell-2), border_radius=3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--user-id", type=int, default=9999)
    args = ap.parse_args()

    pygame.init()
    pygame.display.set_caption("2P Tetris (spectator)")
    font = pygame.font.SysFont(
        "Consolas,Menlo,Monaco,monospace", 22, bold=True)
    font_big = pygame.font.SysFont(
        "Consolas,Menlo,Monaco,monospace", 48, bold=True)

    w = MARGIN*3 + BOARD_W*CELL*2 + 80
    h = MARGIN*2 + BOARD_H*CELL + 80
    screen = pygame.display.set_mode((w, h))

    s = socket.create_connection((args.host, args.port), timeout=10)
    s.settimeout(None)
    send_msg(s, {"type": "HELLO", "version": 1, "roomId": 0,
             "userId": args.user_id, "role": "spectator"})

    boards = {"P1": [[0]*BOARD_W for _ in range(BOARD_H)],
              "P2": [[0]*BOARD_W for _ in range(BOARD_H)]}
    actives = {"P1": None, "P2": None}
    started = False
    winner_text = None
    lock = threading.Lock()

    def rx():
        nonlocal started, winner_text
        try:
            while True:
                m = recv_msg(s)
                t = m.get("type")
                if t == "WELCOME":
                    pass
                elif t == "COUNTDOWN":
                    # spectator 顯示簡化，不做倒數字樣
                    pass
                elif t == "START":
                    with lock:
                        started = True
                elif t == "SNAPSHOT":
                    # 兩種格式都支援：有 who / 沒 who
                    p = m.get("who")
                    if p in ("P1", "P2"):
                        with lock:
                            boards[p] = m.get("board") or boards[p]
                            actives[p] = m.get("active")
                    else:
                        # 伺服器目前傳「我方 board、opponent.board」
                        with lock:
                            boards["P1"] = m.get("board") or boards["P1"]
                            op = m.get("opponent") or {}
                            boards["P2"] = op.get("board") or boards["P2"]
                            actives["P1"] = m.get("active")
                            actives["P2"] = op.get("active")
                elif t == "GAME_OVER":
                    wnr = m.get("winner", "draw")
                    txt = "DRAW" if wnr == "draw" else (
                        f"{wnr} WINS" if wnr in ("P1", "P2") else "FINISHED")
                    with lock:
                        winner_text = txt
                elif t == "BYE":
                    break
        except Exception:
            pass

    threading.Thread(target=rx, daemon=True).start()

    clock = pygame.time.Clock()
    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):
                running = False

        screen.fill(BG)
        with lock:
            b1 = [r[:] for r in boards["P1"]]
            b2 = [r[:] for r in boards["P2"]]
            a1 = actives["P1"]
            a2 = actives["P2"]
            wt = winner_text
            st = started

        x1 = MARGIN
        x2 = MARGIN + BOARD_W*CELL + 80
        y = MARGIN
        pygame.draw.rect(screen, PANEL, (x1-8, y-8, BOARD_W *
                         CELL+16, BOARD_H*CELL+16), border_radius=12)
        pygame.draw.rect(screen, PANEL, (x2-8, y-8, BOARD_W *
                         CELL+16, BOARD_H*CELL+16), border_radius=12)
        draw_grid(screen, x1, y, BOARD_W, BOARD_H, CELL)
        draw_grid(screen, x2, y, BOARD_W, BOARD_H, CELL)
        draw_board(screen, x1, y, b1, CELL)
        draw_active(screen, x1, y, a1, CELL)
        draw_board(screen, x2, y, b2, CELL)
        draw_active(screen, x2, y, a2, CELL)

        t1 = font.render("P1", True, WHITE)
        screen.blit(t1, (x1, y-30))
        t2 = font.render("P2", True, WHITE)
        screen.blit(t2, (x2, y-30))

        if not st:
            txt = font_big.render("Waiting for START...", True, ACCENT)
            screen.blit(txt, txt.get_rect(center=(w//2, h-40)))
        if wt:
            txt = font_big.render(wt, True, ACCENT)
            screen.blit(txt, txt.get_rect(center=(w//2, h-40)))

        pygame.display.flip()
        clock.tick(60)

    try:
        s.close()
    except:
        pass
    pygame.quit()


if __name__ == "__main__":
    main()
