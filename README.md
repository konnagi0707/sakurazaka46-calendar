# sakurazaka46-calendar

Generate subscribe-ready ICS files from the Sakurazaka46 official schedule list.

## Local
```bash
pip install -r requirements.txt
python scripts/generate_ics.py --cd all --months 8 --out docs/sakurazaka46_all.ics
```

## GitHub Pages
Enable Pages with source: `main` branch + `/docs` folder. Then subscribe:

* https://<user>.github.io/<repo>/sakurazaka46_all.ics

## Google Calendar Sync
This repo also includes a Google Calendar sync workflow that writes events into a public calendar
so you can share `.../public/basic.ics`.

Local run example:
```bash
python scripts/sync_gcal.py --cd all --months 8 --calendar-id <calendar-id> --sa-path service_account.json
```

GitHub Actions requires these secrets:
* `GCAL_CALENDAR_ID`
* `GCAL_SA_JSON_B64` (base64-encoded service account JSON)
