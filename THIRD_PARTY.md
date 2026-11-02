# Third-party data, software and fonts

## Data used for the published maps
- **BC Freshwater Atlas** (stream network, watershed group KETL), Province of British Columbia, BC Data Catalogue. *Contains information licensed under the Open Government Licence - British Columbia.* <https://www2.gov.bc.ca/gov/content?id=A519A56BC2BF44E4A008B33FCF527F61>
- **BC Watershed Atlas 1:50,000 watersheds** ("Third-order and greater watersheds"), Province of British Columbia. *Contains information licensed under the Open Government Licence - British Columbia.* Used to cut the basin into local units that give the basin footprint for the US clip; not redistributed.
- **USGS 3D Hydrography Program (3DHP)** flowlines, U.S. Geological Survey. U.S. government work, public domain. <https://www.usgs.gov/3d-hydrography-program>
- **Elevation:** a 30 m digital elevation model patched and extended by the author from the Canadian Digital Elevation Model (Natural Resources Canada, Open Government Licence - Canada) and a US extension. Used to check line direction and measure upstream area; not redistributed here.

## Data used only in the exploration scripts (`day-01/exploration/`), not redistributed
- BC biogeoclimatic zones (OGL-BC); USGS NHDPlus V2 and NWIS (public domain); Water Survey of Canada HYDAT (Open Government Licence - Canada); ERA5-Land reanalysis (Copernicus, licence <https://cds.climate.copernicus.eu/>).

## Software in this repository
- **Leaflet 1.9.4**, BSD-2-Clause, © 2010-2023 Vladimir Agafonkin, © 2010-2011 CloudMade: `site/vendor/leaflet-1.9.4/` (licence text included).
- **IBM Plex Mono**, © 2017 IBM Corp., and **Newsreader**, © 2020 The Newsreader Project Authors: SIL Open Font License 1.1, files and licence texts in `site/fonts/`.

## Loaded only when the visitor asks
- The optional basemap on the Leaflet page loads tiles from CARTO (© OpenStreetMap contributors, © CARTO) when the "basemap" box is ticked. Off by default; nothing is requested from a third party otherwise.
