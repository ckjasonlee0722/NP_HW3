# db_server/storage.py
import json
import os
import time
import threading
from typing import Any, Dict, List, Optional


class Storage:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.Lock()
        if not os.path.exists(self.path):
            self._init_db()
        self._load()
        self._self_heal()

    def _init_db(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({
                "users": [], "rooms": [], "gamelogs": [],
                "games": [],  # HW3 新增
                "nexts": {"user": 1, "room": 1, "gamelog": 1}
            }, f, ensure_ascii=False, indent=2)

    def _load(self):
        with open(self.path, "r", encoding="utf-8") as f:
            self.db: Dict[str, Any] = json.load(f)
        self.db.setdefault("users", [])
        self.db.setdefault("rooms", [])
        self.db.setdefault("gamelogs", [])
        self.db.setdefault("games", [])  # HW3 新增
        self.db.setdefault("nexts", {"user": 1, "room": 1, "gamelog": 1})

    def save(self):
        with self.lock:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.db, f, ensure_ascii=False, indent=2)

    def _self_heal(self):
        # 簡單的 schema 修復邏輯
        if "games" not in self.db:
            self.db["games"] = []
        self.save()

    def _next_id(self, kind: str) -> int:
        nid = int(self.db["nexts"].get(kind, 1))
        self.db["nexts"][kind] = nid + 1
        return nid

    def _now(self):
        return time.time()

    # ---------- User ----------
    def user_register(self, d: Dict[str, Any]):
        with self.lock:
            email = d["email"]
            for u in self.db["users"]:
                if u["email"] == email:
                    return {"status": "error", "message": "E_DUPLICATE", "data": None}

            uid = self._next_id("user")
            new_u = {
                "id": uid,
                "name": d["name"],
                "email": email,
                "password_hash": d["passwordHash"],
                "created_at": self._now(),
                "last_login_at": None,
                "online": False
            }
            self.db["users"].append(new_u)
            self.save()
            return new_u

    def user_login(self, d: Dict[str, Any]):
        with self.lock:
            email = d["email"]
            pw = d["passwordHash"]
            for u in self.db["users"]:
                if u["email"] == email:
                    if u["password_hash"] == pw:
                        u["last_login_at"] = self._now()
                        u["online"] = True
                        self.save()
                        return u
            return None

    def user_logout(self, d: Dict[str, Any]):
        with self.lock:
            uid = d.get("id")
            for u in self.db["users"]:
                if u["id"] == uid:
                    u["online"] = False
                    self.save()
                    return u
            return None

    def user_list_online(self, _=None):
        return [u for u in self.db["users"] if u.get("online")]

    # ---------- Room ----------
    def room_create(self, d: Dict[str, Any]):
        with self.lock:
            rid = self._next_id("room")
            new_r = {
                "id": rid,
                "name": d["name"],
                "host_user_id": d["hostUserId"],
                "visibility": d.get("visibility", "public"),
                "status": "idle",
                "invites": [],
                "users": [d["hostUserId"]],
                "created_at": self._now()
            }
            self.db["rooms"].append(new_r)
            self.save()
            return new_r

    def room_list_public(self, _=None):
        """[HW3 修正] 確保這個方法名稱存在"""
        return [r for r in self.db["rooms"] if r.get("visibility", "public") == "public"]

    def _get_room(self, rid):
        for r in self.db["rooms"]:
            if r["id"] == rid:
                return r
        return None

    def room_invite(self, d: Dict[str, Any]):
        with self.lock:
            rid = d["roomId"]
            target = d["toUserId"]
            r = self._get_room(rid)
            if r and target not in r["invites"]:
                r["invites"].append(target)
                self.save()

    def room_accept(self, d: Dict[str, Any]):
        with self.lock:
            rid = d["roomId"]
            uid = d["userId"]
            r = self._get_room(rid)
            if r:
                if uid not in r["users"]:
                    r["users"].append(uid)
                if uid in r["invites"]:
                    r["invites"].remove(uid)
                self.save()

    def room_leave(self, d: Dict[str, Any]):
        with self.lock:
            rid = d["roomId"]
            uid = d["userId"]
            r = self._get_room(rid)
            if r and uid in r["users"]:
                r["users"].remove(uid)
                self.save()
                return r
            return None

    def room_set_status(self, d: Dict[str, Any]):
        with self.lock:
            rid = d["roomId"]
            st = d["status"]
            r = self._get_room(rid)
            if r:
                r["status"] = st
                self.save()

    # ---------- GameLog ----------
    def gamelog_create(self, d: Dict[str, Any]):
        with self.lock:
            mid = self._next_id("gamelog")
            new_gl = {
                "matchId": mid,
                "roomId": d["roomId"],
                "users": d["users"],
                "startAt": self._now(),
                "endAt": None,
                "results": {}
            }
            self.db["gamelogs"].append(new_gl)
            self.save()
            return new_gl

    def gamelog_finish(self, d: Dict[str, Any]):
        with self.lock:
            mid = d["matchId"]
            res = d["results"]
            for gl in self.db["gamelogs"]:
                if gl["matchId"] == mid:
                    gl["endAt"] = self._now()
                    gl["results"] = res
                    self.save()
                    break

    def gamelog_query(self, d: Dict[str, Any]):
        limit = d.get("limit", 10)
        rid = d.get("roomId")
        uid = d.get("userId")

        # 簡單過濾
        out = []
        # 從最新的開始找 (倒序)
        for gl in reversed(self.db["gamelogs"]):
            if rid is not None and gl["roomId"] != rid:
                continue
            if uid is not None and uid not in gl["users"]:
                continue
            out.append(gl)
            if len(out) >= limit:
                break
        return out

    def _get_gamelog(self, mid):
        for gl in self.db["gamelogs"]:
            if gl["matchId"] == mid:
                return gl
        return None

    # ---------- Game (HW3 新增功能) ----------
    def game_upsert(self, meta: Dict[str, Any], file_path: str):
        """
        上架或更新遊戲。
        meta: 來自 game_config.json 的 meta 區塊
        file_path: 檔案在 Server 上的相對路徑
        """
        with self.lock:
            name = meta.get("game_name")
            version = meta.get("version")

            # 檢查是否已存在 (更新舊遊戲)
            target = None
            for g in self.db["games"]:
                if g["name"] == name:
                    target = g
                    break

            if not target:
                # 新遊戲
                target = {
                    "name": name,
                    "author": meta.get("author", "unknown"),
                    "created_at": self._now()
                }
                self.db["games"].append(target)

            # 更新版本資訊
            target["version"] = version
            target["description"] = meta.get("description", "")
            target["min_players"] = meta.get("min_players", 1)
            target["max_players"] = meta.get("max_players", 4)
            target["file_path"] = file_path  # 重要：儲存檔案位置
            target["execution"] = meta.get("execution", {})  # 重要：儲存啟動參數
            target["updated_at"] = self._now()

            self.save()
            return target

    def game_list(self):
        """列出所有上架遊戲 (摘要)"""
        return [
            {
                "name": g["name"],
                "version": g["version"],
                "description": g.get("description", ""),
                "author": g.get("author")
            }
            for g in self.db["games"]
        ]

    def game_get(self, name: str):
        """取得特定遊戲的詳細資訊"""
        for g in self.db["games"]:
            if g["name"] == name:
                return g
        return None
