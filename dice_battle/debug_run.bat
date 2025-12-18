@echo off
cd /d "%~dp0"
title Dice Battle Launcher

echo [1/5] 正在清理舊的 Python 程序 (強制關閉)...
taskkill /F /IM python.exe >nul 2>&1
echo 清理完成！

echo.
echo [2/5] 啟動 Game Server (使用新 Port 33006)...
:: 使用 33006 避開剛才可能卡住的 33005
start "Game Server" cmd /k "python server.py --port 33006 --users 1,2,3"

echo.
echo [3/5] 等待 3 秒讓 Server 暖身...
timeout /t 3 >nul

echo.
echo [4/5] 啟動 3 位玩家...
start "Player 1" cmd /k "python client.py --host 127.0.0.1 --port 33006 --user-id 1"
timeout /t 1 >nul
start "Player 2" cmd /k "python client.py --host 127.0.0.1 --port 33006 --user-id 2"
timeout /t 1 >nul
start "Player 3" cmd /k "python client.py --host 127.0.0.1 --port 33006 --user-id 3"

echo.
echo [5/5] 全部啟動完畢！
echo 請確認是否有 "3個" 綠色遊戲視窗跳出來。
echo 如果都顯示 "Round 1 - Press SPACE!"，就可以開始點擊視窗玩了！
pause