# 🎮 Network Programming HW3 — Online Game Platform

> A Socket-based online multiplayer game platform featuring a centralized lobby system, user authentication, a game store, and multiplayer networking for **Click War** and **Tetris Battle**.
>
> *Network Programming Course — Fall 2025*

---

## 📋 Prerequisites

- **Python** 3.10 or higher
- **pygame** library (required for game rendering)
```bash
pip install pygame
```

---

## 🚀 Quick Start

> [!IMPORTANT]
> Because the server is deployed on the university's Linux workstation (`linux1`) and restricted by a firewall, this project uses **SSH Tunneling** to bypass port restrictions.
> You **must** establish the SSH tunnel before launching the client, otherwise you will not be able to connect to the game server.

### Step 1 — Establish SSH Tunneling

Open a terminal and run the following command to forward local ports for the Lobby (`33002`) and Game Servers (`33003–33005`) to the remote server.

> **Note:** Replace `<your_student_id>` with your actual linux1 login account if you are not `hslee`.
```bash
ssh -L 33002:127.0.0.1:33002 \
    -L 33003:127.0.0.1:33003 \
    -L 33004:127.0.0.1:33004 \
    -L 33005:127.0.0.1:33005 \
    hslee@linux1.cs.nycu.edu.tw
```

> **⚠️ Important:** After logging in, **keep this terminal window open**. Closing it will terminate the tunnel.

---

### Step 2 — Launch the Player Client

Open a **new** terminal window and connect to the platform:
```bash
python player_client.py --host 127.0.0.1 --port 33002
```

---

### Step 3 — Start Playing

| Step | Action |
|------|--------|
| **Register / Login** | Enter any username and password to register |
| **Game Store** | Browse and download `Click_War` or `Tetris_Battle` |
| **Create a Room** | Select a downloaded game and set player capacity (2 recommended) |
| **Join a Room** | Open another client (repeat Step 2) to join the room |

---

## 🛠️ Developer Tools

To upload new game archive files (`.zip`) to the server, use the developer client:
```bash
python developer_client.py --host 127.0.0.1 --port 33002
```

**Supported features:**
- Upload games
- Remove games
- View the current game list

---

## ⚙️ Server Deployment Info

The main servers are deployed and running on the NYCU CS workstation:

| Field | Value |
|-------|-------|
| **Host** | `linux1.cs.nycu.edu.tw` (`140.113.235.151`) |
| **Process Owner** | `hslee` |
| **Database Server** | Port `33001` |
| **Lobby Server** | Port `33002` |
| **Game Servers** | Ports `33003` – `33005` *(Fixed for Tunneling)* |

---

## 🖥️ Running a Local Server

To host the server on your local machine for development, run the following in **separate terminals**:

**1. Start the Database Server**
```bash
python db_server/db_server.py --port 33001
```

**2. Start the Lobby Server**

> **Note:** Set `--public-host` to `127.0.0.1` for local testing.
```bash
export PYTHONPATH=$PYTHONPATH:.
python lobby_server/lobby_server.py --port 33002 \
    --dbhost 127.0.0.1 --dbport 33001 \
    --public-host 127.0.0.1
```

---

## 📂 Project Structure
```
.
├── client.py               # Generic game client logic
├── server.py               # Generic game server logic
├── player_client.py        # Main entry point for players (Lobby Client)
├── developer_client.py     # Developer tool for game management
├── utils/
│   └── protocol.py         # Network protocol modules
├── downloads/              # Local storage for downloaded games
├── games/                  # Source code (Click_War, Tetris_Battle)
└── README.md
```
