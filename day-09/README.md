# Day 9: Written in cities, looking out

Place of study: one reader's look at a geography of interests. A world map of one personal research library: each line joins the institution a paper was written from to the place it studies, for 1,815 academic papers. Colour is the setting each paper states about its own study (urban, rural or mixed), read from a quoted sentence in the paper; shape is the kind of place (an area, a natural feature, a settlement). A table of origin regions (World Bank regions, or UN M49 subregions) by setting and a table of OpenAlex topics sit below the map, count every paper, and filter it.

Live: <https://cordilleran.github.io/MapChallenge2026/day09/>

Origins come from OpenAlex author affiliations. Places of study come from two layers: names in the title, abstract and keywords matched to GeoNames (layer 1), and a body reading by a small language model (Claude Haiku) that may name a place or a setting only with a 5 to 25 word quotation found verbatim in the text (layer 2). GHS-SMOD and GHS-POP give context: the settlement class of each institution and point place, and how each country's or province's people split between urban centres, towns and rural areas. They never set the class; the paper does.

## Public and private builds

The public page is a coarsened view. `scripts/14_app_export.py` writes it by default; two flags change what is written:

| Build | Command | Where it lives |
| :--- | :--- | :--- |
| Public (coarsened) | `python 14_app_export.py` | `app/data/day09.json`, in the repository and on the site |
| Exact | `python 14_app_export.py --exact` | same file; for local use, do not publish without thinking about it |
| Private | `python 14_app_export.py --private` | adds `app/data/day09_private.json`, gitignored, never published |

What the public build hides, and why:

- **No titles, cite keys, DOIs or record ids.** Papers are numbered rows; nothing on the site names a paper. The private file maps those numbers back to cite keys and titles, and the app lists them when you select a place, a region or a topic (only when the file is present).
- **Years in five-year bins.**
- **Places studied by one paper only are merged into their province or country,** whether a point (a town, a lake) or a smaller area (a county, a range, a park), so a single field site cannot be traced to a single paper. Places no paper links to are not published.
- **Topic labels:** each paper carries only its primary OpenAlex topic, subfield and field, and only where three or more papers share the label. Keywords are not published.
- **No evaluation data.** The 60-record gold set, its ids and every score file stay local (`.gitignore`); tests that need them skip with a message.
- **What it does not hide:** a paper's row still links its authors' institutions, a five-year bin, a topic and its places of study. A determined reader with OpenAlex could match many rows to real papers, so the public build hides the list by name, not by design against re-identification. Use the private build, served to the team only, when the list itself is sensitive.
- The library itself (full texts, abstracts, notes) never leaves the machine. Only titles, abstracts, keywords, candidate place names and the opening and study-area sections were sent to the model.

## Using it for your own library or team

The pipeline is built so a second corpus needs only a loader. It is most useful as an **internal review**: a researcher or a group looking at the geography of what they read, cite or write, with the private build switched on and served only to the team.

1. **Records.** `01_records.py` reads one folder per record from `MC26_LIBRARY`: a Markdown note with YAML frontmatter (DOI, title, item type, container) and a `<id>.source.md` full text, from which it takes the abstract and keywords. Replace it with a reader for your own export (Zotero, a BibTeX file with PDFs, an OpenAlex query) that fills the same `records` table. Nothing downstream reads the library directly.
2. **Run 02 to 15 in order** (table below). Steps 07 and 12 call Claude Haiku through the Claude CLI: about $0.70 and $2.40 at API rates for 1,800 papers. Everything else is local.
3. **Build privately:** `python 14_app_export.py --private --exact`, then `app/serve.sh`. It binds to localhost and the Tailscale address only, not the LAN, so the team sees cite keys and exact places and nothing is public.
4. **Check before you trust it.** Draw a gold set (`08_gold_sample.py`), label it by hand (someone other than the model family that extracted it, ideally), and score it (`09_score_gold.py`, `13_probe_report.py`). Our numbers do not transfer to your corpus.
5. **Publishing a team view** is a separate decision: use the default coarsened build and read the list above first.

What it can and cannot tell a team: it shows where the team's reading comes from and what it looks at; it does not measure a field. To ask about a field, compare against a sample of the same subfields from OpenAlex.

## Data and Licences

- OpenAlex works, authorships, institutions, topics and keywords, read from the public API (polite pool) on 8 November 2026. CC0.
- GeoNames gazetteer (allCountries, countryInfo, admin1CodesASCII), downloaded 8 November 2026. CC BY 4.0.
- GHS-SMOD R2023A and GHS-POP R2023A, epoch 2020, 1 km, Mollweide (European Commission, Joint Research Centre). CC BY 4.0.
- Natural Earth 1:50m admin-0 countries, land and lakes, 1:10m admin-1 states and provinces. Public domain.
- The library records themselves (titles, abstracts, keywords, full texts) stay local. Sent to the model (Claude Haiku): candidate place names with short context windows, titles, abstracts and keywords (layer 1, D107), and the opening and one study-area or methods section of each paper, about 8,500 characters (layer 2, D127). The published `site/day09/data/day09.json` holds institutions, places, aggregated weights, OpenAlex topic labels and the short setting phrases, not paper titles, cite keys or record ids.

## Pipeline

Copy `env.example` to `.env` (gitignored) and load it before running the scripts (`set -a; . ./.env; set +a`). `MC26_DAY09_DIR` (the working folder), `MC26_LIBRARY` (the library, read only, never written) and `MC26_GEONAMES` (the GeoNames download) are required; a script stops with a message if one is missing. Raw downloads go to dated folders that are never overwritten.

| Script | What it does | Needs network | Approximate run time |
| :--- | :--- | :--- | :--- |
| `01_records.py` | Reads library records into `records`; flags academic types; detects language. | No | ~10 s |
| `02_openalex.py` | OpenAlex works (all authorships) and institutions for every academic DOI, 50 per call. | Yes | ~1 min |
| `02b_openalex_topics.py` | OpenAlex topics and keywords for the hover labels (D112). | Yes | ~30 s |
| `03_gazetteer.py` | Filters GeoNames into `gazetteer` with aliases, demonyms, curated major features and an alternate-name penalty (D117, D119, D120). | No (files downloaded by hand) | ~15 s |
| `04_candidates.py` | Capitalised word runs in title, abstract and keywords matched to the gazetteer; homonyms ranked by feature type, author countries, unambiguous places in the same text and a corpus prior; writes `mentions_l1`. | No | ~30 s |
| `05_timing_sample.py` | Times the layer 2 role call on a sample (Gemma via Ollama, Haiku via the Claude CLI) into `timing.duckdb` (D116). | Haiku only | minutes |
| `06_origins.py` | One origin set per author: institutions named in the author's affiliation text; corresponding view (D118). | No | < 1 s |
| `07_roles.py` | Haiku role and scope call per record into `roles.duckdb`; `--changed` re-asks only records whose candidates changed; `--merge` writes `roles` and `scopes`. | Yes (Claude) | ~25 min, about $0.70 |
| `08_gold_sample.py` | Draws the 60-record gold set and a labelling packet. | No | < 1 s |
| `09_score_gold.py` | Scores scope, places of study and the ingest Places line against `tests/gold_labels.json`. | No | < 1 s |
| `10_places.py` | `places` (urban-rural class, regions, North-South lenses), `papers`, `arcs`. | No | ~10 s |
| `11_export.py` | Writes `site/data/day09.js` (the first, held canvas version of the page; superseded by the app, D128). | No | ~10 s |
| `12_body_probe.py` | Body-text pass: Haiku reads the opening and the study-area or methods section and returns scope, places of study (each with a verbatim quote that must be found in the text) and the study's setting (urban, rural, mixed). `--all` for every record, `--verify` to check the quotes (D123, D127). | Yes (Claude) | ~40 min for 1,800 records |
| `13_probe_report.py` | Scores the body pass against the local gold set, if present. | No | < 1 s |
| `14_app_export.py` | Writes the app's data contract `app/data/day09.json` (coarsened by default), province outlines, and with `--private` a local-only file of cite keys (D128). | No | ~20 s |
| `15_area_settlement.py` | Land and population shares by settlement class for every country and province (GHS-SMOD and GHS-POP; system Python with GDAL). | No | ~1 min |

The app is in `app/` (see its README): static files, no libraries, served with `app/serve.sh`. `scripts/16_world_regions.py` adds the World Bank region column to the world outlines; `scripts/18_border_lines.py` writes the border lines (only edges two countries or two provinces share on land, so coasts carry no border line) and the lakes; `scripts/17_site_copy.sh` copies the public app into `site/day09/` (never the private file).

Tests: `tests/test_positive.py` (three hand-set cases: a BC field site, a global synthesis from the JRC, an algorithm paper), run after 04, 06 and the role-call merge; `app/tests/core.test.mjs` (`npm test` in `app/`). The 60-record gold set and its scores stay local (D129).

## Limits

The body pass reads the opening and one study-area or methods section of each paper (about 8,500 characters), not the whole text; papers without a DOI have no origin yet; one reader's library, chosen by interest. See the page for the full list.
