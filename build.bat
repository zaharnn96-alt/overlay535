@echo off
chcp 65001 >nul
echo Установка зависимостей...
pip install -r requirements.txt
echo.
echo Сборка KeyOverlay.exe...
pyinstaller --onefile --noconsole --name KeyOverlay ^
  --hidden-import pynput.keyboard._win32 ^
  --hidden-import pynput._util.win32 ^
  keyoverlay.py
echo.
echo Готово! Файл: dist\KeyOverlay.exe
pause
