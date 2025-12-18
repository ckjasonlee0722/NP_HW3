# Click_War/server.py
import socket
import threading
import argparse
import time
import json
import struct


def send_msg(sock, data):
    try:
        body = json.dumps(data).encode("utf-8")
        sock.sendall(struct.pack("!I", len(body)) + body)
    except:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int)
    parser.add_argument("--users", type=str)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--public-host", default="127.0.0.1")
    # 接收但不使用的參數 (為了相容性)
    parser.add_argument("--room-id", default=0)
    parser.add_argument("--mode", default="")
    parser.add_argument("--drop-ms", default="")
    args = parser.parse_args()

    expected_users = args.users.split(",")
    print(f"Waiting for {len(expected_users)} players: {expected_users}")

    scores = {uid: 0 for uid in expected_users}
    conns = []

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # [關鍵修正] 允許端口重用 (解決 Address already in use 問題)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        s.bind((args.host, args.port))
    except Exception as e:
        print(f"[Fatal Error] Bind failed: {e}")
        return

    s.listen(5)
    s.settimeout(10.0)

    print(f"Click War Server listening on {args.port}...")

    # 等待所有玩家
    while len(conns) < len(expected_users):
        try:
            c, a = s.accept()
            c.settimeout(None)
            conns.append(c)
            print(f"Player connected: {a}")
        except socket.timeout:
            break

    if len(conns) < len(expected_users):
        print(
            f"Not enough players (Got {len(conns)}/{len(expected_users)}). Shutting down.")
        s.close()
        return

    print("All players connected! Game Start!")

    def broadcast():
        for c in conns:
            send_msg(c, {"scores": scores})

    broadcast()
    lock = threading.Lock()

    def handle(conn):
        while True:
            try:
                data = conn.recv(1024)
                if not data:
                    break

                uid = data.decode().strip()
                if uid in scores:
                    with lock:
                        scores[uid] += 1
                        if scores[uid] >= 50:
                            scores["WINNER"] = uid
                    broadcast()
                    if "WINNER" in scores:
                        break
            except:
                break

    threads = []
    for c in conns:
        t = threading.Thread(target=handle, args=(c,))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    time.sleep(2)
    s.close()


if __name__ == "__main__":
    main()
