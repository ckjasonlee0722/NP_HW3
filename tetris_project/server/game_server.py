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

# 允許從套件外相對匯入（保持你原有結構）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from tetris_engine import (
        TetrisEngine, rle_encode_board,
        EngineSnapshot, GravityPlan, make_bag_rng
    )
except Exception:
    # 若以套件形式執行
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
        self.engines: List[TetrisEngine] = [TetrisEngine(
            bag_rng=rng()), TetrisEngine(bag_rng=rng())]
        self.lines_total = [0, 0]
        self.scores = [0, 0]
        self.levels = [1, 1]
        self.gravity = GravityPlan(mode="fixed", drop_ms=drop_ms)

    def apply_input(self, side: int, action: str):
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
        for i in (0, 1):
            eng = self.engines[i]
            if eng.top_out:
                continue
            cleared, score_delta = eng.gravity_step()
            self.scores[i] += score_delta
            self.lines_total[i] += cleared

    def check_game_over(self, now: float):
        if self.mode == "survival":
            p1_out = self.engines[0].top_out
            p2_out = self.engines[1].top_out
            if p1_out or p2_out:
                self.over = True
                if p1_out and p2_out:
                    self.winner, self.reason = "draw", "both topped"
                elif p1_out:
                    self.winner, self.reason = "P2", "P1 topped"
                else:
                    self.winner, self.reason = "P1", "P2 topped"
        elif self.mode == "timed":
            if self.start_ts is None:
                self.start_ts = now
            if now - self.start_ts >= self.timed_seconds:
                self.over = True
                l1, l2 = self.lines_total[0], self.lines_total[1]
                if l1 > l2:
                    self.winner, self.reason = "P1", "more lines"
                elif l2 > l1:
                    self.winner, self.reason = "P2", "more lines"
                else:
                    s1, s2 = self.scores[0], self.scores[1]
                    if s1 > s2:
                        self.winner, self.reason = "P1", "more score"
                    elif s2 > s1:
                        self.winner, self.reason = "P2", "more score"
                    else:
                        self.winner, self.reason = "draw", "tie"
        elif self.mode == "lines":
            t = self.target_lines
            if self.lines_total[0] >= t or self.lines_total[1] >= t:
                self.over = True
                if self.lines_total[0] > self.lines_total[1]:
                    self.winner, self.reason = "P1", "reach target lines"
                elif self.lines_total[1] > self.lines_total[0]:
                    self.winner, self.reason = "P2", "reach target lines"
                else:
                    self.winner, self.reason = "draw", "both reach target"

    def build_snapshot(self, side: int, now_ms: int) -> dict:
        me = self.engines[side]
        opp = self.engines[1 - side]
        snap_me: EngineSnapshot = me.snapshot()
        snap_opp: EngineSnapshot = opp.snapshot(minified=False)
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
            "opponent": {
                "score": self.scores[1 - side],
                "lines": self.lines_total[1 - side],
                "boardRLE": rle_encode_board(snap_opp.board),
                "board": snap_opp.board,
                "active": snap_opp.active,
            },
            "gravityPlan": {"mode": self.gravity.mode, "dropMs": self.gravity.drop_ms},
            "at": now_ms,
        }


def accept_thread(server_sock: socket.socket, expect_users: List[int],
                  join_queue: List[Tuple], stop_flag: threading.Event):
    server_sock.listen(8)
    while not stop_flag.is_set():
        try:
            server_sock.settimeout(0.5)
            conn, addr = server_sock.accept()
        except socket.timeout:
            continue
        except Exception:
            if not stop_flag.is_set():
                raise
            break
        try:
            hello = recv_message(conn)
            if hello.get("type") != "HELLO":
                raise ClosedError("expect HELLO")
            user_id = int(hello.get("userId"))
            role = hello.get("role") or "player"
            if role == "player" and user_id not in expect_users:
                raise ClosedError("unexpected user")
            join_queue.append((conn, addr, user_id, role))
        except Exception as e:
            try:
                send_message(conn, {"type": "ERROR", "message": f"{e}"})
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass


def _pick_public_host(bind_host: str, public_host_arg: Optional[str]) -> str:
    # 1) 明確參數 > 2) 環境變數 > 3) 自動偵測對外 IP > 4) 退回綁定位址
    if public_host_arg:
        return public_host_arg
    env = os.environ.get("PUBLIC_HOST")
    if env:
        return env
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip:
            return ip
    except Exception:
        pass
    return bind_host


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0",
                        help="bind address for game server")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--users", required=True,
                        help="comma separated user ids: e.g. 1,2")
    parser.add_argument("--room-id", type=int, required=True)
    parser.add_argument(
        "--mode", choices=["survival", "timed", "lines"], default="survival")
    parser.add_argument("--drop-ms", type=int, default=500)
    parser.add_argument("--timed-seconds", type=int, default=60)
    parser.add_argument("--target-lines", type=int, default=20)
    parser.add_argument("--lobby-host", default="127.0.0.1")
    parser.add_argument("--lobby-port", type=int, default=10002)
    parser.add_argument("--seed", type=int, default=None,
                        help="PRNG seed; if omitted, server will auto-generate")
    parser.add_argument("--public-host", default=None,
                        help="hostname/IP printed in client commands")

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
            pass  # best-effort

    users = [int(x) for x in args.users.split(",")]
    if len(users) != 2:
        raise SystemExit("Need exactly two users")

    seed = args.seed if args.seed is not None else (
        int(time.time() * 1000) & 0x7FFFFFFF)
    room = GameRoom(
        users=users, mode=args.mode, drop_ms=args.drop_ms,
        timed_seconds=args.timed_seconds, target_lines=args.target_lines, seed=seed
    )

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    print(
        f"[GameServer] listening on {args.host}:{args.port} "
        f"room={args.room_id} mode={args.mode} seed={seed} dropMs={args.drop_ms}"
    )

    public_host = _pick_public_host(args.host, args.public_host)

    p1, p2 = args.users.split(",")[0], args.users.split(",")[1]
    print("\n=== paste these in two terminals ===")
    print(
        f"python -m clients.game_client --host {public_host} --port {args.port} --user-id {p1}")
    print(
        f"python -m clients.game_client --host {public_host} --port {args.port} --user-id {p2}")
    print("\n[spectator] (optional)")
    print(
        f"python -m clients.spectator_client --host {public_host} --port {args.port}")
    print("\n[server_cmd]")
    print(
        "python -m game_server.game_server "
        f"--host {args.host} --port {args.port} --users {args.users} --room-id {args.room_id} "
        f"--mode {args.mode} --drop-ms {args.drop_ms} --timed-seconds {args.timed_seconds} "
        f"--target-lines {args.target_lines} --lobby-host {args.lobby_host} --lobby-port {args.lobby_port} "
        f"--public-host {public_host}"
    )
    print()

    stop_flag = threading.Event()
    join_queue: List[Tuple] = []
    th = threading.Thread(target=accept_thread, args=(
        srv, users, join_queue, stop_flag), daemon=True)
    th.start()

    players: Dict[int, PlayerConn] = {}
    spectators: List[PlayerConn] = []

    # 等待兩位玩家接入；觀戰者可隨時進來
    while len(players) < 2:
        while join_queue:
            conn, addr, uid, role = join_queue.pop(0)
            try:
                if role == "player":
                    if uid in players:
                        send_message(
                            conn, {"type": "ERROR", "message": "duplicate user"})
                        conn.close()
                        continue
                    p = PlayerConn(conn, addr, uid, role)
                    players[uid] = p
                    role_name = "P1" if uid == users[0] else "P2"
                    send_message(conn, {
                        "type": "WELCOME",
                        "version": WELCOME_VERSION,
                        "role": role_name,
                        "seed": room.seed,
                        "bagRule": room.bag_rule,
                        "gravityPlan": {"mode": room.gravity.mode, "dropMs": room.gravity.drop_ms}
                    })
                    print(
                        f"[GameServer] user {uid} connected as {role_name} from {addr}")
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
                    print(f"[GameServer] spectator from {addr}")
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
        time.sleep(0.05)

    side_of = {users[0]: 0, users[1]: 1}
    conns = [players[users[0]], players[users[1]]]

    # 倒數（10 秒）
    print("[GameServer] Starting countdown...")
    for c in conns + spectators:
        try:
            send_message(c.sock, {"type": "COUNTDOWN", "seconds": 10})
        except Exception:
            pass
    for countdown in range(10, 0, -1):
        print(f"[GameServer] {countdown}...")
        time.sleep(1.0)
        for c in conns + spectators:
            try:
                send_message(
                    c.sock, {"type": "COUNTDOWN", "seconds": countdown - 1})
            except Exception:
                pass
    print("[GameServer] GO!")
    for c in conns + spectators:
        try:
            send_message(c.sock, {"type": "START"})
        except Exception:
            pass

    last_drop = time.time() * 1000.0
    last_broadcast = 0.0
    SNAPSHOT_INTERVAL_MS = 60.0

    for i in (0, 1):
        room.engines[i].spawn_if_needed()

    while not room.over:
        now = time.time()
        now_ms = int(now * 1000)

        # 處理玩家/觀戰者訊息
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
                except Exception:
                    who = None
                    for idx, pc in enumerate(conns):
                        if pc.sock is rs:
                            who = idx
                            pc.close()
                    if who is not None and not room.over:
                        room.over = True
                        room.winner = "P2" if who == 0 else "P1"
                        room.reason = "opponent disconnected"
                    continue

                if msg.get("type") == "INPUT":
                    uid = int(msg.get("userId"))
                    action = msg.get("action")
                    if uid in side_of:
                        room.apply_input(side_of[uid], action)

        # 重力下落
        if now_ms - last_drop >= room.drop_ms:
            room.tick_drop(now_ms)
            last_drop = now_ms

        # 週期性廣播 SNAPSHOT
        if now_ms - last_broadcast >= SNAPSHOT_INTERVAL_MS:
            for idx, pc in enumerate(conns):
                if pc.alive:
                    snap = room.build_snapshot(idx, now_ms)
                    send_message(pc.sock, snap)
            for sp in spectators:
                if sp.alive:
                    snap = room.build_snapshot(0, now_ms)  # 觀戰者看 P1 視角
                    send_message(sp.sock, snap)
            last_broadcast = now_ms

        # 判定結束
        room.check_game_over(now)
        time.sleep(0.005)

    # 結果封包
    result = {
        "type": "GAME_OVER",
        "winner": room.winner,
        "reason": room.reason,
        "score": {"P1": room.scores[0], "P2": room.scores[1]},
        "lines": {"P1": room.lines_total[0], "P2": room.lines_total[1]},
    }

    # 廣播結果
    for pc in conns + spectators:
        if pc.alive:
            try:
                send_message(pc.sock, result)
            except Exception:
                pass

    # 回報 Lobby
    report_to_lobby(result)

    time.sleep(2.5)

    for pc in conns + spectators:
        pc.close()
    # 關閉監聽
    try:
        srv.close()
    except Exception:
        pass
    print(f"[GameServer] over winner={room.winner} reason={room.reason}")


if __name__ == "__main__":
    main()
