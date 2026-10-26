"""
YouTube comment collector (official YouTube Data API v3) for:
"Analisis Respons Publik terhadap Alokasi Anggaran Program MBG 2027
 pada Periode Pascapemaparan RKA BGN September 2026"

SCOPE RULES (everything below enforces the paper's title)
  Timeframe : videos AND comments from 2026-09-03 (RKA BGN presentation) onward
  Context   : a video must mention (a) MBG/BGN, (b) a 2027-budget anchor term
              (2027, RKA, RAPBN, 240,2, 25 triliun, Komisi IX, Sudaryono, ...), and
              (c) a budget term. Anything else is rejected and logged with the reason.

Setup:
  1. Google Cloud Console -> project -> enable "YouTube Data API v3" -> Create API key
  2. pip install requests pandas
  3. Windows (cmd):  set YOUTUBE_API_KEY=your_key_here   (same window you run the script in)
  4. python scrape_youtube_mbg.py
Workflow:
  DISCOVER_ONLY = True  -> writes candidates_youtube.csv (accepted) + rejected_youtube.csv (audit)
  pick IDs -> SEED_VIDEO_IDS, set DISCOVER_ONLY = False -> collects comments
"""
import os
import re
import sys
from functools import lru_cache

import pandas as pd
import requests

API_KEY = os.environ.get("YOUTUBE_API_KEY")
BASE = "https://www.googleapis.com/youtube/v3"

# ---------- SCOPE CONFIG ----------
COMMENT_CUTOFF = pd.Timestamp("2026-09-03", tz="UTC")   # RKA BGN presentation
VIDEO_SINCE = "2026-09-03T00:00:00Z"                    # videos before this are out of timeframe
TOTAL_CAP = 3500
PER_VIDEO_CAP = 500          
MAX_VIDEOS = 60
SEARCH_PAGES = 3             # each search page = 100 quota units
SEARCH_ORDER = "viewCount"   # high-engagement first; "date" = newest first
MIN_VIDEO_COMMENTS = 10      # floor for efficiency only; relevance is handled by the scope check

# Videos reviewed by hand and judged off-scope (document each reason in C5).
EXCLUDE_VIDEO_IDS = {
    "ytxHVW9L_-w",  # macro/forex outlook, MBG not in title
    "Qql4m2uDjKE",  # forex only
    "nGUhlO7o4RE",  # 2026 realization (the "2027" in the title is a typo)
    "Ec3OoSix1yI",  # LED procurement scandal, not the 2027 allocation
    "BvVsnu0MdYg",  # LED procurement
    "L3N-6F8kemY",  # LED procurement
    "EIiPnOQbS2M",  # BPOM's own budget request
    "gTXqHbqAEjM",  # BPOM budget
}

DISCOVER_ONLY = False         # True: search + save candidate/rejected CSVs, then stop

SEED_VIDEO_IDS = []          # optional: paste video_id values here to override the CSV
# If SEED_VIDEO_IDS is empty, the videos are read from this file (written by discovery mode).
# Delete rows from it in Excel to drop videos you don't want; the script uses what is left.
CANDIDATES_CSV = "candidates_youtube.csv"
# False: seed videos that fail the scope check keep only comments that themselves contain
#        budget terms. True: keep all comments of every seed (only after you verified them).
SEED_ASSUME_RELEVANT = False

QUERIES = [
    "anggaran MBG 2027",
    "RAPBN 2027 MBG",
    "RKA BGN 2027",
    "Sudaryono Komisi IX anggaran BGN",
    "MBG 240,2 triliun",
    "MBG efisiensi Rp25 triliun",
    "pagu anggaran MBG 2027 DPR",
    "BGN anggaran 2027 72,1 juta penerima",
    # post-RKA developments of the same allocation (approval, cuts, trade-offs)
    "DPR setujui anggaran BGN 2027",
    "anggaran MBG dipangkas 2027",
    "MBG 2027 subsidi BBM LPG dipangkas",
    "anggaran pendidikan MBG 2027",
    "Purbaya anggaran MBG",
]

# (a) topic: the programme / agency
MBG_TERMS = ["mbg", "makan bergizi gratis", "bgn", "badan gizi nasional", "sppg"]
# (b) context anchors: tie a video to the 2027 budget / RKA event, not MBG in general
ANCHOR_TERMS = [
    "2027", "rapbn", "rka", "240,2", "240.2", "240 triliun", "25 triliun",
    "komisi ix", "sudaryono", "72,1 juta", "72.1 juta", "pagu",
]
# (c) budget vocabulary (also used on comments)
BUDGET_TERMS = [
    "anggaran", "rapbn", "rka", "apbn", "triliun", "efisiensi", "pagu",
    "serapan", "defisit", "utang", "fiskal", "komisi ix", "sudaryono",
    "72,1 juta", "72.1 juta", "korupsi", "transparansi", "dana pendidikan",
]
# ----------------------------------

STATS = {"calls": 0, "units": 0, "errors": {}}
FUNNEL = {"search_hits": 0, "videos_kept": 0, "comments_raw": 0, "too_old": 0, "lost_context": 0}
CANDIDATES = []   # videos that passed the scope check
REJECTED = []     # videos that did not, with the reason (audit trail for the report)


@lru_cache(maxsize=None)
def _pat(term):
    # whole-word match: "rka" must not match "perkara"; "utang" must not match "mengutang"
    return re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)


def has_any(text, terms):
    text = text or ""
    return [t for t in terms if _pat(t).search(text)]


def api_get(endpoint, **params):
    """Returns parsed JSON, or {"_error": reason} on failure. Always logs why."""
    params = {k: v for k, v in params.items() if v is not None}
    params["key"] = API_KEY
    STATS["calls"] += 1
    STATS["units"] += 100 if endpoint == "search" else 1
    try:
        r = requests.get(f"{BASE}/{endpoint}", params=params, timeout=30)
    except requests.RequestException as e:
        print(f"[WARN] network error on {endpoint}: {e}")
        STATS["errors"]["network"] = STATS["errors"].get("network", 0) + 1
        return {"_error": "network"}
    if r.status_code == 200:
        return r.json()

    try:
        err = r.json()["error"]
        reason, msg = err["errors"][0]["reason"], err["message"]
    except Exception:
        reason, msg = "unknown", r.text[:200]
    STATS["errors"][reason] = STATS["errors"].get(reason, 0) + 1
    if reason != "commentsDisabled":
        print(f"[WARN] {endpoint} HTTP {r.status_code} reason={reason}: {msg}")
    if reason == "quotaExceeded":
        print("[STOP] Daily quota used up (resets at midnight Pacific Time). "
              "Saving what was collected so far.")
        return {"_error": "quotaExceeded"}
    if reason in ("keyInvalid", "API_KEY_INVALID", "accessNotConfigured"):
        sys.exit("[STOP] API key problem: check the key and that YouTube Data API v3 is enabled.")
    return {"_error": reason}


def ok(data):
    return data is not None and "_error" not in data


# ---------- scope check ----------
def classify(sn):
    """Returns (reject_reason or None, anchors matched, budget terms matched)."""
    tags = " ".join(sn.get("tags", []))
    blob = " ".join([sn.get("title", ""), sn.get("description", ""), tags])
    anchors = has_any(blob, ANCHOR_TERMS)
    budget = has_any(blob, BUDGET_TERMS)
    # The programme must be named in the TITLE or TAGS. A mention buried in the description
    # is how forex/macro videos slipped through ("...also see our MBG video").
    if not has_any(sn.get("title", "") + " " + tags, MBG_TERMS):
        return "no_mbg_in_title", anchors, budget
    if not anchors:
        return "no_2027_anchor", anchors, budget
    if not budget:
        return "no_budget_term", anchors, budget
    return None, anchors, budget


def video_row(v, reason, anchors, budget):
    sn = v["snippet"]
    return {
        "video_id": v["id"],
        "published": sn["publishedAt"][:10],
        "n_comments": int(v.get("statistics", {}).get("commentCount", 0)),
        "video_title": sn.get("title", ""),
        "post_permalink": f'https://www.youtube.com/watch?v={v["id"]}',
        "anchors": ";".join(anchors),
        "budget_terms": ";".join(budget),
        "reason": reason or "accepted",
    }


# ---------- 1. find videos ----------
def collect_videos():
    ids = {}
    for q in QUERIES:
        token = None
        for _ in range(SEARCH_PAGES):
            data = api_get("search", part="snippet", type="video", q=q,
                           publishedAfter=VIDEO_SINCE, order=SEARCH_ORDER,
                           regionCode="ID", relevanceLanguage="id",
                           maxResults=50, pageToken=token)
            if not ok(data):
                if data and data["_error"] == "quotaExceeded":
                    return rank_videos(ids)
                break
            for it in data["items"]:
                ids[it["id"]["videoId"]] = True
                FUNNEL["search_hits"] += 1
            token = data.get("nextPageToken")
            if not token:
                break
    return rank_videos(ids)


def rank_videos(ids):
    ids = list(ids)
    videos = []
    for i in range(0, len(ids), 50):          # videos.list = 1 unit per 50 ids
        data = api_get("videos", part="snippet,statistics", id=",".join(ids[i:i + 50]))
        if not ok(data):
            continue
        for v in data["items"]:
            reason, anchors, budget = classify(v["snippet"])
            row = video_row(v, reason, anchors, budget)
            if reason is None and v["id"] in EXCLUDE_VIDEO_IDS:
                reason = row["reason"] = "manually_excluded"
            if reason is None and row["n_comments"] < MIN_VIDEO_COMMENTS:
                reason = row["reason"] = "below_min_comments"
            if reason:
                FUNNEL[reason] = FUNNEL.get(reason, 0) + 1
                REJECTED.append(row)
                continue
            row["post_budget"] = True
            videos.append(row)
    videos.sort(key=lambda x: x["n_comments"], reverse=True)
    CANDIDATES.extend(videos)
    videos = videos[:MAX_VIDEOS]
    FUNNEL["videos_kept"] = len(videos)
    return videos


def save_candidates():
    if REJECTED:
        pd.DataFrame(REJECTED).drop_duplicates(subset=["video_id"]).sort_values(
            "n_comments", ascending=False).to_csv("rejected_youtube.csv", index=False)
    print(f"\nFunnel: {FUNNEL}")
    if not CANDIDATES:
        print("[DIAGNOSIS] No video passed the scope check. See rejected_youtube.csv for why "
              "(reason column). If the right videos are there, loosen ANCHOR_TERMS; "
              f"if the list is empty, errors: {STATS['errors']}")
        return
    cdf = pd.DataFrame(CANDIDATES).drop_duplicates(subset=["video_id"])
    cdf = cdf.sort_values("n_comments", ascending=False)
    cdf = cdf[["video_id", "published", "n_comments", "anchors", "video_title", "post_permalink"]]
    cdf.to_csv("candidates_youtube.csv", index=False)
    print(f"Saved {len(cdf)} accepted candidates -> candidates_youtube.csv (sorted by comments)")
    print(cdf.head(30).drop(columns=["post_permalink"]).to_string(index=False, max_colwidth=55))
    print(f"\nTop 15 videos hold {cdf.head(15)['n_comments'].sum()} comments "
          "(expect roughly 40-60% to survive the comment filters).")
    print("Rejected videos (with reasons) -> rejected_youtube.csv. Skim it for false negatives.")
    print(f"API calls: {STATS['calls']} | est. quota units: {STATS['units']} | errors: {STATS['errors']}")
    print("Next: choose videos, paste video_id values into SEED_VIDEO_IDS, "
          "set DISCOVER_ONLY = False, run again.")


def load_seed_videos(ids):
    """Look up the chosen IDs, enforce the timeframe, and print a verification table."""
    found = {}
    for i in range(0, len(ids), 50):
        data = api_get("videos", part="snippet,statistics", id=",".join(ids[i:i + 50]))
        if ok(data):
            found.update({v["id"]: v for v in data["items"]})

    print("\nSeed check (id | published | comments | scope | anchors | title)")
    videos = []
    for vid in ids:
        v = found.get(vid)
        if not v:
            print(f"[WARN] {vid}: NOT FOUND (deleted/private/mistyped)")
            continue
        reason, anchors, budget = classify(v["snippet"])
        row = video_row(v, reason, anchors, budget)
        print(f'{vid} | {row["published"]} | {row["n_comments"]} | {row["reason"]} | '
              f'{row["anchors"] or "-"} | {row["video_title"][:60]}')
        if v["snippet"]["publishedAt"] < VIDEO_SINCE:
            print("        -> skipped: published before the post-RKA timeframe")
            continue
        if row["n_comments"] == 0:
            print("        -> skipped: no comments (or disabled)")
            continue
        row["post_budget"] = (reason is None) or SEED_ASSUME_RELEVANT
        videos.append(row)
    FUNNEL["videos_kept"] = len(videos)
    print()
    return videos


# ---------- 2. collect comments ----------
def clean(text):
    text = re.sub(r"@\S+\s*", "", text or "")      # strip @mentions (also anonymizes)
    return re.sub(r"\s+", " ", text).strip()


def make_row(c, video, depth, parent_id):
    sn = c["snippet"]
    text = clean(sn.get("textOriginal") or sn.get("textDisplay"))
    return {
        "content_id": "youtube:" + c["id"],
        "platform": "youtube",
        "text": text,
        "created_at": pd.to_datetime(sn["publishedAt"], utc=True),
        "content_type": "reply",
        "permalink": f'{video["post_permalink"]}&lc={c["id"]}',
        "video_id": video["video_id"],
        "video_title": video["video_title"],
        "post_permalink": video["post_permalink"],
        "parent_id": ("youtube:" + parent_id) if parent_id else None,
        "depth": depth,
        "like_count": sn.get("likeCount", 0),
        "post_budget": video["post_budget"],
        "video_anchors": video.get("anchors", ""),
        "matched_budget_kw": ";".join(has_any(text, BUDGET_TERMS)),
    }


def fetch_all_replies(parent_id):
    out, token = [], None
    while True:
        data = api_get("comments", part="snippet", parentId=parent_id,
                       maxResults=100, textFormat="plainText", pageToken=token)
        if not ok(data):
            break
        out.extend(data["items"])
        token = data.get("nextPageToken")
        if not token:
            break
    return out


def fetch_comments(video):
    rows, token = [], None
    while len(rows) < PER_VIDEO_CAP:
        data = api_get("commentThreads", part="snippet,replies", videoId=video["video_id"],
                       maxResults=100, order="time", textFormat="plainText", pageToken=token)
        if not ok(data):
            if data and data["_error"] == "commentsDisabled":
                print(f'[INFO] comments disabled: {video["video_title"][:60]}')
            if data and data["_error"] == "quotaExceeded":
                raise RuntimeError("quota")
            break
        reached_old = False
        for th in data["items"]:
            top = th["snippet"]["topLevelComment"]
            top_ts = pd.to_datetime(top["snippet"]["publishedAt"], utc=True)
            if top_ts < COMMENT_CUTOFF:
                reached_old = True     # threads are newest-first, so everything after is older
                FUNNEL["too_old"] += 1
                continue
            rows.append(make_row(top, video, 0, None))
            n_total = th["snippet"].get("totalReplyCount", 0)
            if n_total:
                replies = th.get("replies", {}).get("comments", [])
                if n_total > len(replies):          # inline replies are truncated
                    replies = fetch_all_replies(top["id"])
                for rp in replies:
                    rows.append(make_row(rp, video, 1, top["id"]))
        token = data.get("nextPageToken")
        if reached_old or not token:
            break
    FUNNEL["comments_raw"] += len(rows)
    return rows


def lost_context(r):
    """Short nested replies ("setuju", "bener banget") are uninterpretable without the parent."""
    if r["depth"] == 0:
        return False
    words = r["text"].split()
    standalone = bool(r["matched_budget_kw"]) and len(words) >= 5
    return (not standalone) and len(words) < 5


# ---------- 3. main ----------
def main():
    if not API_KEY:
        sys.exit("[STOP] Set the YOUTUBE_API_KEY environment variable first (see top of file).")

    if DISCOVER_ONLY:
        collect_videos()
        save_candidates()
        return

    seeds = list(SEED_VIDEO_IDS)
    if not seeds and os.path.exists(CANDIDATES_CSV):
        seeds = pd.read_csv(CANDIDATES_CSV)["video_id"].dropna().astype(str).tolist()
        print(f"Loaded {len(seeds)} video IDs from {CANDIDATES_CSV}")
    videos = load_seed_videos(seeds) if seeds else collect_videos()
    print(f"Videos used: {len(videos)}")
    if not videos:
        print("[DIAGNOSIS] No usable videos. Run with DISCOVER_ONLY = True first, "
              "or check the seed table above.")
        print(f"API calls: {STATS['calls']} | est. quota units: {STATS['units']} | errors: {STATS['errors']}")
        return

    rows = []
    try:
        for v in videos:
            if len(rows) >= TOTAL_CAP:
                break
            tmp = fetch_comments(v)
            tmp = [r for r in tmp if r["created_at"] >= COMMENT_CUTOFF]
            n0 = len(tmp)
            tmp = [r for r in tmp if not lost_context(r)]
            FUNNEL["lost_context"] += n0 - len(tmp)
            tmp = [r for r in tmp if r["post_budget"] or r["matched_budget_kw"]]
            rows.extend(tmp[:PER_VIDEO_CAP])
    except RuntimeError:
        print("[STOP] Quota exhausted mid-run; saving partial results.")

    df = pd.DataFrame(rows[:TOTAL_CAP])
    if df.empty:
        print("No data collected.")
        print(f"Funnel: {FUNNEL} | errors: {STATS['errors']}")
        return
    df = df.drop_duplicates(subset=["content_id"])
    df = df[df["text"].str.len() >= 15]
    df["created_at"] = df["created_at"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    core = ["content_id", "platform", "text", "created_at", "content_type", "permalink"]
    df = df[core + [c for c in df.columns if c not in core]]
    df.to_csv("dataset_mbg_youtube.csv", index=False)

    print(f"Saved {len(df)} rows from {df['video_id'].nunique()} videos.")
    print(f"Funnel: {FUNNEL}")
    print(f"API calls: {STATS['calls']} | est. quota units: {STATS['units']} | errors: {STATS['errors']}")
    print("Replies dropped for lost parent context (report in C5): ", FUNNEL["lost_context"])


if __name__ == "__main__":
    main()