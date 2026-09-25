# server/game_server.py
from typing import Dict, List, Optional, Tuple
import time
import threading
import struct
import socket
import select
import random
import json
import argparse
import sys
import os

# 允許從套件外相對匯入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from tetris_engine import (
        TetrisEngine, rle_encode_board,
        EngineSnapshot, GravityPlan, make_bag_rng
    )
except Exception:
    sys.path.insert(0, os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    from game_server.tetris_engine import (
        TetrisEngine, rle_encode_board,
        EngineSnapshot, GravityPlan, make_bag_rng
    )

MAX_BODY = 65536
WELCOME_VERSION = 1


class ClosedError(Exception):
    pass


def _readn(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ClosedError("socket closed while reading")
        buf.extend(chunk)
    return bytes(buf)


def recv_message(sock: socket.socket) -> dict:
    hdr = _readn(sock, 4)
    (ln,) = struct.unpack("!I", hdr)
    if ln <= 0 or ln > MAX_BODY:
        raise ClosedError(f"invalid length {ln}")
    body = _readn(sock, ln)
    return json.loads(body.decode("utf-8"))


def send_message(sock: socket.socket, obj: dict) -> None:
    b = json.dumps(obj, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    if len(b) > MAX_BODY or len(b) == 0:
        raise ValueError("message too large or empty")
    sock.sendall(struct.pack("!I", len(b)) + b)


class PlayerConn:
    def __init__(self, sock: socket.socket, addr, user_id: int, role: str):
        self.sock = sock
        self.addr = addr
        self.user_id = user_id
        self.role = role
        self.alive = True

    def close(self):
        if self.alive:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass
            self.alive = False


class GameRoom:
    def __init__(self, users: List[int], mode: str, drop_ms: int,
                 timed_seconds: int, target_lines: int, seed: int):
        self.users = users[:]
        self.mode = mode
        self.drop_ms = drop_ms
        self.timed_seconds = timed_seconds
        self.target_lines = target_lines
        self.seed = seed
        self.bag_rule = "7bag"
        self.start_ts: Optional[float] = None
        self.over = False
        self.winner: Optional[str] = None
        self.reason = ""

        rng = make_bag_rng(seed)
        self.engines: List[TetrisEngine] = [
            TetrisEngine(bag_rng=rng()) for _ in users]

        self.lines_total = [0] * len(users)
        self.scores = [0] * len(users)
        self.levels = [1] * len(users)
        self.gravity = GravityPlan(mode="fixed", drop_ms=drop_ms)

    def apply_input(self, side: int, action: str):
        if side >= len(self.engines):
            return
        eng = self.engines[side]
        if action == "LEFT":
            eng.move(-1)
        elif action == "RIGHT":
            eng.move(+1)
        elif action == "SOFT":
            cleared, score_delta = eng.soft_drop()
            self.scores[side] += score_delta
            self.lines_total[side] += cleared
        elif action == "HARD":
            cleared, score_delta = eng.hard_drop()
            self.scores[side] += score_delta
            self.lines_total[side] += cleared
        elif action in ("CW", "CCW"):
            eng.rotate(cw=(action == "CW"))
        elif action == "HOLD":
            eng.hold()

    def tick_drop(self, now_ms: int):
        for i, eng in enumerate(self.engines):
            if eng.top_out:
                continue
            cleared, score_delta = eng.gravity_step()
            self.scores[i] += score_delta
            self.lines_total[i] += cleared

    def check_game_over(self, now: float):
        if self.mode == "survival":
            alive_indices = [i for i, eng in enumerate(
                self.engines) if not eng.top_out]

            if len(self.engines) > 1:
                # 多人模式：剩 1 人存活或全滅則結束
                if len(alive_indices) <= 1:
                    self.over = True
                    if len(alive_indices) == 1:
                        w_idx = alive_indices[0]
                        self.winner = f"P{w_idx+1}"
                        self.reason = "Last man standing"
                    else:
                        self.winner = "draw"
                        self.reason = "All topped out"
            else:
                # 單人模式：死掉就結束
                if len(alive_indices) == 0:
                    self.over = True
                    self.winner = "None"
                    self.reason = "Topped out"

        elif self.mode == "timed":
            if self.start_ts is None:
                self.start_ts = now
            if now - self.start_ts >= self.timed_seconds:
                self.over = True
                max_s = -1
                w_idx = -1
                for i, s in enumerate(self.scores):
                    if s > max_s:
                        max_s = s
                        w_idx = i
                    elif s == max_s:
                        w_idx = -1
                self.winner = f"P{w_idx+1}" if w_idx != -1 else "draw"
                self.reason = "Time's up"

    def build_snapshot(self, side: int, now_ms: int) -> dict:
        me = self.engines[side]
        snap_me = me.snapshot()

        opponents = []
        for i, eng in enumerate(self.engines):
            if i == side:
                continue
            snap_opp = eng.snapshot(minified=False)
            opponents.append({
                "userId": self.users[i],
                "side": i,
                "score": self.scores[i],
                "lines": self.lines_total[i],
                "boardRLE": rle_encode_board(snap_opp.board),
                "board": snap_opp.board,
                "active": snap_opp.active,
                "alive": not eng.top_out
            })

        return {
            "type": "SNAPSHOT",
            "tick": now_ms,
            "userId": self.users[side],
            "score": self.scores[side],
            "lines": self.lines_total[side],
            "level": self.levels[side],
            "active": snap_me.active,
            "hold": snap_me.hold,
            "next": snap_me.next3,
            "boardRLE": rle_encode_board(snap_me.board),
            "board": snap_me.board,
            "opponents": opponents,
            "gravityPlan": {"mode": self.gravity.mode, "dropMs": self.gravity.drop_ms},
            "at": now_ms,
        }


def accept_thread(server_sock, expect_users, join_queue, stop_flag):
    server_sock.listen(8)
    while not stop_flag.is_set():
        try:
            server_sock.settimeout(0.5)
            conn, addr = server_sock.accept()
        except socket.timeout:
            continue
        except:
            break

        def handle_hello(c, a):
            try:
                c.settimeout(3.0)
                hello = recv_message(c)
                c.settimeout(None)

                if hello.get("type") != "HELLO":
                    raise ClosedError("expect HELLO")

                user_id = int(hello.get("userId"))
                role = hello.get("role") or "player"

                # [修改] 寬鬆檢查：只要是原本名單上的人都接受
                if role == "player" and user_id not in expect_users:
                    # 這裡可以選擇報錯，或者印個警告就好
                    print(f"[Accept] Warning: Unexpected user {user_id}")

                join_queue.append((c, a, user_id, role))
                print(f"[Accept] Accepted user {user_id} from {a}")
            except Exception as e:
                print(f"[Accept] Error with {a}: {e}")
                try:
                    c.close()
                except:
                    pass

        threading.Thread(target=handle_hello, args=(
            conn, addr), daemon=True).start()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--users", required=True)
    parser.add_argument("--room-id", type=int, required=True)
    parser.add_argument("--mode", default="survival")
    parser.add_argument("--drop-ms", type=int, default=500)
    parser.add_argument("--timed-seconds", type=int, default=60)
    parser.add_argument("--target-lines", type=int, default=20)
    parser.add_argument("--lobby-host", default="127.0.0.1")
    parser.add_argument("--lobby-port", type=int, default=10002)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--public-host", default=None)

    args = parser.parse_args()

    def report_to_lobby(result_pkt: dict):
        if not (args.lobby_host and args.lobby_port):
            return
        try:
            s = socket.create_connection(
                (args.lobby_host, args.lobby_port), timeout=3.0)
            payload = {"action": "MATCH_RESULT", "data": {
                "room_id": args.room_id, "results": result_pkt}}
            send_message(s, payload)
            try:
                _ = recv_message(s)
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass
        except Exception:
            pass

    users = [int(x) for x in args.users.split(",")]
    seed = args.seed if args.seed is not None else (
        int(time.time() * 1000) & 0x7FFFFFFF)

    # 預先建立房間，但後面可能會因為人數不足而重建
    room = GameRoom(
        users=users, mode=args.mode, drop_ms=args.drop_ms,
        timed_seconds=args.timed_seconds, target_lines=args.target_lines, seed=seed
    )

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    print(
        f"[GameServer] listening on {args.host}:{args.port} "
        f"room={args.room_id} users={len(users)}"
    )

    stop_flag = threading.Event()
    join_queue: List[Tuple] = []
    th = threading.Thread(target=accept_thread, args=(
        srv, users, join_queue, stop_flag), daemon=True)
    th.start()

    players: Dict[int, PlayerConn] = {}
    spectators: List[PlayerConn] = []

    # === [關鍵修改] 等待玩家，但加入 10 秒逾時機制 ===
    wait_start = time.time()
    WAIT_LIMIT = 10.0  # 秒

    print(f"[GameServer] Waiting for players... (Timeout: {WAIT_LIMIT}s)")

    while len(players) < len(users):
        # 逾時檢查
        if time.time() - wait_start > WAIT_LIMIT:
            print(
                "[GameServer] ⚠️ Wait timeout! Starting game with connected players only.")
            break

        while join_queue:
            conn, addr, uid, role = join_queue.pop(0)
            try:
                if role == "player":
                    if uid in players:
                        conn.close()
                        continue
                    p = PlayerConn(conn, addr, uid, role)
                    players[uid] = p

                    # 這裡暫時先算一個 index，之後可能會變
                    idx = users.index(uid) if uid in users else len(players)-1

                    send_message(conn, {
                        "type": "WELCOME",
                        "version": WELCOME_VERSION,
                        "role": f"P{idx+1}",  # Client 可能會收到 P2，這沒關係
                        "seed": room.seed,
                        "bagRule": room.bag_rule,
                        "gravityPlan": {"mode": room.gravity.mode, "dropMs": room.gravity.drop_ms}
                    })
                    print(f"[GameServer] user {uid} connected")
                else:
                    sp = PlayerConn(conn, addr, uid, role)
                    spectators.append(sp)
                    send_message(conn, {
                        "type": "WELCOME",
                        "version": WELCOME_VERSION,
                        "role": "SPECTATOR",
                        "seed": room.seed,
                        "bagRule": room.bag_rule,
                        "gravityPlan": {"mode": room.gravity.mode, "dropMs": room.gravity.drop_ms}
                    })
                    print(f"[GameServer] spectator connected")
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
        time.sleep(0.05)

    # === [關鍵修改] 重新確認實際參與的玩家 ===
    # 過濾出真正連線的 user list
    actual_users = [u for u in users if u in players]

    # 如果原本預期的人沒來，但有不在名單上的人連進來了(例外狀況)，也加進去
    for p_id in players:
        if p_id not in actual_users:
            actual_users.append(p_id)

    if not actual_users:
        print("[GameServer] No players connected. Shutting down.")
        stop_flag.set()
        return

    # 如果人數變少了，我們必須重新建立 GameRoom
    # 否則原本的 GameRoom 會期待 2 個人，造成「1人存活 -> 直接判定勝利結束」
    if len(actual_users) != len(users):
        print(
            f"[GameServer] Re-initializing room for {len(actual_users)} players.")
        users = actual_users
        room = GameRoom(
            users=users,  # 只放入實際存在的人
            mode=args.mode,
            drop_ms=args.drop_ms,
            timed_seconds=args.timed_seconds,
            target_lines=args.target_lines,
            seed=seed
        )

    # 建立連線列表，順序必須跟 room.users (也就是 actual_users) 一致
    side_of = {u: i for i, u in enumerate(users)}
    conns = [players[u] for u in users]

    # 倒數
    print("[GameServer] Starting countdown...")
    for i in range(3, 0, -1):  # 改成 3 秒比較快
        for c in conns + spectators:
            try:
                send_message(c.sock, {"type": "COUNTDOWN", "seconds": i})
            except Exception:
                pass
        time.sleep(1.0)

    for c in conns + spectators:
        try:
            send_message(c.sock, {"type": "START"})
        except Exception:
            pass

    last_drop = time.time() * 1000.0
    last_broadcast = 0.0
    SNAPSHOT_INTERVAL_MS = 60.0

    for i in range(len(users)):
        room.engines[i].spawn_if_needed()

    while not room.over:
        now = time.time()
        now_ms = int(now * 1000)

        # Handle Inputs
        rlist = [c.sock for c in conns if c.alive] + \
            [s.sock for s in spectators if s.alive]
        if rlist:
            try:
                rl, _, _ = select.select(rlist, [], [], 0.0)
            except Exception:
                rl = []
            for rs in rl:
                try:
                    msg = recv_message(rs)
                    t = msg.get("type")
                    if t == "INPUT":
                        uid = int(msg.get("userId"))
                        act = msg.get("action")
                        if uid in side_of:
                            room.apply_input(side_of[uid], act)
                    elif t == "PLUGIN" or t == "CHAT":
                        for c in conns + spectators:
                            if c.alive:
                                try:
                                    send_message(c.sock, msg)
                                except:
                                    pass
                except Exception:
                    for idx, pc in enumerate(conns):
                        if pc.sock is rs:
                            pc.close()
                            # 斷線視為輸掉
                            room.engines[idx].top_out = True

        # Gravity
        if now_ms - last_drop >= room.drop_ms:
            room.tick_drop(now_ms)
            last_drop = now_ms

        # Snapshot
        if now_ms - last_broadcast >= SNAPSHOT_INTERVAL_MS:
            for idx, pc in enumerate(conns):
                if pc.alive:
                    snap = room.build_snapshot(idx, now_ms)
                    try:
                        send_message(pc.sock, snap)
                    except Exception:
                        pass
            last_broadcast = now_ms

        room.check_game_over(now)
        time.sleep(0.005)

    # Result
    scores_dict = {f"P{i+1}": s for i, s in enumerate(room.scores)}
    result = {
        "type": "GAME_OVER",
        "winner": room.winner,
        "reason": room.reason,
        "score": scores_dict
    }

    for pc in conns + spectators:
        if pc.alive:
            try:
                send_message(pc.sock, result)
            except Exception:
                pass

    report_to_lobby(result)
    time.sleep(2.0)
    stop_flag.set()
    try:
        srv.close()
    except Exception:
        pass
    print(f"[GameServer] Game Over. Winner: {room.winner}")


if __name__ == "__main__":
    main()
