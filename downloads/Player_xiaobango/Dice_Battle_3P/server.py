import socket
import threading
import argparse
import time
import json
import struct
import random
import traceback
import sys
import os  # [修正] 新增這個，用於強制殺死程序

# === [設定] 總共玩幾局? ===
MAX_ROUNDS = 3

# === [功能 1] 錯誤日誌 ===


def log_error(msg):
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open("server_error.log", "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {msg}\n")
    except:
        pass


# === [功能 2] 傳送鎖 ===
send_lock = threading.Lock()


def send_msg(sock, data):
    try:
        body = json.dumps(data).encode("utf-8")
        packed = struct.pack("!I", len(body)) + body
        with send_lock:
            sock.sendall(packed)
    except Exception as e:
        print(f"[Send Error] {e}")


def main():
    with open("server_error.log", "w") as f:
        f.write("=== Server Started ===\n")

    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--port", type=int, required=True)
        parser.add_argument("--users", type=str, required=True)
        parser.add_argument("--host", default="0.0.0.0")
        parser.add_argument("--public-host", default="127.0.0.1")
        parser.add_argument("--room-id", default=0)
        parser.add_argument("--mode", default="")
        parser.add_argument("--drop-ms", default="")
        args = parser.parse_args()

        expected_users = [u.strip() for u in args.users.split(",")]
        player_count = len(expected_users)
        print(f"[Server] Waiting for {player_count} players: {expected_users}")

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((args.host, args.port))
        s.listen(5)
        s.settimeout(None)

        conns = {}

        while len(conns) < player_count:
            try:
                c, addr = s.accept()
                c.settimeout(None)
                print(f"[Server] Connection from {addr}")
                conns[len(conns)] = c
                current_count = len(conns)
                for client in conns.values():
                    send_msg(
                        client, {"type": "INFO", "msg": f"Waiting ({current_count}/{player_count})..."})
            except Exception as e:
                print(f"Accept error: {e}")
                break

        print("[Server] Game Start!")
        time.sleep(1)

        player_rolls = {}
        scores = {}
        round_count = 1
        game_state = "PLAYING"
        logic_lock = threading.Lock()

        # 紀錄總分 (Optional: 如果你想算總冠軍的話)
        total_scores = {u: 0 for u in expected_users}

        # 廣播開始
        for c in conns.values():
            send_msg(c, {"type": "START_ROUND", "round": round_count})

        def handle_client(conn, idx):
            nonlocal round_count, game_state
            print(f"[Thread] Client {idx} handler started")
            while True:
                try:
                    raw = conn.recv(1024)
                    if not raw:
                        break

                    try:
                        data_str = raw.decode().strip()
                        cmds = data_str.split("ROLL")

                        for part in cmds:
                            uid = part.strip(":")
                            if not uid:
                                continue

                            with logic_lock:
                                if game_state != "PLAYING":
                                    continue

                                if uid not in player_rolls:
                                    rolls = [random.randint(1, 6)
                                             for _ in range(5)]
                                    total = sum(rolls)
                                    player_rolls[uid] = rolls
                                    scores[uid] = total

                                    # 累計總分
                                    if uid in total_scores:
                                        total_scores[uid] += total

                                    print(
                                        f"User {uid} rolled {rolls} (Total: {total})")
                                    for c in conns.values():
                                        send_msg(
                                            c, {"type": "PLAYER_ROLLED", "who": uid})

                            should_finish = False
                            with logic_lock:
                                if game_state == "PLAYING" and len(player_rolls) >= player_count:
                                    game_state = "SCORING"
                                    should_finish = True

                            if should_finish:
                                time.sleep(1)
                                max_score = -1
                                winners = []
                                for p, sc in scores.items():
                                    if sc > max_score:
                                        max_score = sc
                                        winners = [p]
                                    elif sc == max_score:
                                        winners.append(p)
                                w_msg = "DRAW" if len(
                                    winners) > 1 else str(winners[0])

                                r_data = {}
                                for p in expected_users:
                                    if p in player_rolls:
                                        r_data[p] = {
                                            "dice": player_rolls[p], "score": scores[p]}
                                    else:
                                        r_data[p] = {"dice": [0]*5, "score": 0}

                                for c in conns.values():
                                    send_msg(
                                        c, {"type": "RESULT", "winner": w_msg, "data": r_data})

                                print(
                                    f"Round {round_count} finished. Waiting 20s...")
                                time.sleep(20)

                                with logic_lock:
                                    player_rolls.clear()
                                    scores.clear()
                                    round_count += 1

                                    # === [關鍵修改] 檢查是否達到最大局數 ===
                                    if round_count > MAX_ROUNDS:
                                        print("Max rounds reached. Game Over.")
                                        # 1. 廣播結束訊息
                                        for c in conns.values():
                                            send_msg(
                                                c, {"type": "INFO", "msg": "GAME OVER! Thanks for playing."})

                                        time.sleep(2)  # 等待訊息送達

                                        # 2. [修正] 強制關閉所有 Client 連線
                                        print("Closing all connections...")
                                        for c in conns.values():
                                            try:
                                                c.close()
                                            except:
                                                pass

                                        s.close()

                                        # 3. [修正] 使用 os._exit(0) 強制殺死整個 Server 行程
                                        print("Server shutting down.")
                                        os._exit(0)
                                    else:
                                        game_state = "PLAYING"

                                for c in conns.values():
                                    send_msg(
                                        c, {"type": "START_ROUND", "round": round_count})

                                break

                    except Exception as e:
                        print(f"Logic Error: {e}")
                        continue
                except:
                    break

        threads = []
        for i, c in conns.items():
            t = threading.Thread(target=handle_client, args=(c, i))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        s.close()

    except Exception as e:
        print(f"[FATAL ERROR] {e}")


if __name__ == "__main__":
    main()
