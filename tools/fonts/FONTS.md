# Fonts

The skin's lettering is baked into its pictures (`skins/`), so the plugin needs no font files. Redrawing the skin
(`tools/make_tui.py`, which `build-sdk.sh` runs when it can) needs these two, which are **not in this repository**:

- `Univers_53_Extended_Regular.otf`: the panel lettering, emboldened by a stroke and fitted to Lemus's measured legend
  widths. Univers is a Linotype typeface: use a copy you are licensed to use.
- `Earth_Normal.ttf`: the MONO-101 wordmark.

Put them here, in `tools/fonts/`. Without them `build-sdk.sh` uses the committed `skins/` as they are.

In the repository, under the SIL Open Font License (`OFL.txt`, `OFL-LiberationSans.txt`):

- `TitilliumWeb-*.ttf`: the face the MPC draws value readouts in (the previews use it).
- `LiberationSans-Bold.ttf`: Helvetica-metric fallback.
