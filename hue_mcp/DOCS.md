# Hue MCP

Claude-Connector für deine **Philips Hue Bridge**. Claude kann damit direkt in der Bridge (also auch in der Hue App sichtbar):

- Lampen und Zubehör umbenennen
- Lampen in andere Räume verschieben, Räume und Zonen anlegen, umbenennen, ändern
- Szenen auflisten, aktivieren, aus dem aktuellen Licht neu anlegen
- nach neuen Lampen suchen, eine Lampe blinken lassen, ausgetauschte alte Lampen entfernen

Zusammen mit dem Home-Assistant-Connector kann Claude so Namen und Räume in Hue und Home Assistant gleich halten.

## Sicherheit

- Die App spricht nur im Heimnetz mit der Bridge (lokale API, kein Hue-Cloud-Konto nötig).
- Zugang für Claude wie bei *JWR Dateien MCP* und *iCloud MCP*: HA-Webhook mit 100-stelliger Zufalls-ID (Integration „Hue MCP Bridge“), zusätzlich der Header-Schlüssel `x-api-key` und ein internes Token. Es wird kein Port geöffnet.
- Löschen (Geräte, Räume, Zonen, Szenen) fragt Claude immer erst im Chat nach. Mit der Option `allow_delete: false` ist Löschen ganz abgeschaltet.
- Jede Änderung steht im App-Log und in `/data/audit.log`.

## Einrichtung

1. In der Konfiguration eintragen:
   - `bridge_host`: IP der Hue Bridge (leer = automatisch suchen)
   - `external_url`: z. B. `https://jetschin.duckdns.org`
   - `client_key`: 100 zufällige Zeichen, **ein anderer** als bei den anderen Connectoren

   Dann die App starten.
2. Beim ersten Start installiert die App die Integration „Hue MCP Bridge“ und meldet „Neustart nötig“: **Home Assistant einmal neu starten.**
3. **Den runden Knopf oben auf der Hue Bridge drücken.** Die App koppelt sich innerhalb weniger Sekunden selbst und meldet „Hue MCP gekoppelt“.
4. Im App-Log steht die **Connector-URL**: `https://<ha-adresse>/api/webhook/<100 Zeichen>`
5. In claude.ai: *Einstellungen → Connectors → Benutzerdefinierten Connector hinzufügen*
   - Name: „Hue“
   - URL: die Connector-URL aus dem Log
   - Authentifizierung: „Keine Anmeldung“
   - Unter „Request-Header“: `x-api-key` mit dem Wert von `client_key`

Teste es mit: *„Welche Lampen hängen in welchem Raum?“*

## Werkzeuge

| Werkzeug | Zweck |
|---|---|
| `status`, `pair` | Verbindung prüfen, mit der Bridge koppeln |
| `list_devices`, `list_groups`, `list_scenes` | Geräte (mit Raum, Zonen, Erreichbarkeit), Räume/Zonen, Szenen |
| `rename_device`, `identify` | umbenennen, Lampe blinken lassen |
| `move_device`, `create_group`, `update_group` | Räume und Zonen bearbeiten |
| `activate_scene`, `create_scene` | Szene aktivieren, aktuelles Licht als Szene speichern |
| `search_new_devices` | neue Lampen suchen („Lampe hinzufügen“) |
| `delete_device`, `delete_group`, `delete_scene` | entfernen (nur mit Bestätigung) |
| `api_request` | Experte: beliebige CLIP-v2-Anfrage |

## Hinweise

- Home Assistant übernimmt neue Namen und Szenen aus der Bridge automatisch, Räume aber nicht: HA-Bereiche sind getrennt. Claude passt sie auf Wunsch mit dem HA-Connector an.
- Wird die App-Kopplung in der Hue App entfernt, einfach erneut den Bridge-Knopf drücken und Claude bitten, zu koppeln.
