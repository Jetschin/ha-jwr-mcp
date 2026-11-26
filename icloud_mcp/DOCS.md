# iCloud MCP

A Claude connector for **your iCloud Drive**, running 24/7 on Home Assistant. Once added in claude.ai it works in every Claude chat, in the mobile apps and in scheduled tasks.

Claude can list folders, search files, read PDFs, Word, Excel and text files, and look at scans and photos (including HEIC).
With **`allow_write: true`** Claude can also create files and folders and move or rename items.
**Never possible:** overwriting or deleting.

> Deutsche Kurzanleitung weiter unten.

## Security

- **Your Apple password is never stored.** You enter it only on the “iCloud” page in the Home Assistant sidebar. The app keeps just the session you confirmed with 2FA (in `/data/session`).
- The sign-in page is only reachable through Home Assistant ingress, so only logged-in HA users can see it.
- Claude reaches the app through a Home Assistant webhook with a 100-character random ID (integration “iCloud MCP Bridge”, installed by the app). On top of that the header `x-api-key` and an internal token are required. No port is opened.

## Requirement for Advanced Data Protection

If your Apple account uses **Advanced Data Protection (ADP)**, turn on **“Access iCloud Data on the Web”** on your iPhone under *Settings → [your name] → iCloud*.

## Setup

1. In the configuration, set:
   - `apple_id`: your Apple ID
   - `language`: `en` or `de`, for the sign-in page and notifications
   - `allow_write`: `true` if Claude may create, move and rename files (default `false`)
   - `external_url`: your public HA address, e.g. `https://myhome.duckdns.org`
   - `client_key`: 100 random characters

   Then start the app.
2. On first start the app installs the integration “iCloud MCP Bridge” and shows a notification asking for a restart: **restart Home Assistant once.**
3. Open **iCloud** in the sidebar, enter your Apple password and confirm the **6-digit code** from your iPhone.
4. The app log shows the **connector URL**: `https://<your-ha-address>/api/webhook/<100 characters>`
5. In claude.ai, go to *Settings → Connectors → Add custom connector* and enter:
   - Name: “iCloud”
   - URL: the connector URL from the log
   - Authentication: none
   - Under “Request headers”: `x-api-key` with the value of `client_key`

Try it: *“What's in my iCloud Drive?”*

## Maintenance

- **About every two months** Apple asks for a new confirmation. The app checks the session every 6 hours and sends a **Home Assistant notification** when that happens. Open the “iCloud” page and sign in again.
- **New connector URL:** switch on “Generate new connector URL”, restart the app, switch the option off again and re-create the connector in claude.ai.

## Tools

| Tool | Purpose |
|---|---|
| `list_dir`, `search`, `file_info` | List folders, search by name or glob (`*.pdf`), metadata |
| `read_text` | Read PDF (text layer), Word, Excel, text/CSV |
| `render_pdf_page`, `read_image` | Look at a scanned page or photo (incl. HEIC) as an image |
| `read_bytes` | Raw content as Base64, e.g. to copy a file to another file connector |
| `status` | Check the sign-in |
| `write_file` | Create a new file (text or Base64; large files in chunks) – only with `allow_write` |
| `make_dir` | Create folders – only with `allow_write` |
| `move` | Move and/or rename – only with `allow_write` |

Every write is logged to `/data/audit.log` and the app log.

Paths are relative to iCloud Drive, e.g. `Documents/Taxes/notice.pdf`. Case does not matter.

## Limitations

- Pages, Numbers and Keynote files cannot be read. Export them as PDF, Word or Excel.
- The app uses the unofficial library [pyicloud](https://github.com/timlaing/pyicloud). If Apple changes its web interface, an app update with a newer pyicloud may be needed.
- Accounts that require a hardware security key instead of a code are not supported.
- This project is not affiliated with or endorsed by Apple or Anthropic.

---

## Deutsch – Kurzanleitung

1. **Konfiguration ausfüllen und App starten:**
   - `apple_id`: deine Apple-ID
   - `language: de`
   - `allow_write: true`, wenn Claude Dateien anlegen, verschieben und umbenennen darf. Überschreiben und Löschen gehen nie.
   - `external_url`: deine öffentliche HA-Adresse
   - `client_key`: 100 zufällige Zeichen
2. **Home Assistant einmal neu starten**, wenn die Benachrichtigung „Neustart nötig“ erscheint.
3. **Anmelden:** In der Seitenleiste **iCloud** öffnen, dein Apple-Passwort eingeben und den 6-stelligen Code vom iPhone bestätigen. Das Passwort wird nicht gespeichert.
4. **Connector-URL kopieren:** Sie steht im Log der App.
5. **In claude.ai verbinden:** *Einstellungen → Connectors → Benutzerdefinierten Connector hinzufügen*. Dort die URL eintragen, Authentifizierung „Keine Anmeldung“ wählen und unter „Request-Header“ `x-api-key` mit dem Wert von `client_key` eintragen.

Etwa alle zwei Monate will Apple eine neue Bestätigung. Du bekommst dann eine Benachrichtigung in Home Assistant und meldest dich auf der Seite „iCloud“ neu an.

Wenn du den erweiterten Datenschutz (ADP) nutzt, muss auf dem iPhone „Auf iCloud-Daten im Web zugreifen“ eingeschaltet sein.
