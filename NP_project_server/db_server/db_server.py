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
        self.data = {
            "players": [],
            "developers": [],
            "rooms": [],
            "games": [],
            "reviews": [],
            # [新增] {username: [game_name1, game_name2, ...]}
            "play_history": {},
            "nexts": {"player": 1, "developer": 1, "room": 1}
        }
        self.load()

    # db_server/db_server.py (約 60 行附近)

    def load(self):
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    # ... (原本的載入邏輯) ...
                    for k in self.data.keys():
                        if k in loaded:
                            self.data[k] = loaded[k]

                # 確保 play_history 是字典
                if isinstance(self.data.get("play_history"), list):
                    self.data["play_history"] = {}

                # === [新增] 強制重置所有玩家為離線 ===
                for p in self.data["players"]:
                    p["online"] = False
                # ====================================

                print(
                    f"[Storage] Loaded DB from {self.db_path} (All users reset to offline)")
            except Exception as e:
                print(f"[Storage] Load error: {e}, using empty DB")
        else:
            print("[Storage] No DB file found, starting new.")
            self.save()
    
    def record_play(self, user_ids, game_name):
        with self.lock:
            for uid in user_ids:
                # 找出 username
                target = next(
                    (p for p in self.data["players"] if p["id"] == uid), None)
                if target:
                    uname = target["username"]
                    if uname not in self.data["play_history"]:
                        self.data["play_history"][uname] = []

                    if game_name not in self.data["play_history"][uname]:
                        self.data["play_history"][uname].append(game_name)
                        print(f"[History] Recorded {uname} played {game_name}")
            self.save()
            return {"status": "success"}

    def save(self):
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def _get_collection(self, role):
        if role == "developer":
            return self.data["developers"], "developer"
        return self.data["players"], "player"

    # --- Auth ---
    def register(self, username, password, role="player"):
        with self.lock:
            collection, kind = self._get_collection(role)
            for u in collection:
                if u["username"] == username:
                    return {"status": "error", "message": "Account already exists"}

            uid = self.data["nexts"][kind]
            self.data["nexts"][kind] += 1
            new_user = {
                "id": uid, "username": username, "password": password,
                "token": None, "online": False, "created_at": time.time()
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

            new_token = str(uuid.uuid4())
            target["token"] = new_token
            target["online"] = True
            self.save()
            print(f"[Auth] {role} {username} logged in.")
            return {"status": "success", "data": {"id": target["id"], "username": target["username"], "token": new_token}}

    def logout(self, username, role="player"):
        with self.lock:
            collection, _ = self._get_collection(role)
            for u in collection:
                if u["username"] == username:
                    u["online"] = False
                    self.save()
                    print(f"[Auth] {role} {username} logged out.")
                    return {"status": "success", "message": "Logged out"}
            return {"status": "error", "message": "User not found"}

    def user_list_online(self):
        return [{"id": u["id"], "username": u["username"]} for u in self.data["players"] if u.get("online")]

    # --- 遊戲管理 ---
    def game_upsert(self, meta, file_path):
        with self.lock:
            name = meta.get("game_name")
            target = next(
                (g for g in self.data["games"] if g["name"] == name), None)

            # [修正 D2] 檢查作者權限
            if target:
                if target.get("author") != meta.get("author"):
                    print(
                        f"[Storage] Permission denied: {meta.get('author')} tried to overwrite {name}")
                    return {"status": "error", "message": "Permission denied: You are not the author."}
            else:
                target = {"name": name, "created_at": time.time()}
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
            return {"status": "success", "data": target}

    def game_delete(self, name, author):
        with self.lock:
            target = next(
                (g for g in self.data["games"] if g["name"] == name), None)
            if not target:
                return {"status": "error", "message": "Game not found"}
            if target.get("author") != author:
                return {"status": "error", "message": "Permission denied"}

            self.data["games"].remove(target)
            self.save()
            print(f"[Storage] Game deleted: {name} by {author}")
            return {"status": "success", "message": "Game deleted"}

    def game_list(self):
        return [{"name": g["name"], "version": g["version"], "author": g.get("author"), "description": g.get("description")} for g in self.data["games"]]

    def game_get(self, name):
        return next((g for g in self.data["games"] if g["name"] == name), None)

    # --- [新增 P4] 評論系統 ---
    def review_add(self, game_name, username, rating, comment):
        with self.lock:
            # 1. 確認遊戲存在
            if not any(g["name"] == game_name for g in self.data["games"]):
                return {"status": "error", "message": "Game not found"}

            # 2. [新增] 確認是否有遊玩紀錄
            history = self.data["play_history"].get(username, [])
            if game_name not in history:
                return {"status": "error", "message": "You must play this game before reviewing."}

            # 3. 檢查評分範圍
            if not (1 <= rating <= 5):
                return {"status": "error", "message": "Rating must be 1-5"}

            new_review = {
                "game_name": game_name,
                "username": username,
                "rating": rating,
                "comment": comment[:200],
                "created_at": time.time()
            }
            self.data["reviews"].append(new_review)
            self.save()
            print(f"[Review] {username} reviewed {game_name}: {rating}")
            return {"status": "success", "message": "Review added"}

    def review_list(self, game_name):
        # 篩選該遊戲的評論
        targets = [r for r in self.data["reviews"]
                   if r["game_name"] == game_name]
        return targets

    # --- 房間相關 ---
    # db_server.py 的 room_create 函式
    # db_server.py 的 room_create 函式
    def room_create(self, d):
        with self.lock:
            rid = self.data["nexts"]["room"]
            self.data["nexts"]["room"] += 1
            host_id = d.get("hostUserId") or d.get("user_id")
            host_name = str(host_id)
            for p in self.data["players"]:
                if p["id"] == host_id:
                    host_name = p["username"]
                    break

            # [新增] 讀取 max_players，預設為 2
            max_players = d.get("max_players", 2)

            r = {
                "id": rid,
                "name": d.get("name"),
                "host_user_id": host_id,
                "host_name": host_name,
                "status": "idle",
                "users": [host_id],
                "max_players": max_players  # 儲存人數上限
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
        data = req.get("data") or {}
        resp = None

        # ... (Auth & Game & Review & Room 路由保持不變) ...
        # 請在原本的 if/elif 結構中加入這條：

        if act == "record_play":  # [新增路由]
            resp = storage.record_play(
                data.get("user_ids"), data.get("game_name"))

        # --- 以下是原本的路由 (為了完整性列出上下文，請將這段融合進去) ---
        elif act == "auth_register":
            resp = storage.register(data.get("username"), data.get(
                "password"), data.get("role", "player"))
        elif act == "auth_login":
            resp = storage.login(data.get("username"), data.get(
                "password"), data.get("role", "player"))
        elif act == "logout":
            resp = storage.logout(data.get("username"),
                                  data.get("role", "player"))
        elif act == "game_upsert":
            resp = storage.game_upsert(data.get("meta"), data.get("file_path"))
        elif act == "game_list":
            out = storage.game_list()
            resp = {"status": "success", "data": out}
        elif act == "game_get":
            out = storage.game_get(data.get("name"))
            resp = {"status": "success", "data": out} if out else {
                "status": "error", "message": "Not found"}
        elif act == "game_delete":
            resp = storage.game_delete(
                data.get("game_name"), data.get("author"))
        elif act == "review_add":
            resp = storage.review_add(data.get("game_name"), data.get(
                "username"), data.get("rating"), data.get("comment"))
        elif act == "review_list":
            out = storage.review_list(data.get("game_name"))
            resp = {"status": "success", "data": out}
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
        elif act == "list_online":
            out = storage.user_list_online()
            resp = {"status": "success", "data": out}

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
    print(
        f"[DB] Listening on port {args.port} (Full Features) - Press Ctrl+C to stop")

    try:
        while True:
            conn, addr = srv.accept()
            t = threading.Thread(target=handle_client,
                                 args=(conn, addr, storage))
            t.daemon = True
            t.start()
    except KeyboardInterrupt:
        print("\n[DB] Shutting down...")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
