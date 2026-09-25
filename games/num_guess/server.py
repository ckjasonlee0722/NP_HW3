# Num_Guess/server.py
import socket
import threading
import argparse
import json
import struct
import time
import random

MAX_LEN = 65536


def send_msg(sock, data):
    try:
        body = json.dumps(data).encode("utf-8")
        sock.sendall(struct.pack("!I", len(body)) + body)
    except:
        pass


def recv_msg(sock):
    try:
        hdr = sock.recv(4)
        if not hdr:
            return None
        (ln,) = struct.unpack("!I", hdr)
        if ln > MAX_LEN:
            return None
        body = sock.recv(ln)
        return json.loads(body.decode("utf-8"))
    except:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--users", type=str, required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--public-host", default="")
    parser.add_argument("--room-id", default="")
    parser.add_argument("--mode", default="")
    parser.add_argument("--drop-ms", default="")
    args = parser.parse_args()

    expected_users = args.users.split(",")
    print(f"[Server] 等待玩家: {expected_users} 在 Port {args.port}")

    target_number = random.randint(1, 100)
    conns = {}
    lock = threading.Lock()
    game_over = False

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((args.host, args.port))
    s.listen(5)
    s.settimeout(1.0)  # 這是為了讓 accept 迴圈不卡死

    # 1. 等待連線
    wait_start = time.time()
    while len(conns) < len(expected_users):
        try:
            c, a = s.accept()
            c.settimeout(None)  # 連線建立後移除 accept 的超時設定

            msg = recv_msg(c)
            if msg and msg.get("type") == "HELLO":
                uid = str(msg.get("user_id"))
                if uid in expected_users:
                    conns[uid] = c
                    print(f"[Server] 玩家 {uid} 已連線")
                    send_msg(c, {"type": "WELCOME", "msg": "等待其他玩家..."})
                else:
                    c.close()

            if time.time() - wait_start > 60:  # 延長等待時間到 60秒
                print("[Server] 等待超時")
                break
        except socket.timeout:
            continue
        except Exception as e:
            print(f"[Server] 連線錯誤: {e}")

    if len(conns) < len(expected_users):
        print("[Server] 人數不足，關閉伺服器")
        s.close()
        return

    print(f"[Server] 遊戲開始！目標: {target_number}")
    for c in conns.values():
        send_msg(c, {"type": "START", "msg": "遊戲開始！請猜 1-100 的數字"})

    # 2. 處理玩家
    def handle_client(uid, conn):
        nonlocal game_over
        while not game_over:
            msg = recv_msg(conn)
            if not msg:
                break

            if msg.get("type") == "GUESS":
                try:
                    guess = int(msg.get("number"))
                    result_msg = ""
                    is_win = False

                    with lock:
                        if game_over:
                            break

                        if guess == target_number:
                            result_msg = f"🎉 玩家 {uid} 猜中了 {guess}！遊戲結束！"
                            game_over = True
                            is_win = True
                        elif guess < target_number:
                            result_msg = f"玩家 {uid} 猜 {guess} (太小了)"
                        else:
                            result_msg = f"玩家 {uid} 猜 {guess} (太大了)"

                    pkt = {
                        "type": "RESULT",
                        "msg": result_msg,
                        "game_over": is_win,
                        "winner": uid if is_win else None
                    }
                    for c in conns.values():
                        send_msg(c, pkt)

                except ValueError:
                    pass

    threads = []
    for uid, c in conns.items():
        t = threading.Thread(target=handle_client, args=(uid, c))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    print("[Server] 結束")
    time.sleep(2)
    s.close()


if __name__ == "__main__":
    main()
