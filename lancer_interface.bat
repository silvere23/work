@echo off
rem Double-cliquez sur ce fichier pour ouvrir l'interface autopostule dans votre navigateur.
rem Gardez la fenetre noire ouverte pendant l'utilisation ; fermez-la pour arreter.
cd /d "%~dp0"
if not exist ".venv\Scripts\autopostule.exe" (
  echo Installation introuvable. Dans PowerShell, depuis ce dossier :
  echo   python -m venv .venv
  echo   .venv\Scripts\Activate.ps1
  echo   pip install -e ".[dns]"
  pause
  exit /b 1
)
".venv\Scripts\autopostule.exe" interface %*
pause
