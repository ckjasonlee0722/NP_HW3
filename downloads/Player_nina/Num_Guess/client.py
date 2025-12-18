# Num_Guess/client.py
import socket
import argparse
import json
import struct
import sys
import threading
import time
import os


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
        body = sock.recv(ln)
        return json.loads(body.decode("utf-8"))
    except:
        return None


def main():
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, required=True)
        parser.add_argument("--user-id", required=True)
        parser.add_argument("--role", default="player")
        args = parser.parse_args()

        print(f"\n=== 終極密碼對戰 (User {args.user_id}) ===", flush=True)

        # 1. 連線
        s = None
        print(f"[系統] 正在連線至遊戲伺服器...", end="", flush=True)
        for i in range(10):
            try:
                s = socket.create_connection(
                    (args.host, args.port), timeout=2.0)
                # 連線成功後移除 timeout
                s.settimeout(None)
                print(" 成功！", flush=True)
                break
            except:
                time.sleep(0.5)
                print(".", end="", flush=True)

        if not s:
            print("\n[錯誤] 無法連線到遊戲伺服器", flush=True)
            input("按 Enter 離開...")
            return

        # 2. 握手
        send_msg(s, {"type": "HELLO", "user_id": args.user_id})

        # 控制變數
        game_started = threading.Event()
        game_running = True

        # 3. 接收執行緒
        def receive_loop():
            nonlocal game_running
            while game_running:
                try:
                    msg = recv_msg(s)
                    if not msg:
                        print("\n[系統] 與伺服器斷線", flush=True)
                        game_running = False
                        game_started.set()  # 斷線也要解鎖輸入，讓程式能結束
                        break

                    mtype = msg.get("type")
                    text = msg.get("msg", "")

                    if mtype == "WELCOME":
                        print(f"\n[系統] {text}", flush=True)
                        print("[狀態] 等待其他玩家加入...", flush=True)
                    elif mtype == "START":
                        print(f"\n>>> {text} <<<", flush=True)
                        game_started.set()  # 解鎖輸入！
                    elif mtype == "RESULT":
                        print(f"\n[廣播] {text}", flush=True)
                        if msg.get("game_over"):
                            print("\n=== 遊戲結束 ===", flush=True)
                            game_running = False
                            game_started.set()
                            # 提示使用者
                            print("\n[提示] 請按 Enter 鍵離開視窗...", flush=True)
                except Exception as e:
                    print(f"Error: {e}")
                    break

        t = threading.Thread(target=receive_loop, daemon=True)
        t.start()

        # 4. 等待遊戲開始 (防止玩家提前輸入)
        while game_running and not game_started.is_set():
            time.sleep(0.5)

        if not game_running:
            input("按 Enter 離開...")
            return

        # 5. 遊戲主迴圈 (現在可以輸入了)
        print("\n[輸入] 請輸入數字 (1-100): ", end="", flush=True)

        while game_running:
            try:
                # 這裡會阻塞等待輸入
                user_input = input()

                # 如果遊戲已經結束，就不處理這次輸入
                if not game_running:
                    break

                if user_input.strip():
                    send_msg(s, {"type": "GUESS", "number": user_input})
                    # 再次顯示提示符號
                    if game_running:
                        print("[輸入] 請輸入數字: ", end="", flush=True)
            except:
                break

        try:
            s.close()
        except:
            pass

    except Exception as e:
        print(f"[錯誤] {e}", flush=True)
        input("按 Enter 離開...")


if __name__ == "__main__":
    main()
