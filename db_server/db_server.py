# db_server/db_server.py
import argparse
import json
import socket
import struct
import threading
import sys
import os
import time
import uuid

MAX_LEN = 65536


def _readn(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Socket closed")
        buf += chunk
    return buf


def send_message(sock, obj):
    body = json.dumps(obj, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    sock.sendall(struct.pack("!I", len(body)) + body)


def recv_message(sock):
    header = _readn(sock, 4)
    (n,) = struct.unpack("!I", header)
    if n > MAX_LEN:
        raise ValueError("Message too large")
    body = _readn(sock, n)
    return json.loads(body.decode("utf-8"))


class SimpleStorage:
    def __init__(self, db_path):
        self.db_path = db_path
        self.lock = threading.Lock()
        # [修改] 將 users 拆分為 players 和 developers
        self.data = {
            "players": [],
            "developers": [],
            "rooms": [],
            "games": [],
            "gamelogs": [],
            "nexts": {"player": 1, "developer": 1, "room": 1, "gamelog": 1}
        }
        self.load()

    def load(self):
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    # 遷移舊資料：如果舊 DB 只有 users，就把它們當作 players
                    if "users" in loaded and "players" not in loaded:
                        loaded["players"] = loaded["users"]

                    for k in self.data.keys():
                        if k in loaded:
                            self.data[k] = loaded[k]
                print(f"[Storage] Loaded DB from {self.db_path}")
            except Exception as e:
                print(f"[Storage] Load error: {e}, using empty DB")
        else:
            print("[Storage] No DB file found, starting new.")
            self.save()

    def save(self):
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # --- 帳號管理 (核心修改) ---

    def _get_collection(self, role):
        # 根據角色決定要存取哪個表
        if role == "developer":
            return self.data["developers"], "developer"
        return self.data["players"], "player"

    def register(self, username, password, role="player"):
        with self.lock:
            collection, kind = self._get_collection(role)

            # 1. 檢查帳號是否重複
            for u in collection:
                if u["username"] == username:
                    return {"status": "error", "message": "Account already exists"}

            # 2. 建立新帳號
            uid = self.data["nexts"][kind]
            self.data["nexts"][kind] += 1

            new_user = {
                "id": uid,
                "username": username,
                "password": password,  # 實務上要 Hash，作業 Demo 存明碼通常可接受
                "token": None,
                "created_at": time.time()
            }
            collection.append(new_user)
            self.save()
            print(f"[Auth] Registered {role}: {username} (ID: {uid})")
            return {"status": "success", "data": {"id": uid, "username": username}}

    def login(self, username, password, role="player"):
        with self.lock:
            collection, _ = self._get_collection(role)

            target = None
            for u in collection:
                if u["username"] == username:
                    target = u
                    break

            if not target:
                return {"status": "error", "message": "Account does not exist"}

            if target["password"] != password:
                return {"status": "error", "message": "Wrong password"}

            # 3. 處理重複登入 (產生新 Token，讓舊的無效)
            new_token = str(uuid.uuid4())
            target["token"] = new_token
            self.save()

            print(f"[Auth] {role} {username} logged in. Token: {new_token}")
            return {
                "status": "success",
                "data": {
                    "id": target["id"],
                    "username": target["username"],
                    "token": new_token
                }
            }

    # --- 遊戲相關 ---
    def game_upsert(self, meta, file_path):
        with self.lock:
            name = meta.get("game_name")
            target = next(
                (g for g in self.data["games"] if g["name"] == name), None)
            if not target:
                target = {"name": name, "created_at": time.time(
                ), "author": meta.get("author", "unknown")}
                self.data["games"].append(target)

            target["author"] = meta.get("author", "unknown")
            target["version"] = meta.get("version")
            target["description"] = meta.get("description", "")
            target["file_path"] = file_path
            target["execution"] = meta.get("execution", {})
            target["min_players"] = meta.get("min_players", 2)
            target["max_players"] = meta.get("max_players", 2)
            self.save()
            print(
                f"[Storage] Game saved: {name} v{target['version']} by {target['author']}")
            return target

    def game_list(self):
        return [{"name": g["name"], "version": g["version"], "author": g.get("author"), "description": g.get("description")} for g in self.data["games"]]

    def game_get(self, name):
        return next((g for g in self.data["games"] if g["name"] == name), None)

    # --- 房間相關 ---
    def room_create(self, d):
        with self.lock:
            rid = self.data["nexts"]["room"]
            self.data["nexts"]["room"] += 1
            host_id = d.get("hostUserId") or d.get("user_id")

            # [修正] 嘗試把 user_id 轉成 user_name 顯示比較友善 (Optional)
            host_name = str(host_id)  # 預設顯示 ID
            for p in self.data["players"]:
                if p["id"] == host_id:
                    host_name = p["username"]
                    break

            r = {
                "id": rid,
                "name": d.get("name"),
                "host_user_id": host_id,
                "host_name": host_name,  # 多存一個名字方便顯示
                "status": "idle",
                "users": [host_id]
            }
            self.data["rooms"].append(r)
            self.save()
            return r

    def room_list_public(self):
        return self.data["rooms"]

    def _get_room(self, rid):
        return next((r for r in self.data["rooms"] if r["id"] == rid), None)

    def room_accept(self, d):
        with self.lock:
            rid = d.get("roomId") or d.get("room_id")
            uid = d.get("userId") or d.get("user_id")
            r = self._get_room(rid)
            if r:
                if uid not in r["users"]:
                    r["users"].append(uid)
                self.save()
                return r
            return None

    def room_leave(self, d):
        with self.lock:
            rid = d.get("roomId") or d.get("room_id")
            uid = d.get("userId") or d.get("user_id")
            r = self._get_room(rid)
            if r and uid in r["users"]:
                r["users"].remove(uid)
                self.save()
                return r
            return None


def handle_client(conn, addr, storage):
    try:
        req = recv_message(conn)
        act = req.get("action")
        data = req.get("data")
        resp = None  # 完整回應包 (含 status)

        # ---------------- Auth (HW3 新增) ----------------
        if act == "auth_register":
            # data: {username, password, role}
            resp = storage.register(data.get("username"), data.get(
                "password"), data.get("role", "player"))

        elif act == "auth_login":
            # data: {username, password, role}
            resp = storage.login(data.get("username"), data.get(
                "password"), data.get("role", "player"))

        # ---------------- HW3 Store ----------------
        elif act == "game_upsert":
            out = storage.game_upsert(data.get("meta"), data.get("file_path"))
            resp = {"status": "success", "data": out}
        elif act == "game_list":
            out = storage.game_list()
            resp = {"status": "success", "data": out}
        elif act == "game_get":
            out = storage.game_get(data.get("name"))
            resp = {"status": "success", "data": out} if out else {
                "status": "error", "message": "Not found"}

        # ---------------- Room ----------------
        elif act == "create_room":
            out = storage.room_create(data)
            resp = {"status": "success", "data": out}
        elif act == "list_public":
            out = storage.room_list_public()
            resp = {"status": "success", "data": out}
        elif act == "accept":
            out = storage.room_accept(data)
            resp = {"status": "success", "data": out}
        elif act == "leave":
            out = storage.room_leave(data)
            resp = {"status": "success", "data": out}
        elif act == "room_get":
            out = storage._get_room(data.get("room_id"))
            resp = {"status": "success", "data": out} if out else {
                "status": "error"}

        # Fallback
        if resp is None:
            resp = {"status": "error", "message": f"Unknown action: {act}"}

        send_message(conn, resp)

    except Exception as e:
        print(f"[DB] Error: {e}")
        try:
            send_message(conn, {"status": "error", "message": str(e)})
        except:
            pass
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=10001)
    parser.add_argument("--db", default="db_clean.json")
    args = parser.parse_args()

    storage = SimpleStorage(args.db)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", args.port))
    srv.listen(5)

    srv.settimeout(1.0)
    print(
        f"[DB] Listening on port {args.port} (Auth Supported) - Press Ctrl+C to stop")

    try:
        while True:
            try:
                conn, addr = srv.accept()
                t = threading.Thread(target=handle_client,
                                     args=(conn, addr, storage))
                t.daemon = True
                t.start()
            except socket.timeout:
                continue
    except KeyboardInterrupt:
        print("\n[DB] Shutting down...")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
