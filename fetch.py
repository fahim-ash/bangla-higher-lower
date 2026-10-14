#!/usr/bin/env python3
"""Add Bangladeshi topics to the game from Wikipedia.

For each topic it looks up the English Wikipedia article, its lead image and
Bangla title, downloads the image, and stores the median monthly page views
(English + Bangla Wikipedia, median of the last 12 full months) in data/game.db.

Duplicates are refused: a topic already in the DB, an image file already used,
or image bytes whose SHA-256 is already known are all skipped.

Usage:
  python3 fetch.py                       # add everything in topics.txt
  python3 fetch.py --file more.txt       # add from another list
  python3 fetch.py --add "Hilsa" --category Food [--name "Ilish"]
  python3 fetch.py --retry-skipped       # try previously rejected topics again
  python3 fetch.py --refresh-views       # update view counts of existing items
  python3 fetch.py --block "Awami League" --reason "banned party"
                                         # remove + exclude a topic
  python3 fetch.py --unblock "Khaleda Zia"   # or --unblock-reason "political person (temporary)"
  python3 fetch.py --status              # show what's in the DB
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import db

IMG_DIR = os.path.join(db.ROOT, "static", "images")
EXPORT_PATH = os.path.join(db.ROOT, "static", "items.json")
UA = "BanglaHigherLower/1.0 (personal hobby game; python-urllib)"


def http_get(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            time.sleep(0.5)  # be polite to Wikimedia
            return data if binary else json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                retry_after = e.headers.get("Retry-After", "")
                time.sleep(int(retry_after) if retry_after.isdigit() else 5 * 2 ** attempt)
                continue
            raise
        except urllib.error.URLError:
            time.sleep(5 * 2 ** attempt)
    raise RuntimeError(f"giving up on {url}")


def wiki_lookup(title):
    params = {
        "action": "query", "format": "json", "formatversion": "2",
        "redirects": "1", "titles": title,
        "prop": "pageimages|langlinks|description",
        "piprop": "thumbnail|name", "pithumbsize": "1280", "lllang": "bn",
    }
    data = http_get("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params))
    page = data["query"]["pages"][0]
    if page.get("missing") or page.get("invalid"):
        return None
    return page


def month_window(months=12):
    first_this_month = dt.date.today().replace(day=1)
    end = first_this_month - dt.timedelta(days=1)
    y, m = first_this_month.year, first_this_month.month - months
    while m <= 0:
        y, m = y - 1, m + 12
    return dt.date(y, m, 1), end


MONTHS = 12


def monthly_views(project, title):
    """{YYYYMM: user views} for one article over the last MONTHS full months."""
    start, end = month_window(MONTHS)
    article = urllib.parse.quote(title.replace(" ", "_"), safe="")
    url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
           f"{project}/all-access/user/{article}/monthly/"
           f"{start:%Y%m%d}00/{end:%Y%m%d}00")
    try:
        items = http_get(url)["items"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise
    return {i["timestamp"][:6]: i["views"] for i in items}


def window_months():
    start, _ = month_window(MONTHS)
    y, m = start.year, start.month
    out = []
    for _ in range(MONTHS):
        out.append(f"{y:04d}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def total_views(en_title, bn_title):
    """Median monthly views (en + bn combined) over the last MONTHS months.
    The median keeps one viral month from dominating; months with no data count as 0."""
    en = monthly_views("en.wikipedia", en_title)
    bn = monthly_views("bn.wikipedia", bn_title) if bn_title else {}
    return round(statistics.median(en.get(m, 0) + bn.get(m, 0) for m in window_months()))


def strip_parens(s):
    return re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()


def skip(conn, requested, reason):
    conn.execute("INSERT OR REPLACE INTO skipped(requested, reason) VALUES (?, ?)",
                 (requested, reason))
    conn.commit()
    print(f"  skip  {requested}: {reason}")


def is_blocked(conn, title):
    return conn.execute("SELECT 1 FROM blocked WHERE title = ?", (title,)).fetchone() is not None


def block(conn, title, reason):
    """Exclude a topic for good: remove it (and its image) if present, and block re-adding."""
    try:
        page = wiki_lookup(title)
    except Exception:  # offline / rate-limited: block the title as given
        page = None
    titles = {title} | ({page["title"]} if page else set())
    for t in titles:
        conn.execute("INSERT OR REPLACE INTO blocked(title, reason) VALUES (?, ?)", (t, reason))
        row = conn.execute(
            "SELECT i.id, i.image_id, img.local_path FROM items i JOIN images img ON img.id = i.image_id "
            "WHERE i.wiki_title = ?", (t,)).fetchone()
        if row:
            conn.execute("DELETE FROM items WHERE id = ?", (row["id"],))
            conn.execute("DELETE FROM images WHERE id = ?", (row["image_id"],))
            path = os.path.join(db.ROOT, "static", row["local_path"])
            if os.path.exists(path):
                os.remove(path)
            print(f"  removed {t}")
        conn.execute("DELETE FROM skipped WHERE requested = ?", (t,))
    conn.commit()
    print(f"  blocked {', '.join(sorted(titles))}")


def unblock(conn, title=None, reason=None):
    """Lift a block by title, or every block with a given reason."""
    if title:
        cur = conn.execute("DELETE FROM blocked WHERE title = ?", (title,))
    else:
        cur = conn.execute("DELETE FROM blocked WHERE reason = ?", (reason,))
    conn.commit()
    print(f"  unblocked {cur.rowcount} title(s) — run fetch.py again to add them back")


def add_topic(conn, requested, category, name=None, retry=False):
    if is_blocked(conn, requested):
        return "blocked"
    if conn.execute("SELECT 1 FROM items WHERE wiki_title = ?", (requested,)).fetchone():
        return "exists"
    if not retry and conn.execute("SELECT 1 FROM skipped WHERE requested = ?", (requested,)).fetchone():
        return "exists"

    page = wiki_lookup(requested)
    if page is None:
        skip(conn, requested, "no such Wikipedia article")
        return "skipped"
    title = page["title"]
    if is_blocked(conn, title):
        return "blocked"
    if conn.execute("SELECT 1 FROM items WHERE wiki_title = ?", (title,)).fetchone():
        skip(conn, requested, f"redirects to '{title}', which is already added")
        return "skipped"
    thumb = page.get("thumbnail")
    if not thumb:
        skip(conn, requested, "article has no lead image")
        return "skipped"

    # --- image de-duplication: file name, URL, then content hash ---
    source_file = page.get("pageimage")
    src_url = thumb["source"].split("?")[0]
    dup = conn.execute(
        """SELECT i.name FROM images img JOIN items i ON i.image_id = img.id
           WHERE img.source_file = ? OR img.source_url = ?""",
        (source_file, src_url)).fetchone()
    if dup:
        skip(conn, requested, f"image {source_file} already used by '{dup['name']}'")
        return "skipped"
    data = http_get(src_url, binary=True)
    sha = hashlib.sha256(data).hexdigest()
    dup = conn.execute(
        """SELECT i.name FROM images img JOIN items i ON i.image_id = img.id
           WHERE img.sha256 = ?""", (sha,)).fetchone()
    if dup:
        skip(conn, requested, f"identical image bytes already used by '{dup['name']}'")
        return "skipped"

    bn_title = next((l["title"] for l in page.get("langlinks", []) if l["lang"] == "bn"), None)
    views = total_views(title, bn_title)
    if views == 0:
        skip(conn, requested, "no page view data")
        return "skipped"

    ext = os.path.splitext(urllib.parse.urlparse(src_url).path)[1].lower() or ".jpg"
    os.makedirs(IMG_DIR, exist_ok=True)
    local_name = f"{sha[:16]}{ext}"
    with open(os.path.join(IMG_DIR, local_name), "wb") as f:
        f.write(data)

    cur = conn.execute(
        "INSERT INTO images(source_file, source_url, sha256, local_path, width, height) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (source_file, src_url, sha, f"images/{local_name}", thumb.get("width"), thumb.get("height")))
    conn.execute(
        "INSERT INTO items(wiki_title, name, name_bn, description, category, views, image_id, page_url) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (title, name or strip_parens(requested), strip_parens(bn_title) if bn_title else None,
         page.get("description"), category, views, cur.lastrowid,
         "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))))
    conn.execute("DELETE FROM skipped WHERE requested = ?", (requested,))
    conn.commit()
    print(f"  added {title} ({bn_title or '-'}) — {views:,} views/month")
    return "added"


def read_topics(path):
    """Lines look like:  Category | Wikipedia title [| display name]"""
    topics = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2:
                print(f"bad line in {path}: {line}", file=sys.stderr)
                continue
            topics.append((parts[0], parts[1], parts[2] if len(parts) > 2 else None))
    return topics


def export_json(conn):
    with open(EXPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(db.all_items(conn), f, ensure_ascii=False)


def refresh_views(conn):
    for row in conn.execute("SELECT id, wiki_title FROM items").fetchall():
        try:
            page = wiki_lookup(row["wiki_title"])
            bn = next((l["title"] for l in (page or {}).get("langlinks", []) if l["lang"] == "bn"), None)
            views = total_views(row["wiki_title"], bn)
        except Exception as e:  # keep the old value, try again next refresh
            print(f"  error {row['wiki_title']}: {e}", file=sys.stderr)
            continue
        conn.execute("UPDATE items SET views = ?, updated_at = datetime('now') WHERE id = ?",
                     (views, row["id"]))
        conn.commit()
        print(f"  {row['wiki_title']}: {views:,}")


def status(conn):
    n_items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    n_imgs = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    print(f"{n_items} items, {n_imgs} images\n")
    for r in conn.execute("SELECT category, COUNT(*) c FROM items GROUP BY category ORDER BY c DESC"):
        print(f"  {r['category']:<12} {r['c']}")
    blocked = conn.execute("SELECT title, reason FROM blocked ORDER BY title").fetchall()
    if blocked:
        print(f"\n{len(blocked)} blocked:")
        for r in blocked:
            print(f"  {r['title']}: {r['reason']}")
    skipped = conn.execute("SELECT requested, reason FROM skipped ORDER BY requested").fetchall()
    if skipped:
        print(f"\n{len(skipped)} skipped:")
        for r in skipped:
            print(f"  {r['requested']}: {r['reason']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=os.path.join(db.ROOT, "topics.txt"))
    ap.add_argument("--add", help="a single Wikipedia title to add")
    ap.add_argument("--category", default="Other")
    ap.add_argument("--name", help="display name for --add")
    ap.add_argument("--retry-skipped", action="store_true")
    ap.add_argument("--refresh-views", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--block", action="append", help="remove and permanently exclude a topic (repeatable)")
    ap.add_argument("--reason", default="excluded")
    ap.add_argument("--unblock", help="lift a block on a title (or use --unblock-reason)")
    ap.add_argument("--unblock-reason", help="lift every block with this reason")
    args = ap.parse_args()

    conn = db.connect()
    if args.status:
        return status(conn)
    if args.unblock or args.unblock_reason:
        unblock(conn, args.unblock, args.unblock_reason)
    elif args.block:
        for t in args.block:
            block(conn, t, args.reason)
    elif args.refresh_views:
        refresh_views(conn)
    else:
        topics = [(args.category, args.add, args.name)] if args.add else read_topics(args.file)
        counts = {"added": 0, "skipped": 0, "exists": 0, "blocked": 0}
        for category, title, name in topics:
            try:
                counts[add_topic(conn, title, category, name, retry=args.retry_skipped or bool(args.add))] += 1
            except Exception as e:  # network hiccup etc. — keep going
                print(f"  error {title}: {e}", file=sys.stderr)
        print(f"\nadded {counts['added']}, skipped {counts['skipped']}, already known {counts['exists']}, blocked {counts['blocked']}")
    export_json(conn)


if __name__ == "__main__":
    main()
