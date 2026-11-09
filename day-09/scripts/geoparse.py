"""Reusable place-candidate extraction (Day 9; meant to become a library tool, D110).

Pure Python, no model: capitalized word runs and their sub-runs, with offsets,
and the common-word list that guards single-word matches.
"""
import re
from pathlib import Path
import os

WORDS = Path(os.environ.get("MC26_WORDLIST", "/usr/share/dict/american-english"))

JOINERS = {"of", "de", "del", "la", "le", "du", "the", "and", "upon", "on", "sur"}
EXEMPT = ("PCLI", "PCLD", "PCLF", "PCLS", "PCLIX", "TERR", "ADM1", "CONT", "OCN", "SEA", "PPLC")
TOKEN = re.compile(r"[^\s()\[\]{},;:\"“”]+")

def common_words():
    """Lowercase dictionary words: a capitalized single word that is also one
    of these ("Most", "Long", "Turkey") needs a stronger cue to count."""
    if not WORDS.exists():
        return set()
    return {w.strip() for w in WORDS.read_text(errors="ignore").split("\n") if w.islower()}


def _cap(tok):
    """Capitalized in any script: Åland, Łódź and Örebro count (review finding 9)."""
    return tok[:1].isupper()


def subruns(text):
    """Yield (surface, start, end) for every 1-5 word sub-run of each run of
    capitalized tokens (joiners such as "of" allowed inside a run).

    Trailing punctuation is stripped from the surface, so "U.S." is looked up
    as "u.s"; gazetteer keys are stored the same way (review finding 2)."""
    toks = [(m.group(), m.start(), m.end()) for m in TOKEN.finditer(text)]
    runs, cur = [], []
    for t in toks:
        if cur and text[cur[-1][2]:t[1]].strip():
            runs.append(cur)  # punctuation between tokens ends a run
            cur = []
        if _cap(t[0]):
            cur.append(t)
        elif cur and t[0] in JOINERS:
            cur.append(t)
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    for run in runs:
        while run and not _cap(run[-1][0]):
            run = run[:-1]
        for i in range(len(run)):
            if not _cap(run[i][0]):
                continue
            for j in range(i + 1, min(i + 6, len(run) + 1)):
                if not _cap(run[j - 1][0]):
                    continue
                s, e = run[i][1], run[j - 1][2]
                surface = re.sub(r"[’']s$", "", text[s:e]).rstrip(".,;:’'")  # "Canada's" (D119)
                if surface:
                    yield surface, s, s + len(surface)


def norm_key(name):
    """The lookup key used on both sides: lowercase, trailing dots stripped."""
    return name.lower().rstrip(".,;:’'")


# Surfaces that match a gazetteer entry but are almost never a place in a paper:
# directions, adjectives, demonyms, phenomena, methods. Checked case-insensitively.
STOP_SURFACES = {
    "north", "south", "east", "west", "northern", "southern", "eastern", "western", "central",
    "centre", "center", "forest", "american", "indian", "english",
    "el niño", "el nino", "monte", "la niña", "la nina", "niño", "nin", "monte carlo", "sar", "west coast",
    "east coast", "gulf", "island", "valley", "river", "lake", "mount", "victoria university",
    "bayes", "markov", "gaussian", "poisson", "pearson", "nash", "darcy", "manning",
    # months and generic admin-area names that are ordinary words in a paper (D117)
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december",
    "northeast", "northwest", "southeast", "southwest", "capital", "coast", "interior", "delta",
    "rivers", "islands", "lakes", "littoral", "maritime", "plateau", "plateaux", "equator",
    "union", "unity", "trinity", "oriental", "occidental", "amazon", "google",
    "meridional", "montane", "siri",
}

# Feature codes that pass the common-word and short-name guards: country-like,
# continents, oceans, first-order admin areas, capitals and admin seats
# ("Lima", "Georgia"; review finding 10). False positives here are
# recoverable by the role call; false negatives are not.
# Single-word features of these codes count only when their country is already
# in the record's context: "Carlo", "Stan" and "James" are rivers and peaks
# somewhere (D117).
# Single-word peaks and named areas never count from text: in Canada the AREA
# names are mostly surnames ("Benoit", "Pelletier") and lone MT names are first
# names ("Carlo") (D117). Multi-word forms ("Mount Robson") still match.
NEVER_SINGLE = ("MT", "AREA")

CONTEXT_ONLY = ("STM", "MT", "MTS", "LK", "RSV", "GLCR", "BAY", "VAL", "PEN", "ISL", "ISLS",
                "PLAT", "AREA", "RGN", "PRK")

COUNTRYLIKE = ("PCLI", "PCLD", "PCLF", "PCLS", "PCLIX", "TERR", "CONT", "OCN", "SEA",
               "ADM1", "PPLC", "PPLA")


# The common-word guard is stricter than the short-name guard: only countries,
# continents, oceans and capitals pass it ("Turkey", "China", "Lima"); an admin
# area or seat that is a dictionary word ("Store", "Bay", "Pool") does not (D117).
WORD_PASS = ("PCLI", "PCLD", "PCLF", "PCLS", "PCLIX", "TERR", "CONT", "OCN", "SEA", "PPLC")
WORD_ALLOW = {"wales"}


# Demonyms that name a country or continent; the role call decides whether the
# paper studies it ("Canadian cities") or only mentions it (D119). "American",
# "English" and "Indian" are too ambiguous and stay stop words.
DEMONYMS = {
    "canadian": "canada", "australian": "australia", "european": "europe", "british": "united kingdom",
    "chinese": "china", "japanese": "japan", "german": "germany", "french": "france",
    "african": "africa", "asian": "asia", "spanish": "spain", "mexican": "mexico",
    "brazilian": "brazil", "italian": "italy", "dutch": "the netherlands", "swedish": "sweden",
    "norwegian": "norway", "finnish": "finland", "danish": "denmark", "austrian": "austria",
    "korean": "south korea", "chilean": "chile", "argentine": "argentina", "argentinian": "argentina",
    "peruvian": "peru", "colombian": "colombia", "icelandic": "iceland", "irish": "ireland",
    "scottish": "scotland", "welsh": "wales", "antarctic": "antarctica", "nepalese": "nepal",
    "bangladeshi": "bangladesh", "pakistani": "pakistan", "vietnamese": "vietnam", "thai": "thailand",
    "indonesian": "indonesia", "kenyan": "kenya", "ethiopian": "ethiopia", "nigerian": "nigeria",
    "ghanaian": "ghana", "south african": "south africa", "egyptian": "egypt", "turkish": "turkey",
    "iranian": "iran", "greek": "greece", "portuguese": "portugal", "polish": "poland",
    "czech": "czechia", "hungarian": "hungary", "romanian": "romania", "russian": "russia",
    "ukrainian": "ukraine", "new zealand": "new zealand",
}


def keep_surface(surface, fcode, words):
    """True if a matched surface is plausible as a place name."""
    low = surface.lower()
    if low in STOP_SURFACES:
        return False
    if low == "us" and surface != "US":
        return False  # the pronoun (D119)
    if " " not in low and surface.isupper() and fcode not in COUNTRYLIKE:
        return False  # an acronym (NASA, FEMA) unless it names a country-level place (USA)
    if " " not in low and len(low) < 4 and fcode not in COUNTRYLIKE:
        return False
    if " " not in low and low in words and fcode not in WORD_PASS and low not in WORD_ALLOW:
        return False
    return True
