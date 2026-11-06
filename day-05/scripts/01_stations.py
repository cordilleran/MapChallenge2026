#!/usr/bin/env python3
"""
Task 1: Build data/derived/stations.csv (and copy to data/stations.csv) from ./in/mlp_locations/*.json.
Extracts every location record in the MLP files for the surveyed stations, classifies `use`
(`primary`, `excluded`, `repeat_with_coords`, `repeat_no_coords`), and computes projected
coordinates (x, y) in EPSG:3979 (NAD83(CSRS) / Canada Atlas Lambert).

Environment:
  MC26_DAY05_DIR          input data root directory (defaults to <repo_root>/../in if unset)
  MC26_MLP_LOCATIONS_DIR  folder holding mlp_locations/ (defaults to $MC26_DAY05_DIR/mlp_locations)
  MC26_SLICE_A_DIR        output slice_a root folder (defaults to $MC26_DAY05_DIR/slice_a)
"""
import csv
import json
import math
import os
from pathlib import Path
from osgeo import osr

osr.UseExceptions()

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()
MLP_DIR = Path(os.environ.get("MC26_MLP_LOCATIONS_DIR", str(DATA_DIR / "mlp_locations"))).resolve()
SLICE_A_DIR = Path(os.environ.get("MC26_SLICE_A_DIR", str(DATA_DIR / "slice_a"))).resolve()
DERIVED_DIR = SLICE_A_DIR / "derived"

def main():
    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    epsg3979 = osr.SpatialReference()
    epsg3979.ImportFromEPSG(3979)
    epsg3979.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    tx = osr.CoordinateTransformation(wgs84, epsg3979)

    # Order of stations: first the 6 Bridgland 1914 stations (84..89), then 1099 (Wheeler 1915 duplicate of Stn 86) and 2413 (Avion Ridge duplicate of Stn 87)
    station_order = [
        (2081, "84", "Bridgland 1914"),
        (1992, "85", "Bridgland 1914"),
        (2020, "86", "Bridgland 1914"),
        (2054, "87", "Bridgland 1914"),
        (2021, "88", "Bridgland 1914"),
        (2067, "89", "Bridgland 1914"),
        (1099, "86_dup_Wheeler1915", "Wheeler 1915 (Interprovincial Boundary Survey)"),
        (2413, "87_dup_AvionRidge", "Bridgland 1914 (unmatched duplicate node)"),
    ]

    rows = []
    for stn_id, stn_num, survey_note in station_order:
        sfile = MLP_DIR / f"station_{stn_id}.json"
        sdata = json.load(open(sfile, "r", encoding="utf-8"))["data"]
        smd = sdata["metadata"]
        sname = smd["name"]
        slat = smd.get("lat")
        slon = smd.get("lng")
        selev = smd.get("elev")
        sx, sy, _ = tx.TransformPoint(slon, slat)

        # Collect all modern visits and their location records
        visits = []
        for dep in sdata.get("dependents", []):
            if dep.get("type") == "modern_visits":
                v_id = dep["node"]["id"]
                v_date = dep.get("label", "")
                v_year = int(v_date[:4]) if v_date and v_date[:4].isdigit() else None
                for ldep in dep.get("dependents", []):
                    if ldep.get("type") == "locations":
                        lid = ldep["node"]["id"]
                        visits.append((v_date, v_year, v_id, lid, ldep.get("label", "")))

        # Sort visits chronologically by visit_date, then location_identity
        for v_date, v_year, v_id, lid, l_label in sorted(visits, key=lambda x: (x[0], x[3])):
            lfile = MLP_DIR / f"loc_{lid}.json"
            ldata = json.load(open(lfile, "r", encoding="utf-8"))["data"]
            lmd = ldata["metadata"]
            ident = lmd.get("location_identity")
            lat = lmd.get("lat")
            lon = lmd.get("lng")
            elev = lmd.get("elev")
            narr = (lmd.get("location_narrative") or "").replace("\r\n", " ").replace("\n", " ").strip()

            # Check capture-level coordinates if any
            mc_coords = []
            for mc in ldata.get("dependents", []):
                if mc.get("type") == "modern_captures":
                    mcmd = mc.get("metadata", {})
                    if mcmd.get("lat") is not None or mcmd.get("lng") is not None:
                        mc_coords.append((mc["node"]["id"], mcmd.get("lat"), mcmd.get("lng")))

            if lat is not None and lon is not None:
                x, y, _ = tx.TransformPoint(lon, lat)
                dist_m = math.hypot(x - sx, y - sy)
            else:
                x, y, dist_m = None, None, None

            # Determine `use` and `use_reason`
            use = ""
            reason = ""

            if stn_id == 1099:
                if lid == 10422:
                    use = "excluded"
                    reason = (
                        f"Impossible coordinates (lon={lon:.6f}, {dist_m/1000.0:.1f} km W in Washington State; "
                        f"corrupted UTM Easting '11706958' with zone '11' prepended to 706958). "
                        f"Also station 1099 is Arthur Oliver Wheeler 1915 survey, not Bridgland 1914 (use station 2020)."
                    )
                else:
                    use = "excluded_station_1099"
                    reason = (
                        "Station 1099 ('Sage Creek No. 1') belongs to Arthur Oliver Wheeler 1915 Interprovincial "
                        "Boundary Survey (owner_id=335); Bridgland 1914 Stn. 86 is MLP station 2020 (owner_id=377)."
                    )
            elif stn_id == 2413:
                use = "excluded_duplicate_station"
                reason = (
                    "Station 2413 ('Avion Ridge') is an unrepeated/unpaired duplicate station entry for "
                    "Stn. 87 Blakiston Divide (MLP station 2054)."
                )
            else:
                # One of the 6 primary Bridgland 1914 stations
                if lid == 51742:
                    use = "excluded"
                    reason = (
                        f"Impossible coordinates: lon={lon:.6f} (and capture lon=-113.903408) is {dist_m/1000.0:.2f} km "
                        f"east of Lost Mt (> 2 km threshold; degree/minute transcription error for -114.088225)."
                    )
                elif lid == 11072:
                    # Stn 2081 (84 Mt Blakiston): 2003-08-30 Loc 1
                    use = "primary"
                    reason = (
                        "Earliest repeat visit Location 1 with recorded decimal coordinates (2003-08-30 visit; "
                        "2004-08-10 visit Location 1 [loc_id=11592] has null coordinates in MLP API)."
                    )
                elif lid == 12418:
                    # Stn 1992 (85 Anderson): 2019-07-12 Loc 1
                    use = "primary"
                    reason = (
                        "Earliest repeat visit Location 1 with recorded decimal coordinates in MLP JSON (2019-07-12 visit; "
                        "2003-09-02 [loc_id=10983] and 2004-07-22 [loc_id=10980] have null lat/lon in JSON, though 2004 narrative gives UTM 11U 718312 5447152 = station coord)."
                    )
                elif lid == 12421:
                    # Stn 2020 (86 Sage Creek): 2019-07-13 Loc 1
                    use = "primary"
                    reason = (
                        "Earliest repeat visit Location 1 with recorded decimal coordinates (2019-07-13 visit; "
                        "2004-09-04 visit Location 1 [loc_id=11535] has null coordinates in MLP API)."
                    )
                elif lid == 11593:
                    # Stn 2054 (87 Blakiston Divide): 2004-09-06 Loc 1
                    use = "primary"
                    reason = "Location 1 of the 2004 repeat visit (2004-09-06)."
                elif lid == 11017:
                    # Stn 2021 (88 Lost Mt): 2004-07-25 Loc 1
                    use = "primary"
                    reason = (
                        "Location 1 of the 2004 repeat visit (2004-07-25; note: 192.8 m north of the true summit cairn "
                        "recorded in 2019 Location 1 [loc_id=12436] and station metadata)."
                    )
                elif lid == 11488:
                    # Stn 2067 (89 Lone Mt): 2004-08-06 Loc 1
                    use = "primary"
                    reason = "Location 1 of the 2004 repeat visit (2004-08-06)."
                elif lat is None or lon is None:
                    use = "no_coords"
                    if lid in (11592, 10980, 11535):
                        reason = f"2004 visit Location 1 has null lat/lon in MLP API location record (see primary row for station {stn_id})."
                    elif lid == 47402:
                        reason = "Location-level lat/lon is null in MLP API (modern captures have EXIF GPS ~49.104162, -114.124012)."
                    else:
                        reason = "Null lat/lon in MLP API location record."
                else:
                    # Has coordinates, check if any capture inside has bad coords or if location is shifted
                    if lid in (51702, 51704, 51705):
                        use = "secondary_shifted"
                        extra = " (also 3 captures in loc 51702 have typo lat=48.138378 in Montana, ~111 km south)" if lid == 51702 else ""
                        reason = f"2025 repeat visit location is {dist_m:.1f} m east of station cairn (~1.0 km shift, < 2 km threshold){extra}."
                    else:
                        use = "secondary"
                        reason = f"Repeat visit location (ident={ident}, {v_year}); {dist_m:.1f} m from station metadata coordinate."

            rows.append({
                "station_num": stn_num,
                "mlp_station_id": stn_id,
                "station_name": sname,
                "visit_id": v_id,
                "visit_date": v_date,
                "visit_year": v_year,
                "location_id": lid,
                "location_identity": ident,
                "lat": f"{lat:.8f}" if lat is not None else "",
                "lon": f"{lon:.8f}" if lon is not None else "",
                "recorded_elevation_m": elev if elev is not None else "",
                "x_epsg3979": f"{x:.2f}" if x is not None else "",
                "y_epsg3979": f"{y:.2f}" if y is not None else "",
                "station_lat": f"{slat:.8f}" if slat is not None else "",
                "station_lon": f"{slon:.8f}" if slon is not None else "",
                "station_elev_m": selev if selev is not None else "",
                "station_x_epsg3979": f"{sx:.2f}",
                "station_y_epsg3979": f"{sy:.2f}",
                "dist_from_station_m": f"{dist_m:.1f}" if dist_m is not None else "",
                "use": use,
                "use_reason": reason,
                "notes": narr,
            })

    fieldnames = list(rows[0].keys())
    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    SLICE_A_DIR.mkdir(parents=True, exist_ok=True)
    outpaths = [DERIVED_DIR / "stations.csv", SLICE_A_DIR / "stations.csv"]
    for outpath in outpaths:
        with open(outpath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    print(f"Wrote {len(rows)} location records to {outpaths[0]} and {outpaths[1]}")
    for r in rows:
        if r["use"] in ("primary", "excluded"):
            print(f"  [{r['use']:8s}] Stn {r['station_num']} ({r['mlp_station_id']}) loc_id={r['location_id']} ({r['visit_year']} Loc {r['location_identity']}): lat={r['lat']}, lon={r['lon']}, x={r['x_epsg3979']}, y={r['y_epsg3979']} | {r['use_reason']}")

if __name__ == "__main__":
    main()
