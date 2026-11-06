# Changelog

## 1.1.0
- Zweiter Schlüssel: Header `X-JWR-Key` (Option `client_key`) wird von der Brücke geprüft.
- Webhook-ID jetzt 100 Zeichen (Buchstaben/Ziffern); bestehende IDs werden einmalig ersetzt.
- Keine voreingestellte externe Adresse mehr.

## 1.0.1
- Brücke: Webhook nur mit POST/GET registrieren (HA unterstützt kein DELETE).

## 1.0.0
- Erste Version: list_dir, search, file_info, read_text, render_pdf_page, read_image, read_bytes, write_file, move, copy, make_dir, mark_done.
- Zugang über HA-Webhook (Integration „JWR MCP Bridge“), kein offener Port.
