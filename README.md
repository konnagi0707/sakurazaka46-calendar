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

## 订阅方式（不要导入）
ICS 订阅链接：
```
https://calendar.google.com/calendar/ical/20abe4a7fe0b3d1f8f29e24a2b69a1c85f551bffcf506f6f9eb9cf0227dd3eea%40group.calendar.google.com/public/basic.ics
```

Google Calendar 添加：
```
https://calendar.google.com/calendar?cid=MjBhYmU0YTdmZTBiM2QxZjhmMjllMjRhMmI2OWExYzg1ZjU1MWJmZmNmNTA2ZjZmOWViOWNmMDIyN2RkM2VlYUBncm91cC5jYWxlbmRhci5nb29nbGUuY29t
```

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
