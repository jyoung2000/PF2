# Build the Windows companion .exe (run ON WINDOWS in this folder):
#   powershell -ExecutionPolicy Bypass -File build_companion.ps1
# Output: dist\PromptForgeCompanion.exe (single file, no console window)
python -m pip install --upgrade pip pyinstaller
python -m pip install -r requirements.txt
python -m PyInstaller --onefile --noconsole --name PromptForgeCompanion `
  --hidden-import pystray._win32 app.py
Write-Host "`nDone → dist\PromptForgeCompanion.exe"
Write-Host "First run (pairing):  PromptForgeCompanion.exe --server http://TOWER:5643 --code 123456"
