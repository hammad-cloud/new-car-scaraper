# Mira e:S Auction Agent

Nightly: tomorrow's auctions on Al Ubaid portal -> sheet check -> OLIAC year -> Telegram at 11 PM.

## Files
| File | Job |
|---|---|
| `graph.py` | Run this. LangGraph flow + 11 PM report |
| `portal.py` | Login / saved search / tomorrow's day / collect lots / colour pre-filter / image credits |
| `car_agent.py` | Per lot: GET IMAGES + 60 s wait (USS), sheet, OLIAC check |
| `car_rules.py` | Your rules (colour W19/W25/S28, 2023-2025, 2,000-19,999 km, grade 4+, wiper, camera, banned marks) |
| `notify.py` | Telegram messages |
| `store.py` | Remembers lots already reported |

## Setup (Windows)
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
copy env.example .env      (then fill in .env)
```

## Fix the selectors (one time)
```
playwright codegen https://auc.alubaidmotors.com
```
Do by hand: log in -> Saved searches -> DAIHATSU MIRA E S -> TUE -> open a lot -> GET IMAGES -> next page.
Copy the selectors into `SELECTORS` in `portal.py` (every line marked TODO).
Repeat on https://oliac.com/autos/ and check the search box selector in `car_agent.py`.

## Test
1. `.env`: `HEADLESS=0`, run `python graph.py` and watch it.
2. Temporarily set `REPORT_AT_HOUR = 0` in graph.py so it reports immediately.
3. Lot 65099 (wine, R67) must be REJECTED.
4. Compare with your own manual search for a week.

## Schedule (automatic)
```
powershell -ExecutionPolicy Bypass -File setup.ps1          # one time: venv, packages, Chromium, .env
powershell -ExecutionPolicy Bypass -File install_task.ps1   # registers "MiraES Auction Agent", daily 10 PM
```
- The task runs `run_nightly.ps1`, which logs to `logs\run_YYYY-MM-DD.log` and keeps 30 days of logs.
- It wakes the PC, runs on battery, and catches up if the PC was off at 10 PM. The PC must be logged in.
- Run it now: `Start-ScheduledTask -TaskName "MiraES Auction Agent"`
- Pause it: `Disable-ScheduledTask -TaskName "MiraES Auction Agent"` (turn it back on with `Enable-ScheduledTask`)
- Remove it: `Unregister-ScheduledTask -TaskName "MiraES Auction Agent" -Confirm:$false`

## Attach mode (safer)
1. Start Chrome: `"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222`
2. Log in, open your saved search, click tomorrow's day.
3. `.env`: `MODE=attach`, then run `python graph.py`.
