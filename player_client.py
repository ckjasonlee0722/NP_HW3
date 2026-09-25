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
                    return 0
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

    # --- Auth ---
    def auth_register(self):
        print("\n=== 📝 註冊帳號 ===")
        user = input("帳號: ").strip()
        pwd = input("密碼: ").strip()
        if not user or not pwd:
            return False
        conn = self.connect()
        if not conn:
            return False
        try:
            send_message(conn, {"action": "auth_register", "data": {
                         "username": user, "password": pwd, "role": "player"}})
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
            send_message(conn, {"action": "auth_login", "data": {
                         "username": user, "password": pwd, "role": "player"}})
            resp = recv_message(conn)
            if resp["status"] == "success":
                data = resp["data"]
                self.user_id = data["id"]
                self.username = data["username"]
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
                    return True
            elif choice == 2:
                self.auth_register()
            elif choice == 0:
                return False

    # --- Game Store & Details ---

    def _get_installed_version(self, game_name):
        if not self.base_dir:
            return None
        json_path = os.path.join(self.base_dir, game_name, "execution.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    return meta.get("version")
            except:
                return None
        return None

    def flow_store(self):
        while True:
            conn = self.connect()
            if not conn:
                return
            games = []
            try:
                send_message(conn, {"action": "game_list", "data": {}})
                resp = recv_message(conn)
                if resp["status"] == "success":
                    games = resp["data"]
            finally:
                conn.close()

            if not games:
                print("\n[提示] 目前商城沒有遊戲。")
                return

            print(f"\n=== 🛒 遊戲商城 (共 {len(games)} 款) ===")
            print(f"{'No.':<4} {'Name':<20} {'Author':<10} {'Status'}")
            print("-" * 60)

            for i, g in enumerate(games):
                local_ver = self._get_installed_version(g['name'])
                server_ver = g['version']

                status_str = f"v{server_ver}"
                if local_ver:
                    if local_ver == server_ver:
                        status_str += " (已安裝)"
                    else:
                        status_str += f" (可更新: v{local_ver}->v{server_ver})"

                print(
                    f"{i+1:<4} {g['name']:<20} {g.get('author','?'):<10} {status_str}")

            print("\n輸入編號查看詳細資訊，或 '0' 返回大廳")
            idx = self._get_input("請選擇: ", len(games))
            if idx == 0:
                break

            self.show_game_details(games[idx-1])

    def show_game_details(self, game_info):
        game_name = game_info["name"]
        server_ver = game_info["version"]
        local_ver = self._get_installed_version(game_name)

        while True:
            reviews = []
            conn = self.connect()
            if conn:
                try:
                    send_message(conn, {"action": "review_list", "data": {
                                 "game_name": game_name}})
                    resp = recv_message(conn)
                    if resp["status"] == "success":
                        reviews = resp["data"]
                finally:
                    conn.close()

            print(f"\n=== 📄 遊戲詳情: {game_name} ===")
            print(f"作者: {game_info.get('author', '?')}")
            print(f"版本: {server_ver}")

            if local_ver:
                if local_ver == server_ver:
                    print(f"狀態: ✅ 已安裝最新版 (v{local_ver})")
                else:
                    print(f"狀態: ⚠️ 舊版本 (v{local_ver}) -> 建議更新")
            else:
                print(f"狀態: 未安裝")

            print(f"描述: {game_info.get('description', '無描述')}")

            if reviews:
                avg = sum(r["rating"] for r in reviews) / len(reviews)
                print(f"評分: {avg:.1f} / 5.0 ({len(reviews)} 則評論)")
                print("--- 最新評論 ---")
                for r in reviews[-3:]:
                    print(f"[{r['rating']}★] {r['username']}: {r['comment']}")
            else:
                print("評分: 暫無評分")

            print("\n1. 下載 / 更新遊戲")
            print("2. 撰寫評論")
            print("0. 返回列表")

            choice = self._get_input("請選擇: ")
            if choice == 1:
                self._do_download(game_name)
                local_ver = self._get_installed_version(game_name)
            elif choice == 2:
                self._do_review(game_name)
            elif choice == 0:
                break

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

            with open(os.path.join(install_path, "execution.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)

            print(f"[成功] 已安裝至: {install_path}")
            input("按 Enter 繼續...")
        except Exception as e:
            print(f"[錯誤] 下載失敗: {e}")
        finally:
            conn.close()

    def _do_review(self, game_name):
        print(f"\n=== ✍️ 評論: {game_name} ===")
        print("請輸入評分 (1-5):")
        rating = self._get_input("> ", 5)
        if rating == 0:
            return

        comment = input("請輸入評論內容 (限200字): ").strip()

        conn = self.connect()
        if not conn:
            return
        try:
            send_message(conn, {
                "action": "review_add",
                "data": {
                    "game_name": game_name,
                    "username": self.username,
                    "rating": rating,
                    "comment": comment
                }
            })
            resp = recv_message(conn)
            if resp["status"] == "success":
                print("[成功] 評論已送出！")
            else:
                print(f"[失敗] {resp.get('message')}")
        finally:
            conn.close()

    # --- Other Flows ---
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
        if idx == 0:
            return

        game_name = local_games[idx-1]

        min_p = 2
        max_p = 2

        config_path = os.path.join(self.base_dir, game_name, "execution.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    if "meta" in meta:
                        target_meta = meta["meta"]
                    else:
                        target_meta = meta

                    min_p = target_meta.get("min_players", 2)
                    max_p = target_meta.get("max_players", 2)
            except Exception as e:
                print(f"[警告] 讀取遊戲設定失敗，使用預設值 (2人): {e}")

        print(f"\n設定 {game_name} 遊玩人數:")
        options = []
        for p in range(min_p, max_p + 1):
            options.append(p)
            print(f"{len(options)}. {p} 人對戰")

        if not options:
            print("[錯誤] 設定檔人數範圍無效")
            return

        choice_idx = self._get_input(f"請選擇 (1-{len(options)}): ", len(options))
        if choice_idx == 0:
            return

        selected_players = options[choice_idx - 1]

        self._wait_for_game_start(
            game_name, is_host=True, max_players=selected_players)

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

            room_map = {}

            for r in rooms:
                gname = r.get("game_name", "Unknown")
                rid = r["id"]
                room_map[rid] = gname

                host_display = r.get("host_name") or r.get("host_user_id")
                cur_users = len(r.get("users", []))
                max_p = r.get("max_players", 2)
                print(
                    f"ID: {r['id']} | 遊戲: {gname} | 房主: {host_display} | 人數: {cur_users}/{max_p}")

            val = input("\n請輸入房間 ID 加入 (或按 Ctrl+C 返回): ").strip()
            if not val:
                return
            if not val.isdigit():
                print("[錯誤] ID 必須是數字")
                return

            rid = int(val)
            target_game = room_map.get(rid)

            if not target_game:
                print("[錯誤] 找不到該房間 ID 或房間已關閉")
                return

            # 檢查本地是否已安裝該遊戲
            if not self._get_installed_version(target_game):
                print(f"\n[錯誤] 你的電腦尚未安裝遊戲 '{target_game}'！")
                print("       請先至 [1. 瀏覽商城] 下載該遊戲後再嘗試加入。")
                input("按 Enter 返回...")
                return
            # ==========================================

            self._wait_for_game_start(
                game_name=target_game, is_host=False, room_id=rid)
        except KeyboardInterrupt:
            pass
        finally:
            if conn:
                conn.close()

    def _wait_for_game_start(self, game_name, is_host, room_id=None, max_players=2):
        conn = self.connect()
        if not conn:
            return
        actual_room_id = room_id
        try:
            if is_host:
                print(f"[系統] 建立 {max_players} 人房間中...")
                send_message(conn, {"action": "create_room", "data": {
                             "name": f"{self.username}'s Room",
                             "user_id": self.user_id,
                             "visibility": "public",
                             "game_name": game_name,
                             "max_players": max_players
                             }})
            else:
                print(f"[系統] 加入房間 {room_id} ...")
                send_message(conn, {"action": "accept", "data": {
                             "room_id": room_id, "user_id": self.user_id}})

            resp = recv_message(conn)
            if resp["status"] != "success":
                print(f"[錯誤] {resp.get('message')}")
                return
            room_data = resp["data"]
            actual_room_id = room_data.get("id")

            target_num = room_data.get("max_players", max_players)
            cur_num = len(room_data.get("users", []))
            print(
                f"[成功] 房間 ID: {actual_room_id} | 等待對戰中 ({cur_num}/{target_num})... (Ctrl+C 離開)")

            conn.settimeout(1.0)
            while True:
                try:
                    msg = recv_message(conn)
                except socket.timeout:
                    continue
                except Exception:
                    break

                if msg.get("type") == "FORCE_LOGOUT":
                    print(f"\n[系統] {msg.get('message')}")
                    os._exit(0)

                if msg.get("status") == "error":
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
        game_dir = os.path.abspath(game_dir)
        config_path = os.path.join(game_dir, "execution.json")

        # 設定檔或腳本缺失時先暫停，讓玩家看得到錯誤訊息
        if not os.path.exists(config_path):
            print(f"\n[嚴重錯誤] 找不到遊戲設定檔！")
            print(f"預期路徑: {config_path}")
            print("請嘗試重新下載遊戲。")
            input("按 Enter 繼續...")
            return

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                meta = json.load(f)

            if "execution" in meta and "client" in meta["execution"]:
                exec_conf = meta["execution"]["client"]
            elif "client" in meta:
                exec_conf = meta["client"]
            else:
                exec_conf = meta.get("execution", {}).get("client", {})

            script_rel = exec_conf.get("script")
            if not script_rel:
                print("[錯誤] 設定檔中找不到 client script 路徑")
                input("按 Enter 繼續...")
                return

            script_abs = os.path.join(game_dir, script_rel)

            # 檢查執行檔是否存在
            if not os.path.exists(script_abs):
                print(f"\n[嚴重錯誤] 找不到遊戲啟動腳本！")
                print(f"預期路徑: {script_abs}")
                print("可能是壓縮檔結構錯誤 (多了一層資料夾?)。")
                input("按 Enter 繼續...")
                return

            args = [sys.executable, script_abs]
            arg_map = exec_conf.get("arguments", {})

            server_host = launch_data.get("host", self.server_addr[0])
            server_port = launch_data.get("port")
            users = launch_data.get("users", [])

            my_role = "P1"
            if str(self.user_id) in [str(u) for u in users]:
                idx = [str(u) for u in users].index(str(self.user_id))
                my_role = f"P{idx+1}"

            # 同時提供 "ip" 和 "host" 以相容不同設定檔
            runtime = {
                "ip": server_host,
                "host": server_host,
                "port": server_port,
                "user_id": self.user_id,
                "role": "player"
            }

            for k, v in runtime.items():
                if k in arg_map:
                    args.append(arg_map[k])
                    args.append(str(v))

            print(f"[系統] 啟動遊戲: {game_name}")
            print(f"[DEBUG] 執行參數: {args}")

            # Windows 開新視窗執行，macOS / Linux 直接執行
            kwargs = {}
            if sys.platform == 'win32':
                kwargs['creationflags'] = subprocess.CREATE_NEW_CONSOLE

            subprocess.Popen(args, cwd=game_dir, **kwargs)

        except Exception as e:
            print(f"[錯誤] {e}")
            input("按 Enter 繼續...")

    def list_online_users(self):
        conn = self.connect()
        if not conn:
            return
        try:
            send_message(conn, {"action": "list_online", "data": {}})
            resp = recv_message(conn)
            if resp["status"] == "success":
                users = resp["data"]
                print(f"\n=== 👥 線上玩家 ({len(users)} 人) ===")
                for u in users:
                    print(f"- {u['username']} (ID: {u['id']})")
            else:
                print(f"[錯誤] {resp.get('message')}")
        finally:
            conn.close()

    def run(self):
        if not self.auth_loop():
            return
        while True:
            print(f"\n=== {self.username} 的大廳 ===")
            print("1. 瀏覽商城 (下載/評論)")
            print("2. 建立房間")
            print("3. 加入房間")
            print("4. 我的遊戲庫")
            print("5. 線上玩家")
            print("0. 離開")

            choice = self._get_input("請選擇: ")
            if choice == 1:
                self.flow_store()
            elif choice == 2:
                self.flow_create_room()
            elif choice == 3:
                self.flow_join_room()
            elif choice == 4:
                games = self.get_local_games()
                print(f"\n已下載: {games if games else '(無)'}")
            elif choice == 5:
                self.list_online_users()
            elif choice == 0:
                print("Bye!")
                conn = self.connect()
                if conn:
                    try:
                        send_message(conn, {
                            "action": "logout",
                            "data": {"username": self.username, "role": "player"}
                        })
                    except:
                        pass
                    finally:
                        conn.close()
                break


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=10002)
    args = parser.parse_args()
    PlayerClient(args.host, args.port).run()
