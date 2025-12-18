# client/game_client.py
import sys
import time
import traceback
import os

# [關鍵修正] 全域錯誤捕捉，防止 import pygame 失敗時閃退
try:
    import argparse
    import json
    import socket
    import struct
    import threading
    import pygame  # 這裡最容易出錯
except ImportError as e:
    print("="*60)
    print(f"[嚴重錯誤] 套件載入失敗: {e}")
    print("請確認你的 Python 環境是否有安裝 pygame (pip install pygame)")
    print(f"目前使用的 Python: {sys.executable}")
    print("="*60)
    input("按 Enter 鍵離開...")
    sys.exit(1)
except Exception as e:
    print(f"[嚴重錯誤] 未知錯誤: {e}")
    input("按 Enter 鍵離開...")
    sys.exit(1)

# 設置 SDL 環境變數以相容 Windows
os.environ['SDL_VIDEODRIVER'] = 'windib'
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'

MAX_LEN = 65536
BOARD_W, BOARD_H = 10, 20
CELL = 24
MARGIN = 20
PREVIEW_SCALE = 0.5

PIECE_COLORS = {
    1: (45, 205, 255), 2: (255, 215, 55), 3: (190, 90, 255),
    4: (95, 230, 120), 5: (250, 90, 110), 6: (90, 140, 255), 7: (255, 165, 95),
    8: (180, 180, 180),
}
BG = (18, 20, 22)
GRID = (48, 50, 54)
GRID_OPP = (60, 62, 66)
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


def draw_board(surface, x, y, board, cell, is_alive=True):
    if not is_alive:
        pygame.draw.rect(surface, (40, 20, 20), (x, y, 10*cell, 20*cell))
    for j, row in enumerate(board):
        for i, v in enumerate(row):
            if v:
                col = PIECE_COLORS.get(int(v), PIECE_COLORS[8])
                if not is_alive:
                    col = (80, 80, 80)
                pygame.draw.rect(
                    surface, col, (x+i*cell+1, y+j*cell+1, cell-2, cell-2), border_radius=3)


def draw_active_piece(surface, x, y, active, cell):
    if not active:
        return
    shape = active.get("shape")
    px, py = active.get("x", 0), active.get("y", 0)
    rot = active.get("rot", 0)
    if not shape or shape not in SHAPES:
        return
    color_id = ORDER.index(shape) + 1
    color = PIECE_COLORS.get(color_id, PIECE_COLORS[8])
    for (dx, dy) in SHAPES[shape][rot % 4]:
        bx, by = px + dx, py + dy
        if 0 <= bx < BOARD_W and 0 <= by < BOARD_H:
            pygame.draw.rect(surface, color, (x+bx*cell+1, y +
                             by*cell+1, cell-2, cell-2), border_radius=3)


def nice_text(surface, font, txt, color, center):
    s = font.render(txt, True, (0, 0, 0))
    r = s.get_rect(center=(center[0]+2, center[1]+2))
    surface.blit(s, r)
    img = font.render(txt, True, color)
    surface.blit(img, img.get_rect(center=center))


def main():
    try:
        ap = argparse.ArgumentParser()
        ap.add_argument("--host", default="127.0.0.1")
        ap.add_argument("--port", type=int, required=True)
        ap.add_argument("--user-id", type=int, required=True)
        ap.add_argument("--role", default="player")
        args = ap.parse_args()

        pygame.init()
        pygame.display.set_caption(f"Tetris Battle - User {args.user_id}")
        font = pygame.font.SysFont(
            "Consolas,Menlo,Monaco,monospace", 22, bold=True)
        font_big = pygame.font.SysFont(
            "Consolas,Menlo,Monaco,monospace", 48, bold=True)

        w_main, h_main = CELL * BOARD_W, CELL * BOARD_H
        w_opp, h_opp = int(w_main * PREVIEW_SCALE), int(h_main * PREVIEW_SCALE)
        # 根據人數動態調整視窗大小 (這裡預設最大支援空間)
        win_w = MARGIN*3 + w_main + 240 + w_opp
        win_h = max(h_main + MARGIN*2 + 100, MARGIN*3 + h_opp*2)
        screen = pygame.display.set_mode((win_w, win_h))

        # 連線重試
        net_sock = None
        print(f"[Client] Connecting to {args.host}:{args.port}...")
        for i in range(20):
            try:
                net_sock = socket.create_connection(
                    (args.host, args.port), timeout=2.0)
                net_sock.settimeout(None)
                print("[Client] Connected to server socket!")
                break
            except:
                time.sleep(0.5)

        if not net_sock:
            raise Exception("Cannot connect to game server (timeout).")

        print(f"[Client] Sending HELLO for User {args.user_id}...")
        send_msg(net_sock, {"type": "HELLO", "version": 1,
                 "userId": args.user_id, "role": args.role})
        print("[Client] HELLO sent.")

        # Game State
        my_state = {"board": [[0]*10 for _ in range(20)],
                    "score": 0, "lines": 0, "active": None}
        opponents = []
        final_result = None
        countdown = None
        disconnected = False
        lock = threading.Lock()
        plugins = []

        def rx_loop():
            nonlocal final_result, countdown, disconnected, opponents
            try:
                while True:
                    msg = recv_msg(net_sock)
                    t = msg.get("type")

                    if t == "COUNTDOWN":
                        with lock:
                            countdown = msg.get("seconds")
                    elif t == "START":
                        with lock:
                            countdown = None
                    elif t == "SNAPSHOT":
                        with lock:
                            my_state["board"] = msg.get("board")
                            my_state["score"] = msg.get("score")
                            my_state["lines"] = msg.get("lines")
                            my_state["active"] = msg.get("active")

                            raw_opp = msg.get("opponents")
                            if raw_opp is None:
                                single = msg.get("opponent")
                                opponents = [single] if single else []
                            else:
                                opponents = raw_opp
                    elif t == "GAME_OVER":
                        with lock:
                            final_result = msg
                    elif t == "PLUGIN" or t == "CHAT":
                        with lock:
                            for p in plugins:
                                if hasattr(p, "on_message"):
                                    p.on_message(msg)
            except Exception as e:
                print(f"[Network] Disconnected: {e}")
                disconnected = True

        threading.Thread(target=rx_loop, daemon=True).start()
        clock = pygame.time.Clock()

        running = True
        while running:
            events = pygame.event.get()
            for ev in events:
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        running = False

                    act = None
                    if ev.key in (pygame.K_LEFT, pygame.K_a):
                        act = "LEFT"
                    elif ev.key in (pygame.K_RIGHT, pygame.K_d):
                        act = "RIGHT"
                    elif ev.key in (pygame.K_UP, pygame.K_w):
                        act = "CW"
                    elif ev.key in (pygame.K_z,):
                        act = "CCW"
                    elif ev.key in (pygame.K_DOWN, pygame.K_s):
                        act = "SOFT"
                    elif ev.key == pygame.K_SPACE:
                        act = "HARD"
                    elif ev.key == pygame.K_c:
                        act = "HOLD"

                    if act and not disconnected:
                        try:
                            send_msg(
                                net_sock, {"type": "INPUT", "userId": args.user_id, "action": act})
                        except:
                            pass

                for p in plugins:
                    if hasattr(p, "handle_event"):
                        p.handle_event(ev)

            screen.fill(BG)

            with lock:
                me = my_state.copy()
                opps = list(opponents)
                cd = countdown
                fin = final_result
                disc = disconnected

            # Draw Self
            mx, my = MARGIN + 120, MARGIN
            pygame.draw.rect(screen, PANEL, (mx-8, my-8, w_main +
                             16, h_main+16), border_radius=12)
            draw_grid(screen, mx, my, 10, 20, CELL, GRID)
            draw_board(screen, mx, my, me["board"], CELL)
            draw_active_piece(screen, mx, my, me["active"], CELL)
            nice_text(screen, font,
                      f"Score: {me['score']}", WHITE, (mx+w_main//2, h_main+40))

            # Draw Opponents
            ox, oy = mx + w_main + MARGIN*3, MARGIN
            for i, opp in enumerate(opps):
                y_pos = oy + i * (h_opp + 40)
                pygame.draw.rect(screen, PANEL, (ox-8, y_pos-8,
                                 w_opp+16, h_opp+16), border_radius=8)
                draw_grid(screen, ox, y_pos, 10, 20, int(
                    CELL*PREVIEW_SCALE), GRID_OPP)
                draw_board(screen, ox, y_pos, opp.get("board", []),
                           int(CELL*PREVIEW_SCALE), opp.get("alive", True))
                draw_active_piece(screen, ox, y_pos, opp.get(
                    "active"), int(CELL*PREVIEW_SCALE))
                nice_text(
                    screen, font, f"P{opp.get('side', '?')+1}", ACCENT, (ox+w_opp//2, y_pos-15))

            # Overlays
            cx, cy = win_w//2, win_h//2
            if cd is not None:
                nice_text(screen, font_big, f"Start in {cd}", ACCENT, (cx, cy))
            elif fin:
                nice_text(screen, font_big,
                          f"Winner: {fin.get('winner')}", ACCENT, (cx, cy))
            elif disc:
                nice_text(screen, font_big, "Disconnected",
                          (255, 50, 50), (cx, cy))

            for p in plugins:
                if hasattr(p, "draw"):
                    p.draw(screen)

            pygame.display.flip()
            clock.tick(60)

        try:
            net_sock.close()
        except:
            pass
        pygame.quit()

    except Exception as e:
        print("\n" + "="*60)
        print(f"[CRASH] 遊戲客戶端發生錯誤: {e}")
        print("詳細錯誤訊息:")
        traceback.print_exc()
        print("="*60)
        input("按 Enter 鍵結束...")


if __name__ == "__main__":
    main()
