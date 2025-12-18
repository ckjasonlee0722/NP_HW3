import socket
import argparse
import json
import struct
import pygame
import threading
import time
import sys
import traceback

# === 網路穩定接收區 ===


def recvall(sock, n):
    data = b''
    while len(data) < n:
        try:
            packet = sock.recv(n - len(data))
            if not packet:
                return None
            data += packet
        except:
            return None
    return data


def recv_msg(sock):
    try:
        hdr = recvall(sock, 4)
        if not hdr:
            return None
        (ln,) = struct.unpack("!I", hdr)
        body = recvall(sock, ln)
        if not body:
            return None
        return json.loads(body.decode("utf-8"))
    except:
        return None

# === 畫圖區 ===


def draw_dice(screen, x, y, value, font):
    pygame.draw.rect(screen, (250, 250, 250), (x, y, 50, 50), border_radius=8)
    pygame.draw.rect(screen, (0, 0, 0), (x, y, 50, 50), 2, border_radius=8)
    if value > 0:
        color = (0, 0, 0)
        if value == 6:
            color = (200, 0, 0)
        txt = font.render(str(value), True, color)
        text_rect = txt.get_rect(center=(x + 25, y + 25))
        screen.blit(txt, text_rect)
    else:
        txt = font.render("?", True, (180, 180, 180))
        text_rect = txt.get_rect(center=(x + 25, y + 25))
        screen.blit(txt, text_rect)


def game_loop(args):
    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    pygame.display.set_caption(f"Dice Battle - Player {args.user_id}")

    font = pygame.font.SysFont("Arial", 20)
    dice_font = pygame.font.SysFont("Arial", 30, bold=True)
    big_font = pygame.font.SysFont("Arial", 50, bold=True)
    warn_font = pygame.font.SysFont("Arial", 40, bold=True)

    print(f"Connecting to {args.host}:{args.port}...")
    s = None
    for i in range(10):
        try:
            s = socket.create_connection((args.host, args.port), timeout=2.0)
            break
        except:
            time.sleep(0.5)

    if not s:
        print("Connection failed.")
        return

    s.settimeout(None)
    print("Connected! Ready to play.")

    state = "WAITING"
    msg_text = "Waiting for players..."
    result_text = ""
    game_data = {}
    my_rolled = False

    lock = threading.Lock()
    running = True

    def listen():
        nonlocal state, msg_text, result_text, game_data, my_rolled, running
        while running:
            try:
                data = recv_msg(s)
                if not data:
                    print("Server disconnected.")
                    break
                dtype = data.get("type")
                with lock:
                    if dtype == "INFO":
                        msg_text = data.get("msg")
                        # === [修正] 偵測 GAME OVER 訊號 ===
                        if "GAME OVER" in msg_text:
                            print("Game Over received. Exiting in 3 seconds...")
                            time.sleep(3)  # 給玩家一點時間看訊息
                            running = False
                        # ===============================
                    elif dtype == "START_ROUND":
                        state = "ROLL"
                        msg_text = f"Round {data.get('round')} - YOUR TURN!"
                        result_text = ""
                        game_data = {}
                        my_rolled = False
                    elif dtype == "PLAYER_ROLLED":
                        pass
                    elif dtype == "RESULT":
                        state = "RESULT"
                        winner = data.get("winner")
                        game_data = data.get("data") or {}
                        if "DRAW" in str(winner):
                            if str(args.user_id) in winner:
                                result_text = "DRAW! (Tie)"
                            else:
                                result_text = "DRAW"
                        elif str(winner) == str(args.user_id):
                            result_text = "YOU WIN! 🎉"
                        else:
                            result_text = f"Player {winner} WINS!"
                        msg_text = "Round finished. Next round soon..."
            except:
                break
        running = False

    t = threading.Thread(target=listen, daemon=True)
    t.start()

    clock = pygame.time.Clock()

    # 定義觸發擲骰的函式
    def do_roll():
        nonlocal my_rolled, msg_text
        if state == "ROLL" and not my_rolled:
            try:
                my_rolled = True
                with lock:
                    msg_text = "Rolled! Good Luck..."
                s.sendall(f"{args.user_id}:ROLL".encode())
                print(f"[Client] Sent ROLL command!")
            except Exception as e:
                print(f"[Error] Send failed: {e}")

    while running:
        is_focused = pygame.key.get_focused()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    do_roll()

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    do_roll()

        screen.fill((46, 139, 87))

        with lock:
            title = font.render(msg_text, True, (255, 255, 255))
            screen.blit(title, (20, 20))

            if state == "RESULT":
                color = (255, 215, 0) if "YOU" in result_text else (
                    200, 200, 200)
                res_surf = big_font.render(result_text, True, color)
                rect = res_surf.get_rect(center=(400, 300))
                shadow = big_font.render(result_text, True, (0, 0, 0))
                screen.blit(shadow, (rect.x+2, rect.y+2))
                screen.blit(res_surf, rect)

            opponents = []
            my_info = {"dice": [0]*5, "score": 0, "uid": args.user_id}
            if state == "RESULT" and game_data:
                for uid, info in game_data.items():
                    if str(uid) == str(args.user_id):
                        my_info = info
                        my_info["uid"] = uid
                    else:
                        info["uid"] = uid
                        opponents.append(info)

        opp_positions = [(50, 80), (450, 80)]
        for i, pos in enumerate(opp_positions):
            ox, oy = pos
            pygame.draw.rect(screen, (34, 100, 34),
                             (ox, oy, 300, 150), border_radius=10)
            opp_data = opponents[i] if i < len(opponents) else None
            label_text = f"Opponent {i+1}" if not opp_data else f"P{opp_data['uid']}"
            score_text = str(opp_data['score']) if opp_data else "?"
            dice_vals = opp_data['dice'] if opp_data else [0]*5

            screen.blit(font.render(
                f"{label_text} (Score: {score_text})", True, (200, 200, 200)), (ox+10, oy+10))
            for d_idx, val in enumerate(dice_vals):
                draw_dice(screen, ox + 20 + d_idx*55, oy + 60, val, dice_font)

        mx, my = 200, 350
        bg_color = (0, 80, 0)
        # 輪到你時閃爍
        if state == "ROLL" and not my_rolled:
            bg_color = (0, 120, 0)
            if (pygame.time.get_ticks() // 500) % 2 == 0:
                pygame.draw.rect(screen, (255, 215, 0),
                                 (mx-5, my-5, 410, 160), border_radius=15)

        pygame.draw.rect(screen, bg_color,
                         (mx, my, 400, 150), border_radius=10)
        my_score_text = str(my_info['score']) if state == "RESULT" else "?"
        screen.blit(font.render(
            f"ME (Score: {my_score_text})", True, (155, 255, 155)), (mx+10, my+10))
        for d_idx, val in enumerate(my_info['dice']):
            val_draw = val
            if state != "RESULT":
                val_draw = 0
            draw_dice(screen, mx + 60 + d_idx*60, my + 60, val_draw, dice_font)

        # 提示文字更新
        if not is_focused:
            pygame.draw.rect(screen, (255, 50, 50), (0, 0, 800, 600), 8)
            warn = warn_font.render("CLICK ME!", True, (255, 255, 255))
            warn_bg = pygame.Surface(
                (warn.get_width()+20, warn.get_height()+10))
            warn_bg.fill((255, 0, 0))
            rect = warn.get_rect(center=(400, 550))
            screen.blit(warn_bg, (rect.x-10, rect.y-5))
            screen.blit(warn, rect)
        elif state == "ROLL" and not my_rolled:
            msg = warn_font.render(
                "CLICK or SPACE to ROLL!", True, (255, 255, 0))
            rect = msg.get_rect(center=(400, 550))
            screen.blit(msg, rect)

        pygame.display.flip()
        clock.tick(30)

    try:
        s.close()
    except:
        pass
    pygame.quit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument("--user-id")
    args = parser.parse_args()
    try:
        game_loop(args)
    except:
        pass


if __name__ == "__main__":
    main()
