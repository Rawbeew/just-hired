#!/usr/bin/env python3
"""
Deduplication report for just-hired.

Answers, with numbers straight from local state:
  - which sources we have fetched from (and how many records each contributed)
  - total records ever received (unique rows + duplicates dropped)
  - duplicates dropped by content hash
  - net unique jobs with a post/fetch date in the last 24h and last 7 days

Method note (honest about what is measurable):
  The store keeps only one row per content hash (sha256 of normalized
  title|employer|location), so raw "records received" is not logged per run.
  We approximate totals two ways:
    1) DB view: every stored row is unique; duplicates dropped are counted by
       replaying the current jobs.json snapshot into an empty temp store and
       reporting insert-vs-dupe outcomes.
    2) Snapshot view: the live jobs.json may itself contain repeats; we hash
       its entries directly and count distinct vs repeated.
Run:  python scripts/dedup_report.py [--db PATH] [--jobs-json PATH]
"""
import argparse
import collections
import datetime
import json
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from jobstore import JobStore, content_hash  # noqa: E402

DEFAULT_DB = os.path.join(os.path.dirname(HERE), "jobs.db")
DEFAULT_JSON = os.path.join(os.path.dirname(HERE), "jobs.json")


def load_snapshot(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--jobs-json", default=DEFAULT_JSON)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    now = datetime.datetime.now(datetime.timezone.utc)

    # -- sources ----------------------------------------------------------
    sources = conn.execute(
        "SELECT source, COUNT(*) AS n FROM postings "
        "GROUP BY source ORDER BY n DESC").fetchall()
    n_sources = len(sources)
    total_unique = conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0]

    # -- net unique in windows --------------------------------------------
    def window(hours):
        cutoff = (now - datetime.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return conn.execute(
            "SELECT COUNT(*) FROM postings "
            "WHERE substr(COALESCE(posted_at, fetched_at), 1, 19) >= ?",
            (cutoff[:10] + "T00:00:00Z" if hours == 24 else cutoff),
        ).fetchone()[0]
    # day-granularity for posted_at dates (Job Bank gives date-only):
    d24 = (now - datetime.timedelta(hours=24)).strftime("%Y-%m-%d")
    d7 = (now - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    last24 = conn.execute(
        "SELECT COUNT(*) FROM postings WHERE COALESCE(posted_at, fetched_at) >= ?",
        (d24,)).fetchone()[0]
    last7 = conn.execute(
        "SELECT COUNT(*) FROM postings WHERE COALESCE(posted_at, fetched_at) >= ?",
        (d7,)).fetchone()[0]

    # -- snapshot replay: duplicates dropped -------------------------------
    entries = load_snapshot(args.jobs_json) if os.path.exists(args.jobs_json) else []
    tmpdb = tempfile.mktemp(suffix=".db")
    tmp = JobStore(tmpdb)
    ins, dup = tmp.upsert_many(entries, source="jobs.json-replay")
    tmp.close()
    os.remove(tmpdb)

    # -- in-snapshot repeats ----------------------------------------------
    hashes = [content_hash(e.get("title", ""), e.get("e", ""), e.get("loc", ""))
              for e in entries]
    counts = collections.Counter(hashes)
    snap_dupes = sum(c - 1 for c in counts.values())

    print("=" * 62)
    print("just-hired dedup report")
    print("=" * 62)
    print(f"sources represented in store:      {n_sources}")
    for s in sources:
        print(f"  {s['source'] or '(unlabeled)':<28} {s['n']:>6} unique postings")
    print(f"total unique postings stored:      {total_unique}")
    print(f"records in current jobs.json:      {len(entries)}")
    print(f"duplicates dropped (snapshot       {dup}")
    print(f"  replay into fresh store):")
    print(f"in-snapshot repeats (same hash     {snap_dupes}")
    print(f"  listed twice in jobs.json):")
    print(f"net unique last 24h:               {last24}")
    print(f"net unique last 7d:                {last7}")
    print("=" * 62)


if __name__ == "__main__":
    main()
