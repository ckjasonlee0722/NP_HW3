# utils/protocol.py
import json
import struct
import socket

# 設定最大 JSON 大小，避免惡意封包塞爆記憶體 (64KB 夠用了)
MAX_JSON_LEN = 65536


def _readn(sock: socket.socket, n: int) -> bytes:
    """從 socket 確保讀取剛好 n 個 bytes，處理 TCP 分段問題"""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed unexpectedly")
        buf.extend(chunk)
    return bytes(buf)


def send_message(sock: socket.socket, data: dict):
    """傳送 JSON 控制訊號"""
    body = json.dumps(data, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_JSON_LEN:
        raise ValueError(f"JSON message too large: {len(body)}")
    # Header: 4 bytes, Big-Endian (網路標準), 代表接下來內容的長度
    header = struct.pack("!I", len(body))
    sock.sendall(header + body)


def recv_message(sock: socket.socket) -> dict:
    """接收 JSON 控制訊號"""
    header = _readn(sock, 4)
    (length,) = struct.unpack("!I", header)

    if length > MAX_JSON_LEN:
        raise ValueError(f"Message length too large: {length}")

    body = _readn(sock, length)
    return json.loads(body.decode("utf-8"))


def send_file(sock: socket.socket, file_data: bytes):
    """傳送檔案二進位資料 (HW3 新增)"""
    # 檔案可能很大，不設上限，或者設一個合理的上限 (如 50MB)
    length = len(file_data)
    # Header 一樣用 4 bytes 表示長度
    header = struct.pack("!I", length)
    sock.sendall(header + file_data)


def recv_file(sock: socket.socket) -> bytes:
    """接收檔案二進位資料 (HW3 新增)"""
    header = _readn(sock, 4)
    (length,) = struct.unpack("!I", header)
    # 讀取全部檔案內容
    return _readn(sock, length)
