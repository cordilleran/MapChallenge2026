"""Day 9: one origin set per author (D118).

OpenAlex often attaches a parent body and the actual unit to the same author
("European Commission", Brussels, beside "Joint Research Centre", Ispra). For
each author, keep the institutions whose city or country name appears in that
author's raw affiliation string; if none match, keep them all. Weights:
all-author view 1 / (n_authors x kept), corresponding view 1 / kept, so every
paper sums to 1 in either view.

The corresponding view takes one author per paper: the first one OpenAlex
flags as corresponding (it sometimes flags dozens), or else the first located
author.

Usage: python 06_origins.py
"""
import os
import sys
from pathlib import Path

import duckdb

OUT_DIR = Path(os.environ.get("MC26_DAY09_DIR") or sys.exit("Set MC26_DAY09_DIR to the Day 9 data folder (see README)."))
GEONAMES = Path(os.environ.get("MC26_GEONAMES") or sys.exit("Set MC26_GEONAMES to the GeoNames download folder (see README)."))


def main():
    con = duckdb.connect(str(OUT_DIR / "day09.duckdb"))
    ci = GEONAMES / "countryInfo.txt"
    con.execute(f"""CREATE OR REPLACE TEMP TABLE cname AS
        SELECT iso, lower(name) AS cname FROM read_csv('{ci}', delim='\t', header=false, quote='',
            all_varchar=true, null_padding=true) t(iso, iso3, isonum, fips, name, capital, area, pop,
            continent, tld, cur, curname, phone, pfmt, pregex, langs, geonameid, neighbours, efips)
        WHERE NOT starts_with(iso, '#')""")
    con.execute("""
    CREATE OR REPLACE TABLE origins AS
    WITH a AS (
        SELECT r.record_id, a.doi, a.author_idx, a.n_authors, a.is_corresponding, a.author,
               a.raw_affiliation, i.inst_id, i.name AS inst, i.country, i.city, i.lat, i.lon,
               coalesce((i.city IS NOT NULL AND contains(lower(a.raw_affiliation), lower(i.city)))
                        OR (c.cname IS NOT NULL AND contains(lower(a.raw_affiliation), c.cname)), false) AS named
        FROM records r JOIN oa_authorships a ON a.doi = r.doi
        JOIN oa_institutions i ON i.inst_id = a.inst_id
        LEFT JOIN cname c ON c.iso = i.country
        WHERE r.academic AND i.lat IS NOT NULL),
    k AS (
        SELECT *, bool_or(named) OVER (PARTITION BY record_id, author_idx) AS any_named FROM a),
    kept AS (
        SELECT * EXCLUDE (any_named), CASE WHEN named THEN 'named' ELSE 'all' END AS pick
        FROM k WHERE named OR NOT any_named),
    corr AS (
        SELECT record_id, coalesce(min(author_idx) FILTER (WHERE is_corresponding), min(author_idx)) AS corr_idx
        FROM kept GROUP BY record_id)
    SELECT kept.*, count(*) OVER (PARTITION BY kept.record_id, kept.author_idx) AS n_kept,
           1.0 / (greatest(kept.n_authors, 1) * count(*) OVER (PARTITION BY kept.record_id, kept.author_idx)) AS w_all,
           kept.author_idx = corr.corr_idx AS corr_view,
           1.0 / count(*) OVER (PARTITION BY kept.record_id, kept.author_idx) AS w_corr
    FROM kept JOIN corr USING (record_id)
    """)
    print(con.execute("""SELECT pick, count(*) AS rows, count(DISTINCT doi || author_idx) AS authors
                         FROM origins GROUP BY 1""").df().to_string(index=False))
    print(con.execute("""SELECT count(DISTINCT record_id) AS records,
            count(DISTINCT CASE WHEN corr_view THEN record_id END) AS with_corr,
            round(max(abs(s - 1)), 6) AS max_sum_dev_located
        FROM origins JOIN (SELECT record_id, sum(w_corr) FILTER (WHERE corr_view) AS s
                           FROM origins GROUP BY record_id) USING (record_id)""").df().to_string(index=False))
    con.close()


if __name__ == "__main__":
    sys.exit(main())
