"""Day 9 slice S3a: build the gazetteer table from a GeoNames dump.

Keeps the features a research paper is likely to name: countries and
territories, first- and second-order admin areas, continents and regions,
populated places of 1,000 people or more (and every capital or admin seat),
and named water bodies, landforms and parks. Single-word water and landform
names are kept ("Nile", "Okanagan"); the common-word guard in
geoparse.keep_surface drops ordinary words such as "Long" and "Bear".

Each name gets an importance score used only to rank homonyms.

Usage:
    python 03_gazetteer.py            # GeoNames folder from MC26_GEONAMES
"""
import os
import sys
from pathlib import Path

import duckdb

from geoparse import DEMONYMS, common_words

GEONAMES = Path(os.environ.get("MC26_GEONAMES") or sys.exit("Set MC26_GEONAMES to the GeoNames download folder (see README)."))
OUT_DIR = Path(os.environ.get("MC26_DAY09_DIR") or sys.exit("Set MC26_DAY09_DIR to the Day 9 data folder (see README)."))

# Feature weights for ranking homonyms (higher wins when names tie).
WEIGHT = """
SELECT * FROM (VALUES
 ('CONT',12),('PCLI',11),('PCLD',10),('PCLF',10),('PCLS',10),('PCLIX',9),('TERR',9),
 ('ADM1',9),('RGN',6),('ADM2',6),('PPLC',8),('PPLA',7),('PPLA2',5),('OCN',10),('SEA',8),
 ('GULF',7),('BAY',4),('STM',5),('LK',4),('RSV',4),('GLCR',4),('MTS',6),('MT',4),
 ('PEN',5),('ISL',4),('ISLS',5),('VAL',3),('PLAT',5),('PRK',4),('AREA',3)
) t(fcode, w)
"""


def main():
    src = GEONAMES / "allCountries.txt"
    if not src.exists():
        sys.exit(f"missing {src}")
    con = duckdb.connect(str(OUT_DIR / "day09.duckdb"))
    con.execute(f"""
    CREATE OR REPLACE TABLE geonames_raw AS
    SELECT * FROM read_csv('{src}', delim='\t', header=false, quote='', escape='',
        columns={{'geonameid':'BIGINT','name':'VARCHAR','asciiname':'VARCHAR',
                 'alternatenames':'VARCHAR','lat':'DOUBLE','lon':'DOUBLE',
                 'fclass':'VARCHAR','fcode':'VARCHAR','country':'VARCHAR','cc2':'VARCHAR',
                 'admin1':'VARCHAR','admin2':'VARCHAR','admin3':'VARCHAR','admin4':'VARCHAR',
                 'population':'BIGINT','elevation':'VARCHAR','dem':'VARCHAR',
                 'timezone':'VARCHAR','modified':'VARCHAR'}})
    WHERE (fclass = 'A' AND fcode IN ('PCLI','PCLD','PCLF','PCLS','PCLIX','TERR','ADM1','ADM2'))
       OR (fclass = 'L' AND fcode IN ('CONT','RGN','PRK','AREA'))
       OR (fclass = 'P' AND (population >= 1000 OR fcode IN ('PPLC','PPLA','PPLA2')))
       OR (fclass IN ('H','T') AND fcode IN ('OCN','SEA','GULF','BAY','STM','LK','RSV','GLCR',
                                             'MTS','MT','PEN','ISL','ISLS','VAL','PLAT'))
    """)
    # One row per searchable name: the official name and the ASCII form.
    # Single-word water and landform names are kept ("Nile", "Okanagan"; review
    # finding 11); the common-word guard in geoparse.keep_surface drops "Bear" and "Long".
    # Dictionary words, so an alternate name that is an ordinary word ("Some" for
    # Finland, "Pain", "Coast") is not indexed (S3 rerun, D117).
    con.execute("CREATE OR REPLACE TEMP TABLE common_word (w VARCHAR PRIMARY KEY)")
    con.executemany("INSERT INTO common_word VALUES (?)", [(w,) for w in sorted(common_words())])
    con.execute(f"""
    CREATE OR REPLACE TABLE gazetteer AS
    WITH w AS ({WEIGHT}),
    names AS (
        SELECT geonameid, name AS nm FROM geonames_raw
        UNION SELECT geonameid, asciiname FROM geonames_raw
        -- English exonyms ("Munich", "Rome", "Vienna") live in alternatenames;
        -- keep ASCII-only alternates for the features papers name most (review finding 12).
        -- Alternates must be 4+ characters with a lowercase letter (airport and
        -- country codes such as "THE" for Teresina are all capitals) and not a
        -- dictionary word (D117).
        UNION SELECT geonameid, alt FROM (
            SELECT geonameid, trim(unnest(string_split(alternatenames, ','))) AS alt FROM geonames_raw
            WHERE fcode IN ('PCLI','PCLD','PCLF','PCLS','PCLIX','TERR','ADM1','CONT','OCN','SEA','PPLC')
               OR (fclass = 'P' AND population >= 500000))  -- mid-size cities carry first names as alternates ("Julia")
        WHERE length(alt) >= 4 AND regexp_matches(alt, '[a-z]')
          AND lower(alt) NOT IN (SELECT w FROM common_word)
    )
    SELECT DISTINCT rtrim(lower(n.nm), '.,;:’' || chr(39)) AS key, g.geonameid, g.name, g.fclass, g.fcode,
           g.country, g.admin1, g.lat, g.lon, g.population,
           coalesce(w.w, 2) + ln(1 + coalesce(g.population, 0)) / 3
             - CASE WHEN n.nm IN (g.name, g.asciiname) THEN 0 ELSE 3 END AS importance  -- a place's own name beats another's alternate ("Philadelphia" is also Amman; D120)
    FROM names n JOIN geonames_raw g USING (geonameid)
    LEFT JOIN w ON w.fcode = g.fcode
    WHERE length(n.nm) >= 3 AND regexp_matches(n.nm, '^[^0-9]+$')
      AND (n.nm IN (g.name, g.asciiname) OR regexp_matches(n.nm, '^[A-Za-z][A-Za-z .' || chr(39) || '-]+$'))
    """)
    # Country and admin1 aliases a paper uses that GeoNames' primary names miss.
    con.execute("""
    INSERT INTO gazetteer
    SELECT a.key, g.geonameid, g.name, g.fclass, g.fcode, g.country, g.admin1, g.lat, g.lon,
           g.population, 11
    FROM (VALUES ('usa','US'),('us','US'),('u.s','US'),('u.s.a','US'),('united states of america','US'),
                 ('uk','GB'),('u.k','GB'),('britain','GB'),('great britain','GB'),('prc','CN')) a(key, cc)
    JOIN geonames_raw g ON g.country = a.cc AND g.fcode = 'PCLI'
    """)
    con.execute("""
    INSERT INTO gazetteer
    SELECT a.key, g.geonameid, g.name, g.fclass, g.fcode, g.country, g.admin1, g.lat, g.lon,
           g.population, 9
    FROM (VALUES ('bc','CA','02'),('b.c','CA','02'),('ab','CA','01'),('alta','CA','01'),
                 ('ont','CA','08'),('que','CA','10'),('wa','US','WA'),('calif','US','CA'))
         a(key, cc, a1)
    JOIN geonames_raw g ON g.country = a.cc AND g.admin1 = a.a1 AND g.fcode = 'ADM1'
    """)
    # Short country names from countryInfo ("Australia", not "Commonwealth of Australia").
    ci = GEONAMES / "countryInfo.txt"
    con.execute(f"""
    INSERT INTO gazetteer
    SELECT lower(c.name), g.geonameid, c.name, g.fclass, g.fcode, g.country, g.admin1, g.lat, g.lon,
           g.population, 12
    FROM read_csv('{ci}', delim='\t', header=false, quote='', all_varchar=true,
                  null_padding=true) t(iso, iso3, isonum, fips, name, capital, area, pop, continent,
                  tld, cur, curname, phone, pfmt, pregex, langs, geonameid, neighbours, efips)
    CROSS JOIN LATERAL (SELECT t.name) c(name)
    JOIN geonames_raw g ON g.geonameid = TRY_CAST(t.geonameid AS BIGINT)
    WHERE NOT starts_with(t.iso, '#')  -- header lines; '#' also appears inside postcode formats
    """)
    # Short admin1 names from admin1CodesASCII ("Victoria", not "State of Victoria").
    a1 = GEONAMES / "admin1CodesASCII.txt"
    con.execute(f"""
    INSERT INTO gazetteer
    SELECT k.key, g.geonameid, t.name, g.fclass, g.fcode, g.country, g.admin1, g.lat, g.lon,
           g.population, 10
    FROM read_csv('{a1}', delim='\t', header=false, quote='', all_varchar=true)
         t(code, name, asciiname, geonameid)
    JOIN geonames_raw g ON g.geonameid = TRY_CAST(t.geonameid AS BIGINT)
    CROSS JOIN LATERAL (SELECT DISTINCT unnest([lower(t.name), lower(t.asciiname)]) AS key) k
    """)
    # Bare ocean names, which papers use without "Ocean".
    con.execute("""
    INSERT INTO gazetteer
    SELECT a.key, g.geonameid, g.name, g.fclass, g.fcode, g.country, g.admin1, g.lat, g.lon,
           g.population, 9
    FROM (VALUES ('atlantic','Atlantic Ocean'),('pacific','Pacific Ocean'),('arctic','Arctic Ocean'),
                 ('arctic ocean','Arctic Ocean')) a(key, oname)
    JOIN geonames_raw g ON g.name = a.oname AND g.fcode = 'OCN'
    """)
    # Major regions and rivers whose bare names collide with small towns the
    # context or corpus prior would otherwise pick ("Ganges", BC; "Middle East", US) (D120).
    con.execute("""
    INSERT INTO gazetteer
    SELECT a.key, g.geonameid, g.name, g.fclass, g.fcode, g.country, g.admin1, g.lat, g.lon,
           g.population, 25  -- above any homonym plus context and prior
    FROM (VALUES ('middle east','Middle East','RGN',NULL),('ganges','Ganges','STM','IN'),
                 ('labrador','Newfoundland and Labrador','ADM1','CA'),
                 ('indus','Indus River','STM',NULL),('brahmaputra','Brahmaputra River','STM',NULL)) a(key, nm, fc, cc)
    JOIN geonames_raw g ON g.name = a.nm AND g.fcode = a.fc AND (a.cc IS NULL OR g.country = a.cc)
    QUALIFY row_number() OVER (PARTITION BY a.key ORDER BY g.population DESC NULLS LAST) = 1
    """)
    # Demonyms point at the best country, continent or admin1 row for the name (D119).
    con.execute("CREATE OR REPLACE TEMP TABLE demonym (key VARCHAR, target VARCHAR)")
    con.executemany("INSERT INTO demonym VALUES (?,?)", list(DEMONYMS.items()))
    con.execute("""
    INSERT INTO gazetteer
    SELECT d.key, g.geonameid, g.name, g.fclass, g.fcode, g.country, g.admin1, g.lat, g.lon,
           g.population, g.importance
    FROM demonym d JOIN gazetteer g ON g.key = d.target
    WHERE g.fcode IN ('PCLI','PCLD','PCLF','PCLS','PCLIX','TERR','CONT','ADM1')
    QUALIFY row_number() OVER (PARTITION BY d.key ORDER BY g.importance DESC) = 1
    """)
    # One row per (key, place): duplicates from the alias inserts would make a
    # place its own alternative downstream (review findings 4 and 7).
    con.execute("""CREATE OR REPLACE TABLE gazetteer AS
                   SELECT key, geonameid, any_value(name) AS name, any_value(fclass) AS fclass,
                          any_value(fcode) AS fcode, any_value(country) AS country, any_value(admin1) AS admin1,
                          any_value(lat) AS lat, any_value(lon) AS lon, any_value(population) AS population,
                          max(importance) AS importance
                   FROM gazetteer GROUP BY key, geonameid""")
    con.execute("CREATE INDEX IF NOT EXISTS gaz_key ON gazetteer(key)")
    print(con.execute("""SELECT fclass, count(*) AS n_names, count(DISTINCT geonameid) AS n_places
                         FROM gazetteer GROUP BY fclass ORDER BY n_names DESC""").df().to_string(index=False))
    con.execute("DROP TABLE geonames_raw")
    con.close()


if __name__ == "__main__":
    sys.exit(main())
