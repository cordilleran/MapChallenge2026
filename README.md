# MapChallenge2026

Code and maps for the [30 Day Map Challenge](https://30daymapchallenge.com/) 2026. Every day or so, a map.

**Site:** https://cordilleran.github.io/MapChallenge2026/

| Day | Theme | Map |
|---|---|---|
| 1 | Points | [Every junction on the Kettle River](day-01/) |
| 2 | Lines | [How the Granby bends](day-02/) |

Each day has its own folder (`day-NN/`) with a README on its data, method, limits and how to reproduce it. Large data stays outside the repo. The site is built from `site/`; after editing `site/days.yml`, run `Rscript site/calendar.R`.

## How made

I develop each day's concept and direct Claude Code (Anthropic) to build it, and I review the work before publishing. Each day's README names the models and tools used.

## Licence

Code: MIT ([`LICENSE`](LICENSE)). Maps, images and derived data files: CC BY 4.0 ([`LICENSE-IMAGES.md`](LICENSE-IMAGES.md)). Third-party data, software and fonts: [`THIRD_PARTY.md`](THIRD_PARTY.md). To cite: [`CITATION.cff`](CITATION.cff).
