# Changelog

## 1.2.0
- Optional write access (`allow_write`): `write_file` (new files, large files in chunks), `make_dir`, `move` (move/rename)
- Overwriting and deleting stay impossible; every write is logged to `/data/audit.log`

## 1.1.0
- Standalone repository: https://github.com/Jetschin/ha-icloud-mcp
- Sign-in page and notifications in English or German (option `language`)
- Tool descriptions and messages for Claude in English
- Dark mode for the sign-in page

## 1.0.1
- Apple ID may be empty when saving the configuration

## 1.0.0
- First version: read-only iCloud Drive access (list_dir, search, file_info, read_text, render_pdf_page, read_image, read_bytes, status)
- Sign-in with 2FA via the “iCloud” page in the HA sidebar; the password is never stored
- Home Assistant notification when the Apple session needs to be renewed
