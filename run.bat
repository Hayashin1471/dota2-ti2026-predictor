@echo off
REM ===============================================================
REM  TI 2026 Match Predictor - local launcher
REM  Cua so nay CHINH LA server. Dong no la app tat.
REM ===============================================================
setlocal
cd /d "%~dp0"
title TI 2026 Match Predictor - server

if "%DOTA_APP_CONTACT%"=="" set DOTA_APP_CONTACT=local-user@example.com

REM ---- 1. tim python -------------------------------------------
set PY=
where py >nul 2>&1 && set PY=py -3
if "%PY%"=="" ( where python >nul 2>&1 && set PY=python )
if "%PY%"=="" (
  echo.
  echo   [LOI] Khong tim thay Python trong PATH.
  echo   Cai Python 3.10+ tai https://www.python.org/downloads/
  echo   Nho tick "Add python.exe to PATH" khi cai.
  echo.
  pause
  exit /b 1
)

REM ---- 2. kiem tra thu vien ------------------------------------
%PY% -c "import fastapi, uvicorn, httpx, bs4, lxml" >nul 2>&1
if errorlevel 1 (
  echo.
  echo   Dang cai thu vien can thiet ^(chi lan dau^)...
  echo.
  %PY% -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo   [LOI] Cai thu vien that bai. Xem thong bao loi o tren.
    echo.
    pause
    exit /b 1
  )
)

REM ---- 3. thu thap du lieu lan dau -----------------------------
if not exist "data\dota_ti.sqlite" (
  echo.
  echo   Chua co du lieu - dang thu thap lan dau.
  echo   Buoc nay mat khoang 10-15 phut, chi chay MOT LAN.
  echo.
  %PY% -m backend refresh all --drafts 300
)

REM ---- 4. mo trinh duyet khi server san sang -------------------
REM  Doi den khi cong 8000 tra loi roi moi mo browser, neu khong
REM  se dinh trang "khong ket noi duoc".
start "" /b %PY% tools\open_when_ready.py http://127.0.0.1:8000

echo.
echo   ============================================================
echo     TI 2026 Match Predictor
echo     Dang chay tai:  http://127.0.0.1:8000
echo.
echo     GIU CUA SO NAY MO. Dong no la app tat.
echo     Nhan Ctrl+C de dung server.
echo   ============================================================
echo.

%PY% -m backend serve --host 127.0.0.1 --port 8000

echo.
echo   Server da dung.
pause
endlocal
