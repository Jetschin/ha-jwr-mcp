# iCloud MCP

Claude-Connector mit **Lesezugriff auf dein iCloud Drive**. Er läuft rund um die Uhr auf Home Assistant und funktioniert in jedem Claude-Chat, auch in der App auf dem Handy und in geplanten Aufgaben.

Was Claude damit kann: Ordner auflisten, Dateien suchen, PDFs, Word, Excel und Text lesen, Scans und Fotos (auch HEIC) als Bild ansehen.
**Nicht möglich:** ändern, hochladen, verschieben, löschen.

## Sicherheit

- **Kein Apple-Passwort gespeichert.** Du gibst es nur auf der Seite „iCloud“ in der HA-Seitenleiste ein. Gespeichert wird nur die von dir per 2FA bestätigte Sitzung, und zwar in `/data/session` im Add-on.
- Die Anmeldeseite ist nur über Home Assistant (Ingress) erreichbar, also nur für angemeldete HA-Benutzer.
- Zugang für Claude wie bei *JWR Dateien MCP*: HA-Webhook mit 100-stelliger Zufalls-ID (Integration „iCloud MCP Bridge“), zusätzlich der Header-Schlüssel `x-api-key` und ein internes Token. Es wird kein Port geöffnet.

## Voraussetzung bei erweitertem Datenschutz (ADP)

Wenn du für deinen Apple-Account den **erweiterten Datenschutz** nutzt, muss auf dem iPhone unter *Einstellungen → [Dein Name] → iCloud* die Option **„Auf iCloud-Daten im Web zugreifen“** eingeschaltet sein.

## Einrichtung

1. In der Konfiguration eintragen:
   - `apple_id`: deine Apple-ID
   - `external_url`: z. B. `https://jetschin.duckdns.org`
   - `client_key`: 100 zufällige Zeichen. Nimm einen **anderen** Schlüssel als bei JWR Dateien.

   Dann das Add-on starten.
2. Beim ersten Start installiert das Add-on die Integration „iCloud MCP Bridge“ und meldet „Neustart nötig“: **Home Assistant einmal neu starten.**
3. In der Seitenleiste **iCloud** öffnen, dein Apple-Passwort eingeben und den **6-stelligen Code** von deinem iPhone bestätigen.
4. Im Add-on-Log steht die **Connector-URL**: `https://<ha-adresse>/api/webhook/<100 Zeichen>`
5. In claude.ai: *Einstellungen → Connectors → Benutzerdefinierten Connector hinzufügen*
   - Name: „iCloud“
   - URL: die Connector-URL aus dem Log
   - Authentifizierung: „Keine Anmeldung“
   - Unter „Request-Header“: `x-api-key` mit dem Wert von `client_key`

Teste es mit: *„Was liegt in meinem iCloud Drive?“*

## Wartung

- **Etwa alle 2 Monate** verlangt Apple eine neue Bestätigung. Das Add-on prüft die Sitzung alle 6 Stunden und schickt dir dann eine **Benachrichtigung in Home Assistant**. Lösung: Seite „iCloud“ öffnen und neu anmelden.
- Neue Connector-URL erzeugen: Option „Neue Connector-URL erzeugen“ einschalten, Add-on neu starten, Option wieder ausschalten und den Connector in claude.ai neu anlegen.

## Werkzeuge

| Werkzeug | Zweck |
|---|---|
| `list_dir`, `search`, `file_info` | Ordner auflisten, nach Namen oder Muster (`*.pdf`) suchen, Metadaten |
| `read_text` | PDF (Textebene), Word, Excel, Text/CSV lesen |
| `render_pdf_page`, `read_image` | Scan-Seite oder Foto (auch HEIC) als Bild |
| `read_bytes` | Rohdaten als Base64, z. B. um eine Datei mit *JWR Dateien* → `write_file` auf die MyCloud zu kopieren |
| `status` | Anmeldung prüfen |

Pfade sind relativ zum iCloud Drive, z. B. `Dokumente/Steuer/Bescheid.pdf`. Groß- und Kleinschreibung ist egal.

## Grenzen

- Pages-, Numbers- und Keynote-Dateien lassen sich nicht lesen. Exportiere sie als PDF, Word oder Excel.
- Der Connector nutzt die inoffizielle Bibliothek *pyicloud*. Wenn Apple etwas umstellt, ist ein Add-on-Update mit neuer pyicloud-Version nötig.
- Accounts mit Hardware-Sicherheitsschlüssel (statt Code) werden nicht unterstützt.
