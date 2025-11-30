# tetris_project/client/game_client.py
import argparse
import json
import socket
import struct
import threading
import time
import sys
import os
import pygame

# Set SDL environment variables for Windows compatibility
os.environ['SDL_VIDEODRIVER'] = 'windib'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'

MAX_LEN = 65536
BOARD_W, BOARD_H = 10, 20
CELL = 24
MARGIN = 18
PREVIEW_SCALE = 0.45

PIECE_COLORS = {
    1: (45, 205, 255), 2: (255, 215, 55), 3: (190, 90, 255),
    4: (95, 230, 120), 5: (250, 90, 110), 6: (90, 140, 255), 7: (255, 165, 95),
    8: (180, 180, 180),
}
BG = (18, 20, 22)
GRID = (48, 50, 54)
GRID_B = (60, 62, 66)
PANEL = (30, 32, 36)
WHITE = (230, 232, 235)
SUB = (170, 175, 180)
ACCENT = (255, 160, 35)

SHAPES = {
    "I": [[(0, 1), (1, 1), (2, 1), (3, 1)], [(2, 0), (2, 1), (2, 2), (2, 3)], [(0, 2), (1, 2), (2, 2), (3, 2)], [(1, 0), (1, 1), (1, 2), (1, 3)]],
    "O": [[(1, 0), (2, 0), (1, 1), (2, 1)]]*4,
    "T": [[(1, 0), (0, 1), (1, 1), (2, 1)], [(1, 0), (1, 1), (2, 1), (1, 2)], [(0, 1), (1, 1), (2, 1), (1, 2)], [(1, 0), (0, 1), (1, 1), (1, 2)]],
    "S": [[(1, 0), (2, 0), (0, 1), (1, 1)], [(1, 0), (1, 1), (2, 1), (2, 2)], [(1, 1), (2, 1), (0, 2), (1, 2)], [(0, 0), (0, 1), (1, 1), (1, 2)]],
    "Z": [[(0, 0), (1, 0), (1, 1), (2, 1)], [(2, 0), (1, 1), (2, 1), (1, 2)], [(0, 1), (1, 1), (1, 2), (2, 2)], [(1, 0), (0, 1), (1, 1), (0, 2)]],
    "J": [[(0, 0), (0, 1), (1, 1), (2, 1)], [(1, 0), (2, 0), (1, 1), (1, 2)], [(0, 1), (1, 1), (2, 1), (2, 2)], [(1, 0), (1, 1), (0, 2), (1, 2)]],
    "L": [[(2, 0), (0, 1), (1, 1), (2, 1)], [(1, 0), (1, 1), (1, 2), (2, 2)], [(0, 1), (1, 1), (2, 1), (0, 2)], [(0, 0), (1, 0), (1, 1), (1, 2)]],
}
ORDER = ["I", "O", "T", "S", "Z", "J", "L"]


def _readn(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed")
        buf += chunk
    return buf


def recv_msg(sock):
    hdr = _readn(sock, 4)
    (ln,) = struct.unpack("!I", hdr)
    if not (0 < ln <= MAX_LEN):
        raise ValueError("bad length")
    body = _readn(sock, ln)
    return json.loads(body.decode("utf-8"))


def send_msg(sock, obj):
    body = json.dumps(obj, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    sock.sendall(struct.pack("!I", len(body)) + body)


def draw_grid(surface, x, y, w, h, cell, grid_color):
    pygame.draw.rect(surface, grid_color, (x-1, y-1, w*cell+2, h*cell+2), 1)
    for i in range(w):
        pygame.draw.line(surface, grid_color, (x+i*cell, y),
                         (x+i*cell, y+h*cell), 1)
    for j in range(h):
        pygame.draw.line(surface, grid_color, (x, y+j*cell),
                         (x+w*cell, y+j*cell), 1)


def draw_board(surface, x, y, board, cell):
    for j, row in enumerate(board):
        for i, v in enumerate(row):
            if v:
                col = PIECE_COLORS.get(int(v) if isinstance(
                    v, int) else 8, PIECE_COLORS[8])
                rx, ry = x + i*cell, y + j*cell
                pygame.draw.rect(
                    surface, col, (rx+1, ry+1, cell-2, cell-2), border_radius=3)


def draw_active_piece(surface, x, y, active, cell):
    if not active:
        return
    shape = active.get("shape")
    px = active.get("x", 0)
    py = active.get("y", 0)
    rot = active.get("rot", 0)
    if not shape or shape not in SHAPES:
        return
    color_id = ORDER.index(shape) + 1
    color = PIECE_COLORS.get(color_id, PIECE_COLORS[8])
    cells = SHAPES[shape][rot % 4]
    for (dx, dy) in cells:
        bx = px + dx
        by = py + dy
        if 0 <= bx < BOARD_W and 0 <= by < BOARD_H:
            rx = x + bx * cell
            ry = y + by * cell
            pygame.draw.rect(surface, color, (rx+1, ry+1,
                             cell-2, cell-2), border_radius=3)


def draw_piece_preview(surface, x, y, shape, cell_size):
    if not shape or shape not in SHAPES:
        return
    color_id = ORDER.index(shape) + 1
    color = PIECE_COLORS.get(color_id, PIECE_COLORS[8])
    cells = SHAPES[shape][0]
    min_x = min(dx for dx, dy in cells)
    max_x = max(dx for dx, dy in cells)
    min_y = min(dy for dx, dy in cells)
    max_y = max(dy for dx, dy in cells)
    width = max_x - min_x + 1
    height = max_y - min_y + 1
    offset_x = (4 - width) * cell_size // 2 - min_x * cell_size
    offset_y = (4 - height) * cell_size // 2 - min_y * cell_size
    for (dx, dy) in cells:
        rx = x + offset_x + dx * cell_size
        ry = y + offset_y + dy * cell_size
        pygame.draw.rect(surface, color, (rx+1, ry+1,
                         cell_size-2, cell_size-2), border_radius=2)


def nice_text(surface, font, txt, color, center, shadow=True):
    if shadow:
        s = font.render(txt, True, (0, 0, 0))
        r = s.get_rect(center=(center[0]+2, center[1]+2))
        surface.blit(s, r)
    img = font.render(txt, True, color)
    surface.blit(img, img.get_rect(center=center))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--user-id", type=int, required=True)
    ap.add_argument("--role", default="player")
    args = ap.parse_args()

    pygame.init()
    pygame.display.set_caption(f"Tetris Battle - Player {args.user_id}")

    # 建立視窗
    font = pygame.font.SysFont(
        "Consolas,Menlo,Monaco,monospace", 22, bold=True)
    font_big = pygame.font.SysFont(
        "Consolas,Menlo,Monaco,monospace", 48, bold=True)
    font_mid = pygame.font.SysFont(
        "Consolas,Menlo,Monaco,monospace", 26, bold=True)
    w = MARGIN*4 + CELL*BOARD_W + int(PREVIEW_SCALE*BOARD_W*CELL) + 240 + 100
    h = MARGIN*2 + CELL*BOARD_H + 120
    screen = pygame.display.set_mode((w, h))

    # [關鍵修正] 連線重試機制
    net_sock = None
    print(f"[Client] Connecting to {args.host}:{args.port}...")
    for i in range(5):  # 重試 5 次
        try:
            net_sock = socket.create_connection(
                (args.host, args.port), timeout=2.0)
            print("[Client] Connected to game server")
            break
        except Exception as e:
            print(f"[Client] Connection failed ({i+1}/5): {e}")
            time.sleep(1.0)  # 等待 Server 啟動

    if not net_sock:
        print("[Client] Give up connecting.")
        # 即使連不上，也讓視窗停留一下顯示錯誤，不要直接閃退
        screen.fill(BG)
        nice_text(screen, font_mid, "Connection Failed", ACCENT, (w//2, h//2))
        pygame.display.flip()
        time.sleep(3)
        pygame.quit()
        sys.exit(1)

    try:
        # 送出 Hello
        send_msg(net_sock, {"type": "HELLO", "version": 1,
                 "roomId": 0, "userId": args.user_id, "role": args.role})
    except Exception as e:
        print(f"[Client] Send HELLO failed: {e}")

    # Game state
    net = type("Net", (), {})()
    net.sock = net_sock
    net.alive = True
    net.role = "P?"
    net.drop_ms = None

    board_me = [[0]*BOARD_W for _ in range(BOARD_H)]
    board_opp = [[0]*BOARD_W for _ in range(BOARD_H)]
    score_me = 0
    lines_me = 0
    tempo = None
    active_me = None
    active_opp = None
    hold_me = None
    next_me = []
    final_result = None
    disconnected = False
    countdown_value = None
    game_started = False

    lock = threading.Lock()

    def rx_loop():
        nonlocal board_me, board_opp, score_me, lines_me, tempo, final_result, disconnected, countdown_value, game_started, active_me, active_opp, hold_me, next_me
        try:
            while True:
                msg = recv_msg(net.sock)
                t = msg.get("type")
                if t == "WELCOME":
                    net.role = msg.get("role", net.role)
                    gp = msg.get("gravityPlan") or {}
                    net.drop_ms = gp.get("dropMs")
                elif t == "COUNTDOWN":
                    with lock:
                        countdown_value = msg.get("seconds", 0)
                elif t == "START":
                    with lock:
                        countdown_value = None
                        game_started = True
                elif t == "SNAPSHOT":
                    with lock:
                        board_me = msg.get("board") or board_me
                        score_me = msg.get("score", score_me)
                        lines_me = msg.get("lines", lines_me)
                        active_me = msg.get("active")
                        hold_me = msg.get("hold")
                        next_me = msg.get("next") or []
                        opp = msg.get("opponent") or {}
                        board_opp = opp.get("board") or board_opp
                        active_opp = opp.get("active")
                        gp = msg.get("gravityPlan") or {}
                        tempo = gp.get("dropMs", tempo)
                elif t == "GAME_OVER":
                    with lock:
                        final_result = msg
        except Exception as e:
            print(f"[Client] Connection error: {e}")
            net.alive = False
            disconnected = True

    threading.Thread(target=rx_loop, daemon=True).start()
    clock = pygame.time.Clock()

    def send_input(act):
        if not net.alive:
            return
        with lock:
            if not game_started:
                return
        try:
            send_msg(net.sock, {"type": "INPUT",
                     "userId": args.user_id, "action": act})
        except:
            pass

    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    running = False
                elif ev.key in (pygame.K_LEFT, pygame.K_a):
                    send_input("LEFT")
                elif ev.key in (pygame.K_RIGHT, pygame.K_d):
                    send_input("RIGHT")
                elif ev.key in (pygame.K_UP, pygame.K_w, pygame.K_x):
                    send_input("CW")
                elif ev.key in (pygame.K_z,):
                    send_input("CCW")
                elif ev.key in (pygame.K_DOWN, pygame.K_s):
                    send_input("SOFT")
                elif ev.key == pygame.K_SPACE:
                    send_input("HARD")
                elif ev.key == pygame.K_c:
                    send_input("HOLD")

        screen.fill(BG)
        main_x, main_y = MARGIN + 120, MARGIN
        opp_x = main_x + CELL*BOARD_W + MARGIN*2
        opp_cell = int(CELL * PREVIEW_SCALE)

        pygame.draw.rect(screen, PANEL, (main_x-8, main_y-8,
                         CELL*BOARD_W+16, CELL*BOARD_H+16), border_radius=12)
        pygame.draw.rect(screen, PANEL, (opp_x-8, main_y-8, opp_cell *
                         BOARD_W+16, opp_cell*BOARD_H+16), border_radius=12)
        draw_grid(screen, main_x, main_y, BOARD_W, BOARD_H, CELL, GRID)
        draw_grid(screen, opp_x, main_y, BOARD_W, BOARD_H, opp_cell, GRID_B)
        pygame.draw.rect(screen, WHITE, (opp_x-8, main_y-8, opp_cell *
                         BOARD_W+16, opp_cell*BOARD_H+16), width=1, border_radius=12)

        with lock:
            me = [row[:] for row in board_me]
            op = [row[:] for row in board_opp]
            sc, ln, tempo_ms = score_me, lines_me, tempo
            act_me, act_op, hld, nxt = active_me, active_opp, hold_me, next_me[:3] if next_me else [
            ]
            cd = countdown_value
            fin = final_result
            disc = disconnected

        draw_board(screen, main_x, main_y, me, CELL)
        draw_active_piece(screen, main_x, main_y, act_me, CELL)
        draw_board(screen, opp_x, main_y, op, opp_cell)
        draw_active_piece(screen, opp_x, main_y, act_op, opp_cell)

        # HUD
        hold_x = main_x - 120
        hold_y = main_y
        if hold_x > 0:
            nice_text(screen, font, "HOLD", SUB,
                      (hold_x + 48, hold_y - 10), shadow=False)
            pygame.draw.rect(
                screen, PANEL, (hold_x, hold_y, 96, 96), border_radius=8)
            pygame.draw.rect(screen, GRID, (hold_x, hold_y,
                             96, 96), 1, border_radius=8)
            if hld:
                draw_piece_preview(screen, hold_x + 12, hold_y + 12, hld, 18)

        next_x = opp_x + int(opp_cell * BOARD_W) + 20
        next_y = main_y
        w_screen = MARGIN*4 + CELL*BOARD_W + \
            int(PREVIEW_SCALE*BOARD_W*CELL) + 240 + 100
        if next_x + 100 < w_screen:
            nice_text(screen, font, "NEXT", SUB,
                      (next_x + 48, next_y - 10), shadow=False)
            for i, piece in enumerate(nxt):
                box_y = next_y + i * 100
                pygame.draw.rect(
                    screen, PANEL, (next_x, box_y, 96, 96), border_radius=8)
                pygame.draw.rect(screen, GRID, (next_x, box_y,
                                 96, 96), 1, border_radius=8)
                draw_piece_preview(screen, next_x + 12, box_y + 12, piece, 18)

        h_screen = MARGIN*2 + CELL*BOARD_H + 120
        hud = f"score={sc}   lines={ln}   tempo={tempo_ms if tempo_ms else '?'} ms"
        nice_text(screen, font, hud, SUB,
                  (w_screen//2, h_screen-28), shadow=False)

        if cd is not None and cd >= 0:
            if cd > 0:
                nice_text(screen, font_big, str(cd), ACCENT,
                          (w_screen//2, h_screen//2 - 8))
                nice_text(screen, font_mid, "Get Ready!", WHITE,
                          (w_screen//2, h_screen//2 + 36))
            else:
                nice_text(screen, font_big, "GO!", ACCENT,
                          (w_screen//2, h_screen//2 - 8))
        elif fin is not None:
            winner = fin.get("winner")
            text = "DRAW"
            if net.role in ("P1", "P2"):
                if winner == "draw":
                    text = "DRAW"
                elif winner == net.role:
                    text = "YOU WIN"
                else:
                    text = "YOU LOSE"
            nice_text(screen, font_big, text, ACCENT,
                      (w_screen//2, h_screen//2 - 8))
            nice_text(screen, font_mid, "Press ESC to exit",
                      WHITE, (w_screen//2, h_screen//2 + 36))
        elif disc:
            nice_text(screen, font_big, "DISCONNECTED",
                      ACCENT, (w_screen//2, h_screen//2 - 8))
            nice_text(screen, font_mid, "Press ESC to exit",
                      WHITE, (w_screen//2, h_screen//2 + 36))

        pygame.display.flip()
        clock.tick(60)

    try:
        net.sock.close()
    except:
        pass
    pygame.quit()


if __name__ == "__main__":
    main()
