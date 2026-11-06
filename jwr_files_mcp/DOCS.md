# JWR Dateien MCP

MCP-Server für Claude mit Dateizugriff auf **genau einen Ordner** der MyCloud:
`/media/WDMycloud/JWR Immobilien GbR` (Netzwerkspeicher mit Verwendung „Medien“).

## Sicherheit

- Zugriff nur unterhalb des freigegebenen Ordners (auch Symlinks und `..` werden geprüft).
- **Kein Löschen, kein Überschreiben.** Erledigtes wird mit `mark_done` nach `_erledigt` im selben Ordner verschoben.
- Kein offener Port: Das Add-on ist nur im internen Home-Assistant-Netz erreichbar. Von außen läuft der Zugriff über einen HA-Webhook mit 100-stelliger Zufalls-ID (Integration „JWR MCP Bridge“, installiert das Add-on selbst).
- Zweiter Schlüssel: Ist `client_key` gesetzt, verlangt die Brücke zusätzlich den Header `x-api-key` mit genau diesem Wert. Ohne ihn antwortet sie wie bei einem unbekannten Webhook. Der Schlüssel wird nicht geloggt.
- Zwischen Webhook und Add-on gilt außerdem ein internes Bearer-Token.
- Jeder Schreibzugriff steht im Add-on-Log und in `/data/audit.log`.

## Einrichtung

1. In der Konfiguration `external_url` (öffentliche HA-Adresse, nur für die Log-Anzeige) und `client_key` (100 zufällige Zeichen) setzen, dann installieren und starten.
2. Beim ersten Start installiert es die Integration und meldet „Neustart nötig“: **Home Assistant einmal neu starten**. Danach richtet sich die Brücke automatisch ein.
3. Im Add-on-Log steht die **Connector-URL**: `https://<deine-ha-adresse>/api/webhook/<100 Zeichen>`
4. In claude.ai: Anpassungen → Konnektoren → „Benutzerdefinierten Konnektor hinzufügen“ → Name „JWR Dateien“, URL eintragen, Authentifizierung „Keine Anmeldung“, unter „Request-Header“ den Namen `x-api-key` (aus der Liste wählen) mit dem Wert von `client_key` hinzufügen.

URL und Header-Schlüssel nicht weitergeben. Für eine neue URL die Option „Neue Connector-URL erzeugen“ einschalten, Add-on neu starten, Option wieder ausschalten und den Connector in claude.ai neu anlegen.

## Werkzeuge

| Werkzeug | Zweck |
|---|---|
| `list_dir`, `search`, `file_info` | Ordner auflisten, suchen, Metadaten (PDF-Seiten, SHA-256) |
| `read_text` | Text aus PDF (pdftotext) oder Textdateien |
| `render_pdf_page`, `read_image` | Seite/Bild als Bild ansehen (Scans) |
| `read_bytes` | Rohdaten als Base64, in Teilen über `offset`/`length` |
| `write_file` | neue Datei (Text/Base64); große Dateien in Teilen an `*.part` anhängen |
| `move`, `copy`, `make_dir` | verschieben/umbenennen, kopieren, Ordner anlegen – ohne Überschreiben |
| `mark_done` | nach `_erledigt` verschieben (Ersatz für Löschen) |

Pfade sind relativ zum freigegebenen Ordner, z. B. `Bestand/00_Eingang/rechnung.pdf`. Mac-Pfade wie `/Volumes/mycloud/JWR Immobilien GbR/...` werden ebenfalls verstanden.

## Fehlerbilder

- „Ordner nicht erreichbar“: MyCloud aus oder Speicher in HA nicht eingebunden (Einstellungen → System → Speicher).
- Connector meldet Fehler: Add-on-Log prüfen; nach einem Update der Integration HA neu starten.
