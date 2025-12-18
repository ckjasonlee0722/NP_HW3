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
            send_message(conn, {"action": "auth_register", "data": {
                         "username": user, "password": pwd, "role": "developer"}})
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
            send_message(conn, {"action": "auth_login", "data": {
                         "username": user, "password": pwd, "role": "developer"}})
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
                my_games = [g for g in games if g.get(
                    "author") == self.username]
                if not my_games:
                    print("(您尚未上架任何遊戲)")
                else:
                    for g in my_games:
                        print(
                            f"{g['name']:<20} v{g['version']:<10} {g.get('author')}")
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

    def _validate_game_config(self, base_path):
        config_path = os.path.join(base_path, "game_config.json")
        if not os.path.exists(config_path):
            return False, "找不到 game_config.json"

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            return False, f"game_config.json 格式錯誤: {e}"

        meta = config.get("meta", {})
        if not meta.get("game_name") or not meta.get("version"):
            return False, "meta 中缺少 game_name 或 version"

        execution = config.get("execution", {})
        srv = execution.get("server", {})
        srv_script = srv.get("script")
        if not srv_script:
            return False, "execution.server 缺少 script 定義"
        if not os.path.exists(os.path.join(base_path, srv_script)):
            return False, f"找不到 Server Script 檔案: {srv_script}"

        cli = execution.get("client", {})
        cli_script = cli.get("script")
        if not cli_script:
            return False, "execution.client 缺少 script 定義"
        if not os.path.exists(os.path.join(base_path, cli_script)):
            return False, f"找不到 Client Script 檔案: {cli_script}"

        return True, config

    # [新增] 版本號自動增加邏輯
    def _increment_version(self, version_str):
        try:
            parts = version_str.split('.')
            if len(parts) >= 3:
                # 1.0.0 -> 1.0.1
                parts[-1] = str(int(parts[-1]) + 1)
                return ".".join(parts)
            else:
                return version_str + ".1"
        except:
            return version_str  # 解析失敗就回傳原值

    def upload_game(self):
        path = self._get_input("\n請輸入遊戲專案路徑 (例如 .): ")
        if not path:
            path = "."  # 預設當前目錄

        if not os.path.exists(path):
            print("[錯誤] 路徑不存在")
            return

        # 1. 驗證並讀取設定檔
        valid, result = self._validate_game_config(path)
        if not valid:
            print(f"[錯誤] 驗證失敗: {result}")
            return

        config = result
        current_ver = config["meta"]["version"]

        # [新增] 詢問自動更新版本
        next_ver = self._increment_version(current_ver)
        print(f"\n目前版本: v{current_ver}")
        ask = self._get_input(f"是否自動更新版本至 v{next_ver}? (Y/n): ").lower()
        if ask != 'n':
            # 更新記憶體中的 config
            config["meta"]["version"] = next_ver
            # 寫回檔案 (這樣 zip 才會包到新版本)
            config_path = os.path.join(path, "game_config.json")
            try:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=4)
                print(f"[系統] 已更新設定檔版本為 v{next_ver}")
            except Exception as e:
                print(f"[警告] 無法寫入設定檔，將使用舊版本上傳: {e}")

        # 準備上傳資料
        meta = config.get("meta", {}).copy()
        meta["execution"] = config.get("execution", {})
        meta["author"] = self.username

        print(f"[系統] 正在打包 {meta['game_name']} v{meta['version']} ...")

        try:
            # 這裡打包時會讀取到剛剛更新過的 game_config.json
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

    def delete_game(self):
        self.list_my_games()
        name = self._get_input("\n請輸入要下架的遊戲名稱: ")
        if not name:
            return
        conn = self.connect()
        if not conn:
            return
        try:
            send_message(conn, {
                "action": "game_delete",
                "data": {"game_name": name, "author": self.username}
            })
            resp = recv_message(conn)
            if resp["status"] == "success":
                print(f"[成功] 遊戲 '{name}' 已下架")
            else:
                print(f"[失敗] {resp.get('message')}")
        finally:
            conn.close()

    def run(self):
        if not self.auth_loop():
            return
        while True:
            print(f"\n=== 開發者: {self.username} ===")
            print("1. 遊戲列表 (List Games)")
            print("2. 上架/更新遊戲 (Upload/Update)")
            print("3. 下架遊戲 (Delete)")
            print("0. 離開")
            choice = self._get_input("請選擇: ")
            if choice == "1":
                self.list_my_games()
            elif choice == "2":
                self.upload_game()
            elif choice == "3":
                self.delete_game()
            elif choice == "0" or choice is None:
                break


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=10002)
    args = parser.parse_args()
    DeveloperClient(args.host, args.port).run()
