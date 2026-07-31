# OBS Tournament Overlay

A Flask server that serves browser-source overlays for OBS. It polls a Google Sheet every 15 seconds and exposes the data to HTML overlay pages (leaderboard, kill stats, placement, etc.).

## Stack

- **Python 3.11** + **Flask**
- Google Sheets API v4 (batch-get, single poll per cycle)
- Static assets in `Static/` (fonts, PNGs, logos)

## How to run

```
python app.py
```

The server starts on port 5000. Open any overlay page at:
- `/Main Leaderboard.html`
- `/Lower Leaderboard.html`
- `/Lower Stats.html`
- `/Individual Kills.html`
- `/Team Kills.html`
- `/Placement.html`
- `/Top Bar Info.html`

## Environment variables / secrets

| Name | Description |
|------|-------------|
| `GOOGLE_API_KEY` | Google Sheets API key used to read tournament data |

## User preferences

- Keep the project's existing structure and stack.
