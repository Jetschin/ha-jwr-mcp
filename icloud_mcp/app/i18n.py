"""User-facing texts (login page, Home Assistant notifications, log hints) in English and German.

Texts meant for Claude (tool descriptions, tool errors) are English only; Claude answers
in the user's language anyway.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

TEXTS: dict[str, dict[str, str]] = {
    # ---- login page
    "title": {"en": "iCloud MCP", "de": "iCloud MCP"},
    "no_apple_id": {"en": "No Apple ID configured.", "de": "Keine Apple-ID eingetragen."},
    "no_apple_id_hint": {
        "en": "Please set <b>apple_id</b> in the app configuration and restart the app.",
        "de": "Bitte in der App-Konfiguration <b>apple_id</b> setzen und die App neu starten."},
    "enter_code": {
        "en": "Apple sent a verification code to your devices. Please enter the <b>6-digit code</b>:",
        "de": "Apple hat einen Bestätigungscode an deine Geräte gesendet. Bitte den "
              "<b>6-stelligen Code</b> eingeben:"},
    "confirm": {"en": "Verify", "de": "Bestätigen"},
    "cancel": {"en": "Cancel", "de": "Abbrechen"},
    "connected": {"en": "✓ Connected to {account}", "de": "✓ Verbunden mit {account}"},
    "renew_note": {
        "en": "Apple asks for a new confirmation about every two months. You will get a "
              "Home Assistant notification when that happens.",
        "de": "Apple verlangt etwa alle zwei Monate eine neue Bestätigung. Du bekommst dann "
              "eine Benachrichtigung in Home Assistant."},
    "logout": {"en": "Sign out", "de": "Abmelden"},
    "apple_id": {"en": "Apple ID", "de": "Apple-ID"},
    "password": {"en": "Apple password", "de": "Apple-Passwort"},
    "login": {"en": "Sign in", "de": "Anmelden"},
    "pw_note": {
        "en": "The password is only sent to Apple to sign in and is never stored. "
              "Only the confirmed session is kept.",
        "de": "Das Passwort wird nur für die Anmeldung an Apple gesendet und nicht gespeichert. "
              "Gespeichert wird nur die bestätigte Sitzung."},
    "need_password": {"en": "Please enter your password.", "de": "Bitte das Passwort eingeben."},
    "signed_in": {"en": "Signed in.", "de": "Angemeldet."},
    "signed_in_claude": {
        "en": "Signed in – Claude can now read your iCloud Drive.",
        "de": "Angemeldet – Claude kann jetzt auf dein iCloud Drive zugreifen."},
    "signed_out": {"en": "Signed out.", "de": "Abgemeldet."},
    "not_signed_in": {"en": "Not signed in", "de": "Nicht angemeldet"},
    "sign_in_required": {"en": "Sign-in required", "de": "Anmeldung erforderlich"},
    "unreachable": {"en": "iCloud not reachable: {err}", "de": "iCloud nicht erreichbar: {err}"},
    # ---- login results
    "err_locked": {
        "en": "Apple account is locked. Please unlock it at iforgot.apple.com.",
        "de": "Apple-Account ist gesperrt. Bitte unter iforgot.apple.com entsperren."},
    "err_bad_login": {"en": "Wrong Apple ID or password.", "de": "Apple-ID oder Passwort falsch."},
    "err_login": {"en": "Sign-in failed ({err}).", "de": "Anmeldung fehlgeschlagen ({err})."},
    "err_2sa": {
        "en": "Your account uses the old two-step verification, which is not supported.",
        "de": "Dein Account nutzt die alte zweistufige Bestätigung – wird nicht unterstützt."},
    "err_key": {
        "en": "Your account requires a hardware security key. That is not supported here.",
        "de": "Dein Account verlangt einen Hardware-Sicherheitsschlüssel. Das geht hier nicht."},
    "err_no_phone": {
        "en": "No trusted phone number in the Apple account.",
        "de": "Keine vertrauenswürdige Telefonnummer im Apple-Account."},
    "err_no_pending": {"en": "Please enter the password first.", "de": "Bitte zuerst das Passwort eingeben."},
    "err_code_len": {"en": "The code has 6 digits.", "de": "Der Code hat 6 Ziffern."},
    "err_code": {"en": "Invalid code. Please try again.", "de": "Code ungültig. Bitte erneut eingeben."},
    # ---- notifications
    "n_login_title": {"en": "iCloud MCP: sign in again", "de": "iCloud MCP: Anmeldung erneuern"},
    "n_login_msg": {
        "en": "Claude currently cannot read your iCloud Drive. Open **iCloud** in the sidebar and "
              "sign in again with password and 2FA code.",
        "de": "Claude kann gerade nicht auf dein iCloud Drive zugreifen. Bitte in der Seitenleiste "
              "**iCloud** öffnen und mit Passwort und 2FA-Code neu anmelden."},
    "n_restart_title": {"en": "iCloud MCP: restart required", "de": "iCloud MCP: Neustart nötig"},
    "n_restart_msg": {
        "en": "The app installed the integration “iCloud MCP Bridge”. Please restart Home Assistant "
              "once (Settings → System → Restart). The bridge then sets itself up.",
        "de": "Die App hat die Integration „iCloud MCP Bridge“ installiert. Bitte Home Assistant "
              "einmal neu starten (Einstellungen → System → Neu starten). Danach richtet sich die "
              "Brücke automatisch ein."},
    "n_updated_msg": {
        "en": "The bridge integration was updated. Please restart Home Assistant "
              "(Settings → System → Restart).",
        "de": "Die Brücken-Integration wurde aktualisiert. Bitte Home Assistant neu starten "
              "(Einstellungen → System → Neu starten)."},
}


def _language() -> str:
    lang = os.environ.get("ICLOUD_LANGUAGE")
    if not lang:
        p = Path(os.environ.get("ICLOUD_OPTIONS", "/data/options.json"))
        try:
            lang = json.loads(p.read_text()).get("language")
        except (OSError, ValueError):
            lang = None
    return lang if lang in ("en", "de") else "en"


LANG = _language()


def t(key: str, **kw) -> str:
    entry = TEXTS[key]
    return entry.get(LANG, entry["en"]).format(**kw)
