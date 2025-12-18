# lobby_server/lobby_server.py
from utils.protocol import send_message, recv_message, recv_file, send_file
import argparse
import socket
import threading
import os
import sys
import subprocess
import zipfile
import random
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IS_WINDOWS = os.name == 'nt'


class GameExecutor:
    def __init__(self, storage_dir="server_storage/games", run_dir="server_running"):
        self.storage_dir = storage_dir
        self.run_dir = run_dir
        os.makedirs(self.run_dir, exist_ok=True)

    def _find_free_port(self):
        target_port = 33003
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', target_port)) != 0:
                return target_port
        return 33004

    def _prepare_game_files(self, game_name, version):
        zip_path = os.path.join(self.storage_dir, game_name, f"{version}.zip")
        extract_path = os.path.join(self.run_dir, game_name, version)
        if not os.path.exists(extract_path) or not os.listdir(extract_path):
            print(f"[Executor] Extracting {game_name} v{version}...")
            if not os.path.exists(zip_path):
                raise FileNotFoundError(f"Game zip not found: {zip_path}")
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(extract_path)
        return extract_path

    def start_game_process(self, game_meta, room_id, user_ids, public_host, db_host, db_port):
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
            "port": port,
            "room_id": room_id,
            "users": ",".join(map(str, user_ids)),
            "mode": "survival",
            "drop_ms": 500,
            "lobby_host": "127.0.0.1",
            "lobby_port": 10002
        }
        for k, v in runtime_vals.items():
            if k in arg_map:
                cmd.append(arg_map[k])
                cmd.append(str(v))
        cmd.append("--public-host")
        cmd.append(public_host)
        print(f"[Executor] Launching: {' '.join(map(str, cmd))}")

        proc = subprocess.Popen(
            cmd, cwd=game_cwd,
            stdout=sys.stdout,
            stderr=sys.stderr,
            start_new_session=True
        )
        return port, proc


_executor = GameExecutor()
_room_game_map = {}
_ONLINE_CLIENTS = {}
_LOCK = threading.Lock()


def call_db(dbhost, dbport, payload):
    try:
        s = socket.create_connection((dbhost, dbport), timeout=5)
        send_message(s, payload)
        resp = recv_message(s)
        s.close()
        return resp
    except Exception as e:
        return {"status": "error", "message": str(e)}


def handle_client(conn, addr, args):
    current_user_id = None
    try:
        while True:
            req = recv_message(conn)
            if not req:
                break
            act = req.get("action")
            dat = req.get("data") or {}

            if act in ("auth_register", "auth_login", "logout", "list_online"):
                resp = call_db(args.dbhost, args.dbport, req)
                if act == "auth_login" and resp.get("status") == "success":
                    uid = resp["data"]["id"]
                    current_user_id = uid
                    with _LOCK:
                        _ONLINE_CLIENTS[uid] = conn
                    print(f"[Lobby] User {uid} logged in from {addr}")
                if act == "logout" and resp.get("status") == "success":
                    current_user_id = None
                send_message(conn, resp)

            elif act in ("game_upsert", "game_delete", "game_list"):
                resp = call_db(args.dbhost, args.dbport, req)
                send_message(conn, resp)

            elif act == "upload_game":
                meta = dat.get("meta", {})
                game_name = meta.get("game_name")
                version = meta.get("version")
                file_data = recv_file(conn)
                print(
                    f"[Lobby] Upload: {game_name} v{version} ({len(file_data)} bytes)")
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
                if game_info and os.path.exists(game_info.get("file_path", "")):
                    path = game_info["file_path"]
                    size = os.path.getsize(path)
                    with open(path, "rb") as f:
                        b = f.read()
                    send_message(conn, {"status": "success", "data": {
                        "size": size, "version": game_info["version"], "execution": game_info["execution"],
                        "min_players": game_info.get("min_players", 2), "max_players": game_info.get("max_players", 2)
                    }})
                    send_file(conn, b)
                else:
                    send_message(conn, {"status": "error",
                                 "message": "File not found"})

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
                    user_id = dat.get("user_id")
                    if user_id:
                        with _LOCK:
                            _ONLINE_CLIENTS[user_id] = conn
                    with _LOCK:
                        _room_game_map[room_id] = game_resp["data"]
                send_message(conn, resp)

            elif act == "accept":
                user_id = dat.get("user_id")
                if user_id:
                    with _LOCK:
                        _ONLINE_CLIENTS[user_id] = conn
                resp = call_db(args.dbhost, args.dbport, req)
                send_message(conn, resp)
                if resp["status"] == "success":
                    room_data = resp["data"]
                    room_id = room_data["id"]
                    users = room_data["users"]
                    max_players = room_data.get("max_players", 2)
                    if len(users) >= max_players:
                        print(
                            f"[Lobby] Room {room_id} full. Starting game server...")
                        game_meta = _room_game_map.get(room_id)
                        if not game_meta:
                            gname = room_data.get("game_name")
                            if gname:
                                g_resp = call_db(args.dbhost, args.dbport, {
                                                 "action": "game_get", "data": {"name": gname}})
                                if g_resp["status"] == "success":
                                    game_meta = g_resp["data"]
                                    with _LOCK:
                                        _room_game_map[room_id] = game_meta
                        if game_meta:
                            try:
                                port, proc = _executor.start_game_process(
                                    game_meta, room_id, users, args.public_host, args.dbhost, args.dbport)
                                time.sleep(1.5)
                                start_packet = {
                                    "status": "success", "message": "Game Started",
                                    "data": {"client_cmds": True, "host": args.public_host, "port": port, "users": users}
                                }
                                send_message(conn, start_packet)
                                for uid in users:
                                    if uid == user_id:
                                        continue
                                    with _LOCK:
                                        p_conn = _ONLINE_CLIENTS.get(uid)
                                        if p_conn:
                                            try:
                                                send_message(
                                                    p_conn, start_packet)
                                            except:
                                                pass
                            except Exception as e:
                                print(f"[Error] Start game failed: {e}")
            else:
                resp = call_db(args.dbhost, args.dbport, req)
                send_message(conn, resp)

    except Exception as e:
        print(f"[Lobby] Client error: {e}")
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
    ap.add_argument("--public-host", required=True)
    args = ap.parse_args()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", args.port))
    s.listen(20)
    print(f"[Lobby] Listening on 0.0.0.0:{args.port}")
    try:
        while True:
            c, a = s.accept()
            threading.Thread(target=handle_client, args=(
                c, a, args), daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        s.close()


if __name__ == "__main__":
    main()
