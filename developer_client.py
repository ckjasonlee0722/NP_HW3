# developer_client.py
import socket
import json
import os
import zipfile
import io
import argparse
import sys
from utils.protocol import send_message, recv_message, send_file


class DeveloperClient:
    def __init__(self, host, port):
        self.server_addr = (host, port)
        self.conn = None
        self.user_id = None
        self.username = None

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

    def _get_input(self, prompt):
        try:
            return input(prompt).strip()
        except KeyboardInterrupt:
            return None

    # --- Auth ---
    def auth_register(self):
        print("\n=== 🛠️ 開發者註冊 ===")
        user = self._get_input("帳號: ")
        pwd = self._get_input("密碼: ")
        if not user or not pwd:
            return

        conn = self.connect()
        if not conn:
            return
        try:
            send_message(conn, {
                "action": "auth_register",
                "data": {"username": user, "password": pwd, "role": "developer"}
            })
            resp = recv_message(conn)
            if resp["status"] == "success":
                print(f"[成功] 註冊成功 ID: {resp['data']['id']}")
            else:
                print(f"[失敗] {resp.get('message')}")
        finally:
            conn.close()

    def auth_login(self):
        print("\n=== 🔑 開發者登入 ===")
        user = self._get_input("帳號: ")
        pwd = self._get_input("密碼: ")

        conn = self.connect()
        if not conn:
            return False
        try:
            send_message(conn, {
                "action": "auth_login",
                "data": {"username": user, "password": pwd, "role": "developer"}
            })
            resp = recv_message(conn)
            if resp["status"] == "success":
                data = resp["data"]
                self.user_id = data["id"]
                self.username = data["username"]
                print(f"[成功] 歡迎回來, Dev {self.username}")
                return True
            else:
                print(f"[失敗] {resp.get('message')}")
                return False
        finally:
            conn.close()

    def auth_loop(self):
        while True:
            print("\n=== 開發者平台 ===")
            print("1. 登入 (Login)")
            print("2. 註冊 (Register)")
            print("0. 離開 (Exit)")
            choice = self._get_input("請選擇: ")
            if choice == "1":
                if self.auth_login():
                    return True
            elif choice == "2":
                self.auth_register()
            elif choice == "0" or choice is None:
                return False

    # --- Features ---
    def list_my_games(self):
        conn = self.connect()
        if not conn:
            return
        try:
            send_message(conn, {"action": "game_list", "data": {}})
            resp = recv_message(conn)
            if resp["status"] == "success":
                games = resp["data"]
                print(f"\n=== 📦 上架遊戲列表 ===")
                print(f"{'Name':<20} {'Ver':<10} {'Author'}")
                print("-" * 40)
                for g in games:
                    mark = "*" if g.get("author") == self.username else " "
                    print(
                        f"{mark}{g['name']:<19} v{g['version']:<9} {g.get('author', '?')}")
                print("(* 代表是您上架的遊戲)")
            else:
                print(f"[失敗] {resp.get('message')}")
        finally:
            conn.close()

    def zip_directory(self, path):
        mem_file = io.BytesIO()
        with zipfile.ZipFile(mem_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if d not in (
                    '.git', '__pycache__', 'venv', '.venv')]
                for file in files:
                    if file == '.DS_Store':
                        continue
                    file_path = os.path.join(root, file)
                    archive_name = os.path.relpath(file_path, path)
                    zf.write(file_path, archive_name)
        return mem_file.getvalue()

    def upload_game(self):
        path = self._get_input("\n請輸入遊戲專案路徑 (例如 ./t): ")
        if not path or not os.path.exists(path):
            print("[錯誤] 路徑不存在")
            return

        config_path = os.path.join(path, "game_config.json")
        if not os.path.exists(config_path):
            print(f"[錯誤] 找不到 {config_path}")
            return

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            meta = config.get("meta", {}).copy()
            meta["execution"] = config.get("execution", {})
            meta["author"] = self.username

            game_name = meta.get("game_name")
            version = meta.get("version")

            print(f"[系統] 正在打包 {game_name} v{version} ...")
            zip_data = self.zip_directory(path)

            conn = self.connect()
            if not conn:
                return

            print(f"[系統] 上傳中 ({len(zip_data)} bytes)...")
            send_message(conn, {
                "action": "upload_game",
                "data": {"meta": meta, "size": len(zip_data)}
            })
            send_file(conn, zip_data)

            resp = recv_message(conn)
            if resp["status"] == "success":
                print("[成功] 遊戲上架/更新完成！")
            else:
                print(f"[失敗] {resp.get('message')}")

            conn.close()

        except Exception as e:
            print(f"[錯誤] {e}")

    def run(self):
        if not self.auth_loop():
            return

        while True:
            print(f"\n=== 開發者: {self.username} ===")
            print("1. 遊戲列表 (List Games)")
            print("2. 上架/更新遊戲 (Upload/Update)")
            print("0. 離開")

            choice = self._get_input("請選擇: ")
            if choice == "1":
                self.list_my_games()
            elif choice == "2":
                self.upload_game()
            elif choice == "0" or choice is None:
                break


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=10002)
    args = parser.parse_args()

    DeveloperClient(args.host, args.port).run()
