# client.py (Click War - 3人版)
import socket
import argparse
import json
import struct
import pygame
import sys
import threading
import time
import traceback


def recv_msg(sock):
    try:
        hdr = sock.recv(4)
        if not hdr:
            return None
        (ln,) = struct.unpack("!I", hdr)
        body = sock.recv(ln)
        return json.loads(body.decode("utf-8"))
    except:
        return None


def main():
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int)
        parser.add_argument("--user-id")
        parser.add_argument("--role")
        args = parser.parse_args()

        pygame.init()
        screen = pygame.display.set_mode((400, 400))  # 稍微加大視窗以容納3人
        pygame.display.set_caption(f"Click War - Player {args.user_id}")
        font = pygame.font.SysFont("Arial", 24)

        # 連線重試機制
        s = None
        print(f"[Client] Connecting to {args.host}:{args.port}...")
        for i in range(10):
            try:
                s = socket.create_connection(
                    (args.host, args.port), timeout=2.0)
                print("[Client] Connected!")
                break
            except:
                time.sleep(0.5)

        if s is None:
            print("[Client] Failed to connect.")
            return

        scores = {}
        winner = None
        running = True
        lock = threading.Lock()

        def listen():
            nonlocal scores, winner, running
            while running:
                try:
                    msg = recv_msg(s)
                    if not msg:
                        break
                    with lock:
                        scores = msg.get("scores", {})
                        if "WINNER" in scores:
                            winner = scores["WINNER"]
                except:
                    break
            running = False

        threading.Thread(target=listen, daemon=True).start()

        clock = pygame.time.Clock()
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE and not winner:
                        try:
                            s.sendall(str(args.user_id).encode())
                        except:
                            pass

            screen.fill((0, 0, 0))

            y = 20
            with lock:
                if not scores:
                    wait_surf = font.render(
                        "Waiting for players...", True, (150, 150, 150))
                    screen.blit(wait_surf, (50, 100))
                else:
                    # 動態顯示所有玩家分數 (支援 2人, 3人, 4人...)
                    for uid, sc in scores.items():
                        if uid == "WINNER":
                            continue
                        txt = f"Player {uid}: {sc}"
                        # 自己的分數顯示綠色，別人顯示白色
                        color = (0, 255, 0) if str(uid) == str(
                            args.user_id) else (255, 255, 255)
                        surf = font.render(txt, True, color)
                        screen.blit(surf, (50, y))
                        y += 40

                if winner:
                    msg = "YOU WIN!" if str(winner) == str(
                        args.user_id) else f"Player {winner} WINS!"
                    surf = font.render(msg, True, (255, 255, 0))
                    screen.blit(surf, (50, y + 20))
                else:
                    help_txt = font.render(
                        "PRESS SPACE TO CLICK!", True, (100, 100, 255))
                    screen.blit(help_txt, (50, 350))

            pygame.display.flip()
            clock.tick(30)

        try:
            s.close()
        except:
            pass
        pygame.quit()

    except Exception as e:
        print(f"[CRASH] {e}")
        traceback.print_exc()
        input("Press Enter...")


if __name__ == "__main__":
    main()
