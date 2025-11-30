# player_client.py
import socket
import json
import os
import zipfile
import io
import subprocess
import sys
import argparse
import time
from utils.protocol import send_message, recv_message, recv_file


class PlayerClient:
    def __init__(self, host, port):
        self.server_addr = (host, port)
        # user_id 和 base_dir 會在登入成功後才設定
        self.user_id = None
        self.username = None
        self.base_dir = None
        self.conn = None

    def connect(self):
        try:
            return socket.create_connection(self.server_addr, timeout=None)
        except Exception as e:
            print(f"[系統] 連線失敗: {e}")
            return None

    def close(self):
        if self.conn:
            try:
                self.conn.close()
            except:
                pass
            self.conn = None

    def _get_input(self, prompt, valid_range=None):
        while True:
            try:
                val = input(prompt).strip()
                if val == '0':
                    return None

                if not val.isdigit():
                    print("[錯誤] 請輸入數字。")
                    continue

                idx = int(val)
                if valid_range and (idx < 1 or idx > valid_range):
                    print(f"[錯誤] 請輸入 1 到 {valid_range} 之間的數字。")
                    continue

                return idx
            except KeyboardInterrupt:
                return None

    # ----------------- Auth 模組 -----------------
    def auth_register(self):
        print("\n=== 📝 註冊帳號 ===")
        user = input("帳號: ").strip()
        pwd = input("密碼: ").strip()
        if not user or not pwd:
            print("[錯誤] 帳號密碼不能為空")
            return False

        conn = self.connect()
        if not conn:
            return False
        try:
            send_message(conn, {
                "action": "auth_register",
                "data": {"username": user, "password": pwd, "role": "player"}
            })
            resp = recv_message(conn)
            if resp["status"] == "success":
                print(f"[成功] 註冊成功！ID: {resp['data']['id']}")
                return True
            else:
                print(f"[失敗] {resp.get('message')}")
                return False
        finally:
            conn.close()

    def auth_login(self):
        print("\n=== 🔓 登入系統 ===")
        user = input("帳號: ").strip()
        pwd = input("密碼: ").strip()

        conn = self.connect()
        if not conn:
            return False
        try:
            send_message(conn, {
                "action": "auth_login",
                "data": {"username": user, "password": pwd, "role": "player"}
            })
            resp = recv_message(conn)
            if resp["status"] == "success":
                data = resp["data"]
                self.user_id = data["id"]
                self.username = data["username"]

                # 設定下載目錄 (隔離環境)
                self.base_dir = os.path.join(
                    "downloads", f"Player_{self.username}")
                os.makedirs(self.base_dir, exist_ok=True)

                print(f"[成功] 歡迎回來, {self.username} (ID: {self.user_id})")
                return True
            else:
                print(f"[失敗] {resp.get('message')}")
                return False
        finally:
            conn.close()

    def auth_loop(self):
        while True:
            print("\n=== 歡迎來到遊戲大廳 ===")
            print("1. 登入 (Login)")
            print("2. 註冊 (Register)")
            print("0. 離開 (Exit)")

            choice = self._get_input("請選擇: ")

            if choice == 1:
                if self.auth_login():
                    return True  # 登入成功，進入主選單
            elif choice == 2:
                self.auth_register()
            elif choice == 0 or choice is None:
                return False  # 離開程式

    # ----------------- 功能模組 (維持不變，僅微調路徑) -----------------

    def fetch_store_list(self, quiet=False):
        conn = self.connect()
        if not conn:
            return []
        try:
            send_message(conn, {"action": "game_list", "data": {}})
            resp = recv_message(conn)
            if resp["status"] == "success":
                games = resp["data"]
                self.cached_store_games = games
                if not quiet:
                    print(f"\n=== 🛒 遊戲商城 (共 {len(games)} 款) ===")
                    print(f"{'No.':<4} {'Name':<20} {'Ver':<8} {'Author'}")
                    print("-" * 50)
                    for i, g in enumerate(games):
                        print(
                            f"{i+1:<4} {g['name']:<20} v{g['version']:<8} {g.get('author', '?')}")
                return games
            return []
        finally:
            conn.close()

    def flow_download(self):
        games = self.fetch_store_list()
        if not games:
            print("[提示] 商城無遊戲。")
            return
        idx = self._get_input(
            f"\n請輸入編號下載 (1-{len(games)}) 或 '0' 返回: ", len(games))
        if not idx:
            return
        self._do_download(games[idx-1]["name"])

    def _do_download(self, game_name):
        conn = self.connect()
        try:
            print(f"[系統] 正在下載 '{game_name}' ...")
            send_message(conn, {"action": "download_game",
                         "data": {"game_name": game_name}})
            resp = recv_message(conn)
            if resp["status"] != "success":
                print(f"[失敗] {resp.get('message')}")
                return
            meta = resp["data"]
            zip_data = recv_file(conn)

            install_path = os.path.join(self.base_dir, game_name)
            import shutil
            if os.path.exists(install_path):
                shutil.rmtree(install_path)
            os.makedirs(install_path, exist_ok=True)

            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                zf.extractall(install_path)
            with open(os.path.join(install_path, "execution.json"), "w") as f:
                json.dump(meta, f, indent=2)
            print(f"[成功] 已安裝至: {install_path}")
        except Exception as e:
            print(f"[錯誤] 下載失敗: {e}")
        finally:
            conn.close()

    def get_local_games(self):
        if not os.path.exists(self.base_dir):
            return []
        return [d for d in os.listdir(self.base_dir) if os.path.isdir(os.path.join(self.base_dir, d))]

    def flow_create_room(self):
        local_games = self.get_local_games()
        if not local_games:
            print("[提示] 請先去商城下載遊戲。")
            return
        print(f"\n=== 🏠 建立房間 ===")
        for i, name in enumerate(local_games):
            print(f"{i+1}. {name}")
        idx = self._get_input(
            f"請輸入編號 (1-{len(local_games)}) 或 '0' 返回: ", len(local_games))
        if not idx:
            return
        self._wait_for_game_start(local_games[idx-1], is_host=True)

    def flow_join_room(self):
        conn = self.connect()
        if not conn:
            return
        try:
            send_message(conn, {"action": "list_public", "data": {}})
            resp = recv_message(conn)
            rooms = resp.get("data", [])
            print("\n=== 房間列表 ===")
            if not rooms:
                print("(目前沒有公開房間)")
                return
            for r in rooms:
                gname = r.get("game_name", "Unknown")
                # 這裡顯示 host_name 比較友善
                host_display = r.get("host_name") or r.get("host_user_id")
                print(f"ID: {r['id']} | 遊戲: {gname} | 房主: {host_display}")

            rid_str = input("\n請輸入房間 ID 加入 (或按 Ctrl+C 返回): ").strip()
            if not rid_str.isdigit():
                print("[錯誤] ID 必須是數字")
                return
            self._wait_for_game_start(
                game_name=None, is_host=False, room_id=int(rid_str))
        except KeyboardInterrupt:
            pass
        finally:
            if conn:
                conn.close()

    def _wait_for_game_start(self, game_name, is_host, room_id=None):
        conn = self.connect()
        if not conn:
            return
        actual_room_id = room_id

        try:
            if is_host:
                print(f"[系統] 建立房間中...")
                send_message(conn, {
                    "action": "create_room",
                    "data": {
                        "name": f"{self.username}'s Room",
                        "user_id": self.user_id,
                        "visibility": "public",
                        "game_name": game_name
                    }
                })
            else:
                print(f"[系統] 加入房間 {room_id} ...")
                send_message(conn, {
                    "action": "accept",
                    "data": {"room_id": room_id, "user_id": self.user_id}
                })

            resp = recv_message(conn)
            if resp["status"] != "success":
                print(f"[錯誤] {resp.get('message')}")
                return

            room_data = resp["data"]
            actual_room_id = room_data.get("id")
            print(f"[成功] 房間 ID: {actual_room_id} | 等待對戰中... (Ctrl+C 離開)")

            conn.settimeout(1.0)
            while True:
                try:
                    msg = recv_message(conn)
                except socket.timeout:
                    continue
                except Exception:
                    break

                status = msg.get("status")
                if status == "error":
                    print(f"[Server] {msg.get('message')}")
                    break

                data = msg.get("data") or {}
                if data.get("client_cmds") or data.get("host"):
                    print(f"\n[系統] 遊戲開始！")
                    target = game_name if game_name else "Tetris_Battle"
                    self._auto_launch_game(target, data)
                    break

        except KeyboardInterrupt:
            print("\n[系統] 離開房間...")
            try:
                conn.settimeout(None)
                if actual_room_id:
                    send_message(conn, {"action": "leave", "data": {
                                 "room_id": actual_room_id, "user_id": self.user_id}})
            except:
                pass
        finally:
            conn.close()

    def _auto_launch_game(self, game_name, launch_data):
        game_dir = os.path.join(self.base_dir, game_name)
        game_dir = os.path.abspath(game_dir)  # 絕對路徑
        config_path = os.path.join(game_dir, "execution.json")

        if not os.path.exists(config_path):
            print(f"[嚴重錯誤] 本地找不到 {game_name}，無法啟動。")
            return

        try:
            with open(config_path, "r") as f:
                meta = json.load(f)

            exec_conf = meta.get("execution", {}).get("client", {})
            script_rel = exec_conf.get("script")
            script_abs = os.path.join(game_dir, script_rel)

            args = [sys.executable, script_abs]
            arg_map = exec_conf.get("arguments", {})

            server_host = launch_data.get("host", self.server_addr[0])
            server_port = launch_data.get("port")

            # [修正] 這裡 role 必須是 "player"，這樣 Server 才會把你當玩家
            runtime_params = {
                "ip": server_host,
                "port": server_port,
                "user_id": self.user_id,
                "role": "player"
            }

            for k, v in runtime_params.items():
                if k in arg_map:
                    args.append(arg_map[k])
                    args.append(str(v))

            print(f"[系統] 自動啟動: {' '.join(args)}")
            subprocess.Popen(args, cwd=game_dir,
                             creationflags=subprocess.CREATE_NEW_CONSOLE)

        except Exception as e:
            print(f"[錯誤] 啟動失敗: {e}")

    def run(self):
        # 第一層：Auth Loop
        if not self.auth_loop():
            return

        # 第二層：Main Loop
        while True:
            print(f"\n=== {self.username} 的大廳 ===")
            print("1. 瀏覽商城")
            print("2. 下載遊戲")
            print("3. 建立房間")
            print("4. 加入房間")
            print("5. 我的遊戲庫")
            print("0. 離開")

            choice = self._get_input("請選擇: ")

            if choice == 1:
                self.fetch_store_list()
            elif choice == 2:
                self.flow_download()
            elif choice == 3:
                self.flow_create_room()
            elif choice == 4:
                self.flow_join_room()
            elif choice == 5:
                games = self.get_local_games()
                print(f"\n已下載: {games if games else '(無)'}")
            elif choice == 0:
                pass

            if choice is None:
                print("Bye!")
                break


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=10002)
    # [修改] 移除 user 參數，改用 UI 登入
    args = parser.parse_args()

    PlayerClient(args.host, args.port).run()
