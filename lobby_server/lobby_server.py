# lobby_server/lobby_server.py
from utils.protocol import send_message, recv_message, recv_file, send_file
import argparse
import json
import socket
import struct
import threading
import os
import sys
import subprocess
import zipfile
import random
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class GameExecutor:
    def __init__(self, storage_dir="server_storage/games", run_dir="server_running"):
        self.storage_dir = storage_dir
        self.run_dir = run_dir
        os.makedirs(self.run_dir, exist_ok=True)

    def _find_free_port(self):
        while True:
            port = random.randint(20000, 30000)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(('127.0.0.1', port)) != 0:
                    return port

    def _prepare_game_files(self, game_name, version):
        zip_path = os.path.join(self.storage_dir, game_name, f"{version}.zip")
        extract_path = os.path.join(self.run_dir, game_name, version)

        if not os.path.exists(extract_path):
            print(f"[Executor] Extracting {game_name} v{version}...")
            if not os.path.exists(zip_path):
                raise FileNotFoundError(f"Game zip not found: {zip_path}")
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(extract_path)
        return extract_path

    def start_game_process(self, game_meta, room_id, user_ids, public_ip):
        game_name = game_meta.get("name") or game_meta.get("game_name")
        version = game_meta["version"]

        game_cwd = os.path.abspath(
            self._prepare_game_files(game_name, version))

        exec_conf = game_meta.get("execution", {}).get("server", {})
        script_rel = exec_conf.get("script")
        if not script_rel:
            raise ValueError("No server script defined in config")

        script_abs = os.path.join(game_cwd, script_rel)
        port = self._find_free_port()

        cmd = [sys.executable, script_abs]
        arg_map = exec_conf.get("arguments", {})

        runtime_vals = {
            "port": port, "room_id": room_id, "users": ",".join(map(str, user_ids)),
            "mode": "survival", "drop_ms": 500
        }

        for k, v in runtime_vals.items():
            if k in arg_map:
                cmd.append(arg_map[k])
                cmd.append(str(v))

        custom_args = exec_conf.get("custom_args", {})
        for k, v in custom_args.items():
            if k == "host":
                cmd.append("--host")
                cmd.append(str(v))

        cmd.append("--public-host")
        cmd.append(public_ip)

        print(f"[Executor] Launching: {' '.join(cmd)}")
        proc = subprocess.Popen(
            cmd, cwd=game_cwd, creationflags=subprocess.CREATE_NEW_CONSOLE)
        return port, proc


_executor = GameExecutor()
_room_game_map = {}


def call_db(dbhost, dbport, payload):
    try:
        s = socket.create_connection((dbhost, dbport), timeout=5)
        send_message(s, payload)
        resp = recv_message(s)
        s.close()
        return resp
    except Exception as e:
        return {"status": "error", "message": str(e)}


_ONLINE_CLIENTS = {}
_LOCK = threading.Lock()


def handle_client(conn, addr, args):
    current_user_id = None
    try:
        while True:
            req = recv_message(conn)
            act = req.get("action")
            dat = req.get("data") or {}

            # 登入後記錄 socket
            if act == "auth_login" and current_user_id is None:
                # 這裡只是轉發，真正的 ID 要等 DB 回傳成功才知道
                # 我們稍後處理回應時再記錄
                pass

            # ---------------- Auth & General Forwarding ----------------
            if act in ("auth_register", "auth_login", "logout"):
                resp = call_db(args.dbhost, args.dbport, req)
                send_message(conn, resp)

                # 如果登入成功，記錄連線
                if act == "auth_login" and resp.get("status") == "success":
                    user_data = resp.get("data")
                    if user_data:
                        uid = user_data.get("id")
                        current_user_id = uid
                        with _LOCK:
                            _ONLINE_CLIENTS[uid] = conn
                        print(f"[Lobby] User {uid} logged in from {addr}")

            # ---------------- Game Store ----------------
            elif act == "game_upsert":
                resp = call_db(args.dbhost, args.dbport, req)
                send_message(conn, resp)

            elif act == "upload_game":
                meta = dat.get("meta", {})
                game_name = meta.get("game_name")
                version = meta.get("version")
                file_data = recv_file(conn)
                print(f"[Lobby] Recv file {game_name} size={len(file_data)}")

                save_dir = os.path.join("server_storage", "games", game_name)
                os.makedirs(save_dir, exist_ok=True)
                file_path = os.path.join(save_dir, f"{version}.zip")
                with open(file_path, "wb") as f:
                    f.write(file_data)

                call_db(args.dbhost, args.dbport, {"action": "game_upsert", "data": {
                        "meta": meta, "file_path": file_path}})
                send_message(conn, {"status": "success"})

            elif act == "download_game":
                game_name = dat.get("game_name")
                db_resp = call_db(args.dbhost, args.dbport, {
                                  "action": "game_get", "data": {"name": game_name}})
                game_info = db_resp.get("data")
                if game_info:
                    path = game_info["file_path"]
                    size = os.path.getsize(path)
                    with open(path, "rb") as f:
                        b = f.read()
                    send_message(conn, {"status": "success", "data": {
                                 "size": size, "version": game_info["version"], "execution": game_info["execution"]}})
                    send_file(conn, b)
                else:
                    send_message(
                        conn, {"status": "error", "message": "Not found"})

            elif act == "game_list":
                resp = call_db(args.dbhost, args.dbport, req)
                send_message(conn, resp)

            # ---------------- Room Management ----------------
            elif act == "create_room":
                game_name = dat.get("game_name")
                game_resp = call_db(args.dbhost, args.dbport, {
                                    "action": "game_get", "data": {"name": game_name}})
                if not game_resp.get("data"):
                    send_message(conn, {"status": "error",
                                 "message": "Unknown game"})
                    continue
                resp = call_db(args.dbhost, args.dbport, req)
                if resp["status"] == "success":
                    room_id = resp["data"]["id"]
                    with _LOCK:
                        _room_game_map[room_id] = game_resp["data"]
                send_message(conn, resp)

            elif act == "list_public":
                resp = call_db(args.dbhost, args.dbport, req)
                rooms = resp.get("data", [])
                for r in rooms:
                    rid = r["id"]
                    if rid in _room_game_map:
                        r["game_name"] = _room_game_map[rid]["name"]
                send_message(conn, {"status": "success", "data": rooms})

            elif act == "accept":
                resp = call_db(args.dbhost, args.dbport, req)
                send_message(conn, resp)
                if resp["status"] == "success":
                    room_data = resp["data"]
                    room_id = room_data["id"]
                    users = room_data["users"]
                    if len(users) == 2:
                        print(
                            f"[Lobby] Room {room_id} is full! Starting game...")
                        game_meta = _room_game_map.get(room_id)
                        if game_meta:
                            try:
                                port, proc = _executor.start_game_process(
                                    game_meta, room_id, users, args.gs_host)
                                time.sleep(1)
                                start_packet = {"status": "success", "message": "Game Started", "data": {
                                    "client_cmds": True, "host": args.gs_host, "port": port, "users": users}}
                                send_message(conn, start_packet)
                                p1_id = users[0]
                                with _LOCK:
                                    p1_conn = _ONLINE_CLIENTS.get(p1_id)
                                    if p1_conn:
                                        try:
                                            send_message(p1_conn, start_packet)
                                        except:
                                            pass
                            except Exception as e:
                                err = f"Start game failed: {e}"
                                print(f"[Error] {err}")
                                try:
                                    send_message(
                                        conn, {"status": "error", "message": err})
                                except:
                                    pass
            else:
                # 其他請求直接轉發
                resp = call_db(args.dbhost, args.dbport, req)
                send_message(conn, resp)

    except Exception as e:
        print(f"[Lobby] Client disconnect: {e}")
    finally:
        if current_user_id:
            with _LOCK:
                if current_user_id in _ONLINE_CLIENTS:
                    del _ONLINE_CLIENTS[current_user_id]
        try:
            conn.close()
        except:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=10002)
    ap.add_argument("--dbhost", default="127.0.0.1")
    ap.add_argument("--dbport", type=int, default=10001)
    ap.add_argument("--gs-host", default="127.0.0.1")
    args = ap.parse_args()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", args.port))
    s.listen(10)

    s.settimeout(1.0)
    print(f"[Lobby] Listening on {args.port} (Press Ctrl+C to stop)")

    try:
        while True:
            try:
                c, a = s.accept()
                threading.Thread(target=handle_client, args=(
                    c, a, args), daemon=True).start()
            except socket.timeout:
                continue
    except KeyboardInterrupt:
        print("\n[Lobby] Shutting down...")
    finally:
        s.close()


if __name__ == "__main__":
    main()
