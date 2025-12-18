# utils/protocol.py
import struct
import json
import socket


def send_message(sock, data):
    try:
        msg = json.dumps(data, ensure_ascii=False).encode('utf-8')
        sock.sendall(struct.pack('!I', len(msg)) + msg)
    except Exception as e:
        print(f"[Protocol] Send Error: {e}")
        raise e


def recv_message(sock):
    try:
        header = _readn(sock, 4)
        if not header:
            return None
        (length,) = struct.unpack('!I', header)
        body = _readn(sock, length)
        return json.loads(body.decode('utf-8'))
    except Exception as e:
        # print(f"[Protocol] Recv Error: {e}")
        raise e


def send_file(sock, file_data):
    # 簡單傳檔協定: 長度(4 bytes) + 內容
    sock.sendall(struct.pack('!I', len(file_data)) + file_data)


def recv_file(sock):
    header = _readn(sock, 4)
    (length,) = struct.unpack('!I', header)
    return _readn(sock, length)


def _readn(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed")
        buf += chunk
    return buf
