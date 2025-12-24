import argparse
import datetime as dt
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Dict, Iterable

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_ics as g

SCOPES = ["https://www.googleapis.com/auth/calendar"]
MANAGED_KEY = "managedBy"
MANAGED_VAL = "sakurazaka46-calendar"
DEFAULT_TZ = "Asia/Tokyo"


def load_tz(name: str) -> dt.tzinfo:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        return dt.timezone(dt.timedelta(hours=9))


def build_service(sa_path: str):
    creds = Credentials.from_service_account_file(sa_path, scopes=SCOPES)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def rfc3339(dt_obj: dt.datetime) -> str:
    return dt_obj.isoformat()


def list_managed_events(
    service, calendar_id: str, time_min: str, time_max: str
) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    page_token = None
    while True:
        request = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=2500,
            pageToken=page_token,
            privateExtendedProperty=[f"{MANAGED_KEY}={MANAGED_VAL}"],
        )
        resp = execute_with_backoff(request)
        for ev in resp.get("items", []):
            out[ev["id"]] = ev
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def build_body(ev: g.Event, tz: dt.tzinfo, tz_name: str) -> dict:
    if ev.all_day:
        start = {"date": ev.start.isoformat()}
        end = {"date": ev.end.isoformat()}
    else:
        start_dt = ev.start.replace(tzinfo=tz)
        end_dt = ev.end.replace(tzinfo=tz)
        start = {"dateTime": rfc3339(start_dt), "timeZone": tz_name}
        end = {"dateTime": rfc3339(end_dt), "timeZone": tz_name}

    return {
        "id": ev.uid,
        "summary": ev.summary,
        "description": ev.description,
        "start": start,
        "end": end,
        "source": {
            "title": "Sakurazaka46 Official Schedule",
            "url": ev.source_url,
        },
        "extendedProperties": {
            "private": {
                MANAGED_KEY: MANAGED_VAL,
                "sourceUrl": ev.source_url,
            }
        },
    }


def http_status(err: HttpError) -> int | None:
    status = getattr(err, "status_code", None)
    if status is None and getattr(err, "resp", None) is not None:
        status = getattr(err.resp, "status", None)
    return status


def error_reasons(err: HttpError) -> set[str]:
    try:
        payload = json.loads(err.content.decode("utf-8"))
    except Exception:
        return set()
    errors = payload.get("error", {}).get("errors", [])
    reasons = set()
    for item in errors:
        if isinstance(item, dict) and item.get("reason"):
            reasons.add(item["reason"])
    return reasons


def is_rate_limit_error(err: HttpError) -> bool:
    status = http_status(err)
    if status not in (403, 429):
        return False
    reasons = error_reasons(err)
    if reasons.intersection({"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"}):
        return True
    if b"Rate Limit Exceeded" in getattr(err, "content", b""):
        return True
    return "Rate Limit Exceeded" in str(err)


def execute_with_backoff(request, max_retries: int = 5, base_sleep: float = 1.0):
    for attempt in range(max_retries + 1):
        try:
            return request.execute()
        except HttpError as exc:
            if not is_rate_limit_error(exc) or attempt >= max_retries:
                raise
            delay = base_sleep * (2 ** attempt) + random.random() * 0.25
            time.sleep(delay)


def upsert_event(service, calendar_id: str, body: dict, exists: bool) -> str:
    if exists:
        try:
            execute_with_backoff(
                service.events().update(calendarId=calendar_id, eventId=body["id"], body=body)
            )
            return "updated"
        except HttpError as exc:
            if http_status(exc) == 404:
                execute_with_backoff(service.events().insert(calendarId=calendar_id, body=body))
                return "inserted"
            raise

    try:
        execute_with_backoff(service.events().insert(calendarId=calendar_id, body=body))
        return "inserted"
    except HttpError as exc:
        if http_status(exc) == 409:
            execute_with_backoff(
                service.events().update(calendarId=calendar_id, eventId=body["id"], body=body)
            )
            return "updated"
        raise


def collect_events(cd_label: str, months: int, sleep_sec: float) -> Iterable[g.Event]:
    cd = g.CD_VALUES[cd_label]
    months_iter = g.month_iter(dt.date.today(), months)
    uniq: Dict[str, g.Event] = {}

    for y, m in months_iter:
        url = g.build_month_url(y, m, cd)
        html = g.fetch(url)
        lines = g.extract_schedule_lines(html)
        for ev in g.parse_events_from_lines(lines, source_url=url):
            uniq[ev.uid] = ev
        time.sleep(sleep_sec)

    return list(uniq.values())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cd", default="all", help=f"one of: {list(g.CD_VALUES.keys())}")
    ap.add_argument("--months", type=int, default=8)
    ap.add_argument("--calendar-id", default=os.environ.get("GCAL_CALENDAR_ID"))
    ap.add_argument(
        "--sa-path", default=os.environ.get("GCAL_SERVICE_ACCOUNT_PATH", "service_account.json")
    )
    ap.add_argument("--tz", default=os.environ.get("GCAL_TIMEZONE", DEFAULT_TZ))
    ap.add_argument("--prune", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.6, help="delay between month requests")
    ap.add_argument("--op-sleep", type=float, default=0.2, help="delay between calendar writes")
    args = ap.parse_args()

    if not args.calendar_id:
        raise SystemExit("Missing --calendar-id or env GCAL_CALENDAR_ID")

    cd_label = args.cd
    if cd_label not in g.CD_VALUES:
        raise SystemExit(f"Unknown cd={cd_label}. Choices: {list(g.CD_VALUES.keys())}")

    tz = load_tz(args.tz)
    service = build_service(args.sa_path)

    new_events = list(collect_events(cd_label, args.months, args.sleep))
    new_ids = {e.uid for e in new_events}

    now = dt.datetime.now(tz)
    time_min = dt.datetime(now.year, now.month, 1, tzinfo=tz)
    time_max = time_min + dt.timedelta(days=31 * args.months)
    managed = list_managed_events(service, args.calendar_id, time_min.isoformat(), time_max.isoformat())

    inserted = updated = 0
    for ev in new_events:
        body = build_body(ev, tz, args.tz)
        action = upsert_event(service, args.calendar_id, body, exists=ev.uid in managed)
        if action == "inserted":
            inserted += 1
        else:
            updated += 1
        if args.op_sleep:
            time.sleep(args.op_sleep)

    deleted = 0
    if args.prune:
        for event_id in list(managed.keys()):
            if event_id not in new_ids:
                execute_with_backoff(
                    service.events().delete(calendarId=args.calendar_id, eventId=event_id)
                )
                deleted += 1

    print(
        f"cd={cd_label} inserted={inserted} updated={updated} deleted={deleted} total_new={len(new_events)}"
    )


if __name__ == "__main__":
    main()
