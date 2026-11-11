# Day 11 (Senses: Sound): 2424/461, mapped again

The piece lives in the sonify-viz repository, and the Day 11 page (`site/day-11.qmd`) frames the live version, so both sites show the same one: <https://cordilleran.github.io/sonify-viz/lightning.html>. Source: <https://github.com/cordilleran/sonify-viz/tree/main/lightning>.

Day 11 rebuilt the piece's map; the sound is unchanged. What changed, and which earlier day taught it, is listed on the page:

- relief tiles: a hillshade (AWS Terrain Tiles) blended with Sentinel-2 true colour from 22 May to 29 June 2021, zoom to 8x the starting view;
- rivers (BC Freshwater Atlas) as a hierarchy that grows with zoom, under filled lakes;
- the six most populous towns (OpenStreetMap), labels placed by rule so they stay inside the map; highways;
- a scale bar, a north arrow and layer buttons;
- a steadier follow-the-pin pan.

The builders (`make_relief_tiles.py`, `make_places_roads.py`) are kept with the piece's sources, outside this repository. The before and after images in `site/img/day11/` are headless screenshots of the 26 October and 10 November versions at the same moment.

Data: GOES-17 GLM (NOAA/NESDIS); AWS Terrain Tiles; contains modified Copernicus Sentinel data 2021; BC Freshwater Atlas (Open Government Licence - British Columbia); © OpenStreetMap contributors (ODbL).
