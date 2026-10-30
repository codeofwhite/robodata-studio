# README visual assets

Created for RoboData Studio by IPPLab on 2026-10-30.

| Asset | Origin | Purpose |
| --- | --- | --- |
| robodata-studio-hero.png | AI-generated with the built-in image generation tool; no reference image supplied | Conceptual project cover with the exact project name and by IPPLab credit |
| workflow.svg | Locally rendered from specs/workflow.json using FigureSpec | Canonical data lifecycle and QA-gated export |
| architecture.svg | Locally rendered from specs/architecture.json using FigureSpec | Implemented process, interface and data boundaries |

The hero is a concept illustration, not a screenshot, robot measurement or evidence
of collection performance. It uses no supplied lab logo or third-party photo.
The final generation prompt is preserved in [hero-prompt.txt](hero-prompt.txt).
No simulator SDK, asset binary or captured dataset was used to create these visuals.
The SVGs and their JSON source are original project documentation under the root
[Apache-2.0 license](../../LICENSE). No exclusive-rights claim is made for the
AI-generated cover; third-party rights, if any, are not granted by this notice.

## Reproduce the technical diagrams

The JSON sources use the FigureSpec schema. With the FigureSpec skill's
figure_renderer.py available locally, run from the repository root:

```bash
python -B /path/to/figure_renderer.py validate docs/assets/specs/workflow.json
python -B /path/to/figure_renderer.py render docs/assets/specs/workflow.json --output docs/assets/workflow.svg
python -B /path/to/figure_renderer.py validate docs/assets/specs/architecture.json
python -B /path/to/figure_renderer.py render docs/assets/specs/architecture.json --output docs/assets/architecture.svg
```

The renderer is a documentation-authoring tool, not a runtime dependency and is
not bundled here. Edit the JSON and regenerate the SVG; identical specifications
produce identical SVG markup with a fixed renderer version. Appearance depends on
the viewer's installed fonts. All essential diagrams include a solid background
and explicit text colors for consistent light/dark GitHub display.
