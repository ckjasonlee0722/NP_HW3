# NP_HW3
A course I took in fall semester 2025

 Player client 連線: python player_client.py --host 127.0.0.1 --port 33002
 Developer client 連線: python developer_client.py --host 127.0.0.1 --port 33002

🎮 Network Programming HW3 - Online Game Platform
這是一個基於 Socket 的線上遊戲平台，包含大廳系統、會員機制、遊戲商城以及多款連線遊戲（Click War, Tetris Battle）。

📋 環境需求 (Prerequisites)
Python: 3.10 或更高版本

Libraries: 需要安裝 pygame (用於遊戲畫面)

Bash

pip install pygame
🚀 快速啟動 (How to Run Client)
由於伺服器部署於學校 Linux 工作站 (linux1)，且為了繞過防火牆對隨機 Port 的限制，本專案採用 SSH Tunneling 技術。

⚠️ 請務必依照以下步驟連線，否則無法進入遊戲畫面。

步驟 1：建立 SSH 雙通道 (SSH Tunneling)
請開啟一個終端機 (Terminal / PowerShell)，執行以下指令。這會將本地的 33002 (大廳) 和 33003 (遊戲固定端口) 轉發至遠端伺服器。

請將 <your_student_id> 替換為你的學號 (linux1 登入帳號)：

Bash

# 格式: ssh -L [本地Port]:[遠端IP]:[遠端Port] [帳號]@[主機]
# 注意：必須同時包含 -L 33002 和 -L 33003
ssh -L 33002:127.0.0.1:33002 -L 33003:127.0.0.1:33003 <your_student_id>@linux1.cs.nycu.edu.tw
重要提示： 輸入密碼登入成功後，請保留此視窗開啟（不要關閉），這代表連線通道已建立。

步驟 2：啟動遊戲客戶端 (Player Client)
開啟另一個 新的 終端機，執行以下指令連線至平台：

Bash

# 請連線至 127.0.0.1，SSH 通道會自動將封包轉發至學校伺服器
python player_client.py --host 127.0.0.1 --port 33002
步驟 3：開始遊玩
註冊/登入：輸入任意帳號密碼註冊。

瀏覽商城：下載 Click_War 或 Tetris_Battle。

建立房間：選擇遊戲並設定人數 (建議選擇 2 人以便測試)。

加入房間：開啟第二個 Client (重複步驟 2)，加入剛剛建立的房間。

🛠️ 開發者工具 (Developer Client)
如果您需要上傳新的遊戲檔案 (.zip) 到伺服器，請使用開發者客戶端：

Bash

python developer_client.py --host 127.0.0.1 --port 33002
支援功能：上架遊戲、下架遊戲、查看遊戲清單。

📂 專案結構 (Project Structure)
Plaintext

.
├── client.py               # 遊戲通用 Client 邏輯
├── server.py               # 遊戲通用 Server 邏輯
├── player_client.py        # 玩家大廳客戶端 (主要進入點)
├── developer_client.py     # 開發者上傳工具
├── utils/                  # 通訊協定模組 (Protocol)
│   └── protocol.py
├── downloads/              # 玩家下載的遊戲存放區
├── games/                  # 遊戲原始碼 (Click_War, Tetris_Battle)
└── README.md
⚙️ 伺服器部署資訊 (Server Deployment)
目前的伺服器已部署並運行中：

Host: linux1.cs.nycu.edu.tw (140.113.235.151)

Database Server: Port 33001

Lobby Server: Port 33002

Game Server: Port 33003 (Fixed Port for Tunneling)

Process Owner: hslee

自行架設 Server (Localhost)
若您需要自行在本地架設伺服器，請參考以下指令：

Bash

# 1. 啟動資料庫
python db_server/db_server.py --port 33001

# 2. 啟動大廳 (Linux 環境需設定 PYTHONPATH)
# 注意：本地測試時 public-host 請設為 127.0.0.1
export PYTHONPATH=$PYTHONPATH:.
python lobby_server/lobby_server.py --port 33002 --dbhost 127.0.0.1 --dbport 33001 --public-host 1

ssh -L 33002:127.0.0.1:33002 -L 33003:127.0.0.1:33003 -L 33004:127.0.0.1:33004 -L 33005:127.0.0.1:33005 hslee@linux1.cs.nycu.edu.tw
