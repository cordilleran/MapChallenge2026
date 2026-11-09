"""Day 9 slice S1: build the record table from the library (read only).

Reads every record folder in the library, keeps the frontmatter fields the
extraction needs, the abstract and keywords, the text length, and a detected
language. Writes `records` into the Day 9 DuckDB file. Nothing in the library
is written.

Usage:
    python 01_records.py            # paths from MC26_LIBRARY and MC26_DAY09_DIR

Academic types (D108) are flagged, not filtered out, so later layers can
reuse the same table for reports and bylaws.
"""
import os
import re
import sys
from pathlib import Path

import duckdb

LIBRARY = Path(os.environ.get("MC26_LIBRARY") or sys.exit("Set MC26_LIBRARY to the library's records folder (see README)."))
OUT_DIR = Path(os.environ.get("MC26_DAY09_DIR") or sys.exit("Set MC26_DAY09_DIR to the Day 9 data folder (see README)."))

ACADEMIC = {"article", "thesis", "book-chapter", "book-section",
            "conference-paper", "preprint"}

# Short stopword lists: enough to tell the few non-English texts apart.
STOP = {
    "en": "the of and to in is that for are with as by this on be from".split(),
    "fr": "le la les des et du une est dans pour que sur par au aux".split(),
    "es": "el la los las de y en que por para con una del es se".split(),
    "de": "der die und das ist mit von den zu im für auf nicht ein".split(),
    "pt": "o a os as de e do da em que para com uma não dos".split(),
}

FM_KEYS = ("title", "author", "doc-date", "instrument-type", "jurisdiction",
           "doi", "container", "source-org")


def frontmatter(text):
    """Return a dict of the simple `key: value` lines in the YAML header."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).split("\n"):
        k, sep, v = line.partition(":")
        if sep and k.strip() in FM_KEYS and k.strip() not in out:
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def language(text):
    """Guess the language from stopword counts in the first 20,000 characters."""
    words = re.findall(r"[a-zà-ÿ]+", text[:20000].lower())
    if len(words) < 50:
        return "unknown", 0.0
    counts = {lang: sum(words.count(w) for w in ws) for lang, ws in STOP.items()}
    best = max(counts, key=counts.get)
    total = sum(counts.values()) or 1
    return best, round(counts[best] / total, 3)


def abstract_and_keywords(note, source):
    """Abstract: the source text's own abstract paragraph if it has one,
    else the note's ingest abstract (tagged so its origin stays visible)."""
    abstract, origin = "", "none"
    m = re.search(r"(?im)^\s*(?:abstract|summary)\s*[:.\-—]?\s*(.{200,4000}?)\n\s*\n",
                  source[:60000])
    if m:
        abstract, origin = m.group(1).strip(), "source"
    else:
        m = re.search(r"\*\*Abstract:\*\*\s*(.+)", note)
        if m:
            abstract, origin = m.group(1).strip(), "ingest-note"
    m = re.search(r"(?im)^\s*(?:author\s+)?key\s*words?\s*[:.\-—]\s*(.{3,600})$",
                  source[:60000])
    keywords = m.group(1).strip() if m else ""
    return abstract, origin, keywords


def ingest_places(note):
    m = re.search(r"^\* \*\*Places:\*\*\s*(.+)$", note, re.M)
    return m.group(1).strip().rstrip(".") if m else ""


def main():
    rows = []
    for d in sorted(p for p in LIBRARY.iterdir() if p.is_dir()):
        rid = d.name
        note_p = d / f"{rid}.md"
        if not note_p.exists():
            continue
        note = note_p.read_text(errors="replace")
        src_p = d / f"{rid}.source.md"
        source = src_p.read_text(errors="replace") if src_p.exists() else ""
        body = re.sub(r"^---\n.*?\n---\n", "", source, count=1, flags=re.S)
        fm = frontmatter(note)
        dois = re.findall(r"10\.\d{4,9}/[^\s\"'<>]+", fm.get("doi", ""))
        year = re.search(r"(1[89]\d\d|20\d\d)", fm.get("doc-date", ""))
        abstract, abs_origin, keywords = abstract_and_keywords(note, body)
        lang, lang_conf = language(body or note)
        itype = fm.get("instrument-type", "unspecified")
        rows.append((
            rid, fm.get("title", ""), itype, itype in ACADEMIC,
            dois[0].rstrip(".,;").lower() if dois else None,
            int(year.group(1)) if year else None,
            fm.get("jurisdiction", ""), fm.get("container", ""),
            abstract, abs_origin, keywords, ingest_places(note),
            len(body), lang, lang_conf,
        ))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(OUT_DIR / "day09.duckdb"))
    con.execute("""CREATE OR REPLACE TABLE records (
        record_id VARCHAR PRIMARY KEY, title VARCHAR, itype VARCHAR,
        academic BOOLEAN, doi VARCHAR, year INTEGER, jurisdiction VARCHAR,
        container VARCHAR, abstract VARCHAR, abstract_origin VARCHAR,
        keywords VARCHAR, ingest_places VARCHAR, text_chars BIGINT,
        lang VARCHAR, lang_conf DOUBLE)""")
    con.executemany("INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    print(con.execute("""SELECT count(*) n, sum(academic::INT) academic,
        sum((academic AND doi IS NOT NULL)::INT) academic_doi,
        sum((academic AND abstract_origin='source')::INT) abs_source,
        sum((academic AND abstract_origin='ingest-note')::INT) abs_note,
        sum((academic AND abstract_origin='none')::INT) abs_none,
        sum((academic AND text_chars=0)::INT) no_text
        FROM records""").df().to_string(index=False))
    print(con.execute("""SELECT lang, count(*) n FROM records WHERE academic
        GROUP BY lang ORDER BY n DESC""").df().to_string(index=False))
    con.close()


if __name__ == "__main__":
    sys.exit(main())
