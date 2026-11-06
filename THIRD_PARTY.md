# Third-party data, software and fonts

## Data used for the published maps
- **BC Freshwater Atlas** (stream network, watershed group KETL), Province of British Columbia, BC Data Catalogue. *Contains information licensed under the Open Government Licence - British Columbia.* <https://www2.gov.bc.ca/gov/content?id=A519A56BC2BF44E4A008B33FCF527F61>
- **BC Watershed Atlas 1:50,000 watersheds** ("Third-order and greater watersheds"), Province of British Columbia. *Contains information licensed under the Open Government Licence - British Columbia.* Used to cut the basin into local units that give the basin footprint for the US clip; not redistributed.
- **USGS 3D Hydrography Program (3DHP)** flowlines, U.S. Geological Survey. U.S. government work, public domain. <https://www.usgs.gov/3d-hydrography-program>
- **Elevation:** a 30 m digital elevation model assembled by the author from the Canadian Digital Elevation Model (Natural Resources Canada; contains information licensed under the Open Government Licence - Canada) and the USGS 3D Elevation Program (3DEP) 1/3 arc-second DEM (U.S. Geological Survey, public domain). Used to check line direction, measure upstream area (pruning and the map readout) and outline the basin; the DEM itself is not redistributed. The shaded-relief image on the Leaflet page (`site/img/day01_relief.jpg`) is made from it.

## Data used only in the exploration scripts (`day-01/exploration/`), not redistributed
- BC biogeoclimatic zones (OGL-BC); USGS NHDPlus V2 and NWIS (public domain); Water Survey of Canada HYDAT (Open Government Licence - Canada); ERA5-Land reanalysis (Copernicus, licence <https://cds.climate.copernicus.eu/>).

## Day 5 (Sight): data and photographs
- **Photographs, not CC BY:** M.P. Bridgland's 1914 survey plates (Library and Archives Canada, via the Mountain Legacy Project) and the 2004 and 2005 repeat photographs © Eric Higgs (Mountain Legacy Project), as printed in Watt, G. D. (2007), published as Watt-Gremm, G. D., M.Sc. thesis, University of Victoria (<http://hdl.handle.net/1828/2481>). Files: `site/img/day05/photos/*` and the overlay `site/img/day05/wedge_plate597.webp`. Shown with credit; reuse needs the owners' permission.
- **Mountain Legacy Project** station and capture records (MLP Explorer, <https://explore.mountainlegacy.ca>): station ids, positions, recorded bearings and capture ids in `site/data/day05/` follow the Mountain Legacy Project's terms, not CC BY. Free-text capture comments are not published.
- **MRDEM-30**, Natural Resources Canada (CanElevation). *Contains information licensed under the Open Government Licence - Canada.* Hillshade, viewsheds, panoramas and the browser terrain grid are made from it.
- **Copernicus Sentinel-2** L2A, 25 August 2025, from the Earth Search catalogue (Element 84, AWS open data). Contains modified Copernicus Sentinel data 2025.
- **ESA WorldCover 10 m 2021 v200** (Zanaga et al. 2022), CC BY 4.0.
- **Names:** Canadian Geographical Names Database, Natural Resources Canada (Open Government Licence - Canada); USGS Geographic Names Information System (public domain). Published summit heights from OpenStreetMap (ODbL) for 16 peaks.
- **Vectors:** park boundary, Government of Alberta (Open Government Licence - Alberta); 2017 Kenow fire perimeter, Canadian Wildland Fire Information System, National Burned Area Composite (Open Government Licence - Canada); Red Rock Parkway and trails, © OpenStreetMap contributors (ODbL).

## Software in this repository
- **Leaflet 1.9.4**, BSD-2-Clause, © 2010-2023 Vladimir Agafonkin, © 2010-2011 CloudMade: `site/vendor/leaflet-1.9.4/` (licence text included).
- **IBM Plex Mono**, © 2017 IBM Corp., and **Newsreader**, © 2020 The Newsreader Project Authors: SIL Open Font License 1.1, files and licence texts in `site/fonts/`.

## Third-party requests
- None. Every file the pages use is in this repository; the Leaflet page has no tile service.
