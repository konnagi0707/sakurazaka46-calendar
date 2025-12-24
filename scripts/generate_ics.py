import argparse
import datetime as dt
import hashlib
import re
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta

BASE_URL = "https://sakurazaka46.com/s/s46/media/list"
IMA = "0000"
USER_AGENT = "Mozilla/5.0 (compatible; sakurazaka46-calendar/1.0)"
DEFAULT_DURATION_MIN = 60

CD_VALUES = {
    "all": None,
    "shakehands": "shakehands",
    "event": "event",
    "goods": "goods",
    "release": "release",
    "ticket": "ticket",
    "media": "media",
    "birthday": "birthday",
    "other": "other",
}

DATE_LINE = re.compile(r"^(?P<y>\d{4})\.(?P<m>\d{2})\.(?P<d>\d{2})(?:\s+(?P<t>.+))?$")
TIME_RANGE = re.compile(r"(?P<h1>\d{1,2}):(?P<m1>\d{2})[～〜](?:(?P<h2>\d{1,2}):(?P<m2>\d{2}))?")

SKIP_TOKENS = {
    "NEW",
    "NEW!",
    "NEW!!",
    "NEW!!!",
}


@dataclass(frozen=True)
class Event:
    uid: str
    summary: str
    start: dt.datetime | dt.date
    end: dt.datetime | dt.date
    all_day: bool
    description: str
    source_url: str


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def build_month_url(year: int, month: int, cd: Optional[str]) -> str:
    dy = f"{year}{month:02d}01"
    params = {"dy": dy, "ima": IMA}
    if cd:
        params["cd"] = cd
    return f"{BASE_URL}?{urlencode(params)}"


def fetch(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    return r.text


def extract_schedule_lines(html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def normalize_time(base_date: dt.date, hour: int, minute: int) -> dt.datetime:
    if hour >= 24:
        base_date = base_date + dt.timedelta(days=1)
        hour -= 24
    return dt.datetime(base_date.year, base_date.month, base_date.day, hour, minute)


def parse_datetime(
    date_str: str, time_part: Optional[str]
) -> Tuple[dt.date, Optional[Tuple[dt.datetime, dt.datetime]]]:
    m = DATE_LINE.match(date_str)
    if not m:
        raise ValueError(f"Bad date line: {date_str}")

    y, mo, d = int(m.group("y")), int(m.group("m")), int(m.group("d"))
    base_date = dt.date(y, mo, d)

    if not time_part:
        return base_date, None

    time_part = time_part.replace(" ", "")
    tr = TIME_RANGE.search(time_part)
    if not tr:
        return base_date, None

    h1, m1 = int(tr.group("h1")), int(tr.group("m1"))
    h2 = tr.group("h2")
    m2 = tr.group("m2")

    start_dt = normalize_time(base_date, h1, m1)

    if h2 is not None and m2 is not None:
        eh, em = int(h2), int(m2)
        end_dt = normalize_time(base_date, eh, em)
        if end_dt <= start_dt:
            end_dt = end_dt + dt.timedelta(days=1)
    else:
        end_dt = start_dt + dt.timedelta(minutes=DEFAULT_DURATION_MIN)

    return base_date, (start_dt, end_dt)


def is_category_candidate(text: str) -> bool:
    if text in SKIP_TOKENS:
        return False
    if " " in text:
        return False
    if len(text) > 20:
        return False
    if DATE_LINE.match(text):
        return False
    if text.lower().startswith("http"):
        return False
    return True


def clean_title(text: str) -> str:
    text = text.strip()
    if text.startswith("## "):
        return text[3:].strip()
    if text.startswith("#"):
        return text.lstrip("#").strip()
    return text


def parse_events_from_lines(lines: List[str], source_url: str) -> List[Event]:
    events: List[Event] = []
    i = 0

    while i < len(lines):
        ln = lines[i]
        m = DATE_LINE.match(ln)
        if not m:
            i += 1
            continue

        date_str = f"{m.group('y')}.{m.group('m')}.{m.group('d')}"
        time_part = m.group("t")
        base_date, time_tuple = parse_datetime(date_str, time_part)

        block: List[str] = []
        j = i + 1
        while j < len(lines) and not DATE_LINE.match(lines[j]):
            block.append(lines[j])
            j += 1

        category_idx = None
        for idx, text in enumerate(block):
            if is_category_candidate(text):
                category_idx = idx
                break

        if category_idx is None:
            i = j
            continue

        category = block[category_idx]

        title_idx = None
        title = None
        for idx in range(category_idx + 1, len(block)):
            text = block[idx]
            if text in SKIP_TOKENS:
                continue
            title = clean_title(text)
            title_idx = idx
            break

        if not title:
            i = j
            continue

        desc_lines: List[str] = []
        if title_idx is not None and title_idx + 1 < len(block):
            desc_lines = block[title_idx + 1 :]

        description = "\n".join(desc_lines).strip()
        if description:
            description = f"{description}\n\nSource: {source_url}"
        else:
            description = f"Source: {source_url}"

        if time_tuple is None:
            start = base_date
            end = base_date + dt.timedelta(days=1)
            all_day = True
            start_key = start.isoformat()
        else:
            start, end = time_tuple
            all_day = False
            start_key = start.isoformat()

        uid = sha1(f"{category}|{start_key}|{title}|{source_url}")
        summary = f"[{category}] {title}"

        events.append(
            Event(
                uid=uid,
                summary=summary,
                start=start,
                end=end,
                all_day=all_day,
                description=description,
                source_url=source_url,
            )
        )

        i = j

    uniq = {}
    for ev in events:
        uniq[ev.uid] = ev
    return list(uniq.values())


def ics_escape(s: str) -> str:
    return (
        s.replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def to_ics(events: Iterable[Event]) -> str:
    now = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out = []
    out.append("BEGIN:VCALENDAR")
    out.append("VERSION:2.0")
    out.append("PRODID:-//sakurazaka46-calendar//EN")
    out.append("CALSCALE:GREGORIAN")

    for ev in sorted(events, key=lambda e: (str(e.start), e.summary)):
        out.append("BEGIN:VEVENT")
        out.append(f"UID:{ev.uid}")
        out.append(f"DTSTAMP:{now}")
        out.append(f"SUMMARY:{ics_escape(ev.summary)}")
        out.append(f"DESCRIPTION:{ics_escape(ev.description)}")

        if ev.all_day:
            ds = ev.start.strftime("%Y%m%d")  # type: ignore[union-attr]
            de = ev.end.strftime("%Y%m%d")  # type: ignore[union-attr]
            out.append(f"DTSTART;VALUE=DATE:{ds}")
            out.append(f"DTEND;VALUE=DATE:{de}")
        else:
            ds = ev.start.strftime("%Y%m%dT%H%M%S")  # type: ignore[union-attr]
            de = ev.end.strftime("%Y%m%dT%H%M%S")  # type: ignore[union-attr]
            out.append(f"DTSTART:{ds}")
            out.append(f"DTEND:{de}")

        out.append("END:VEVENT")

    out.append("END:VCALENDAR")
    return "\n".join(out) + "\n"


def month_iter(start: dt.date, months: int) -> List[Tuple[int, int]]:
    cur = start.replace(day=1)
    out = []
    for k in range(months):
        d = cur + relativedelta(months=k)
        out.append((d.year, d.month))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cd", default="all", help="all/media/event/... (see CD_VALUES)")
    ap.add_argument("--months", type=int, default=6, help="how many months ahead to fetch")
    ap.add_argument("--out", default=None, help="output ics path")
    ap.add_argument("--sleep", type=float, default=0.6, help="polite delay between requests")
    args = ap.parse_args()

    cd_label = args.cd
    if cd_label not in CD_VALUES:
        raise SystemExit(f"Unknown cd={cd_label}. Choices: {list(CD_VALUES.keys())}")

    cd = CD_VALUES[cd_label]
    months = month_iter(dt.date.today(), args.months)

    all_events: List[Event] = []
    for y, m in months:
        url = build_month_url(y, m, cd)
        html = fetch(url)
        lines = extract_schedule_lines(html)
        all_events.extend(parse_events_from_lines(lines, source_url=url))
        time.sleep(args.sleep)

    out_path = args.out or f"docs/sakurazaka46_{cd_label}.ics"
    ics = to_ics(all_events)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(ics)

    print(f"Wrote {len(all_events)} events to {out_path}")


if __name__ == "__main__":
    main()
