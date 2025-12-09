# Windows-Build: Einzel-Exe

Schritte, um Backend **und** gebaute Frontend-App in eine einzige `.exe` zu packen, die lokal laeuft und automatisch den Browser oeffnet.

## Voraussetzungen
- Windows, PowerShell
- Python 3.10+ (inkl. `pip`), Node.js 18+
- Google Chrome + passender ChromeDriver (nur noetig, wenn die Selenium-Scraper genutzt werden)

## 1) Backend-Umgebung vorbereiten
```powershell
cd "D:\Uni\ProjektChatbot\moodle_chat copy\backend"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt pyinstaller
```

## 2) Frontend bauen (Vite)
```powershell
cd "D:\Uni\ProjektChatbot\moodle_chat copy\frontend"
npm install
npm run build
```
Der Build landet in `frontend/dist` und wird vom Backend als statische Dateien mit ausgeliefert.

## 3) Exe erzeugen (PyInstaller)
```powershell
cd "D:\Uni\ProjektChatbot\moodle_chat copy\backend"
pyinstaller --onefile --name StudiBot --add-data "..\\frontend\\dist;frontend/dist" backend.py
```
Ergebnis: `backend/dist/StudiBot.exe`

Hinweise:
- Die Option `--add-data "..\\frontend\\dist;frontend/dist"` packt den Vite-Build mit ein. Bei geaendertem Projektpfad den relativen Teil anpassen.
- Falls Chrome/ChromeDriver nicht gebuendelt werden sollen, entferne die Selenium-Abhaengigkeiten aus `requirements.txt` und baue erneut.

## 4) App starten
```powershell
cd "D:\Uni\ProjektChatbot\moodle_chat copy\backend\dist"
./StudiBot.exe
```
- Startet den eingebetteten FastAPI-Server auf `http://127.0.0.1:8000` und oeffnet den Browser automatisch.
- Beim ersten Start erscheint ein Popup in der UI, um den ChatGPT-API-Key einzugeben; er wird lokal gespeichert und bei jedem Aufruf mitgesendet. In den Einstellungen gibt es einen Button zum Loeschen des Keys.

## 5) Aktualisieren
Bei Code-Aenderungen Schritt 2 und 3 erneut ausfuehren, die alte `StudiBot.exe` durch die neue ersetzen.
