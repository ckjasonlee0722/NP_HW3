# 🎮 Network Programming HW3 - Online Game Platform

A Socket-based online multiplayer game platform developed for the Network Programming course (Fall 2025). This platform features a centralized lobby system, user authentication, a game store, and multiplayer networking for games like *Click War* and *Tetris Battle*.

## 📋 Prerequisites
* **Python:** 3.10 or higher
* **Libraries:** `pygame` (required for game rendering)

pip install pygame
🚀 Quick Start (How to Run Client)
Because the server is deployed on the university's Linux workstation (linux1) and restricted by a firewall, this project utilizes SSH Tunneling to bypass random port restrictions.

⚠️ Crucial Step: You must establish the SSH tunnel before launching the client, otherwise, you will not be able to connect to the game server.

Step 1: Establish SSH Tunneling (建立 SSH 雙通道)
Open a terminal (Terminal / PowerShell) and execute the following command to forward the local ports for the Lobby (33002) and Game Servers (33003-33005) to the remote server.
(Note: Replace <your_student_id> with your actual linux1 login account if you are not hslee)

Bash
ssh -L 33002:127.0.0.1:33002 -L 33003:127.0.0.1:33003 -L 33004:127.0.0.1:33004 -L 33005:127.0.0.1:33005 hslee@linux1.cs.nycu.edu.tw
Important: After successfully logging in with your password, keep this terminal window open. Closing it will terminate the connection tunnel.

Step 2: Launch the Player Client (啟動遊戲客戶端)
Open a new terminal window and connect to the platform using the local forwarded port:

Bash
python player_client.py --host 127.0.0.1 --port 33002
Step 3: Start Playing!
Register/Login: Enter any username and password to register.

Game Store: Browse and download Click_War or Tetris_Battle.

Create a Room: Select a downloaded game and set the player capacity (2 players recommended for testing).

Join a Room: Open another client (repeat Step 2) to join the newly created room.

🛠️ Developer Tools (開發者工具)
If you need to upload new game archive files (.zip) to the server, use the developer client:

python developer_client.py --host 127.0.0.1 --port 33002
Supported Features: Upload games, remove games, and view the current game list.

⚙️ Server Deployment Info
The main servers are currently deployed and running on the NYCU CS workstation:

Host: linux1.cs.nycu.edu.tw (140.113.235.151)

Process Owner: hslee

Ports:

Database Server: 33001

Lobby Server: 33002

Game Servers: 33003 - 33005 (Fixed Ports for Tunneling)

🖥️ Running a Local Server (自行架設 Server)
If you wish to host the server entirely on your local machine for development, run the following commands in separate terminals:

Bash
# 1. Start the Database Server
python db_server/db_server.py --port 33001

# 2. Start the Lobby Server
# Note: Set public-host to 127.0.0.1 for local testing
export PYTHONPATH=$PYTHONPATH:.
python lobby_server/lobby_server.py --port 33002 --dbhost 127.0.0.1 --dbport 33001 --public-host 127.0.0.1
📂 Project Structure
Plaintext
.
├── client.py               # Generic game client logic
├── server.py               # Generic game server logic
├── player_client.py        # Main entry point for players (Lobby Client)
├── developer_client.py     # Developer tool for game management
├── utils/                  # Network protocol modules
│   └── protocol.py
├── downloads/              # Local storage for downloaded games
├── games/                  # Source code for games (Click_War, Tetris_Battle)
└── README.md
