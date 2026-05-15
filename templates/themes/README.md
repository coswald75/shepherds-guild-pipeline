# Themes

V1 ships with a single inlined theme. The template at
`templates/sermon_page.html.j2` declares its design tokens as CSS variables in
`:root` (e.g. `--accent`, `--link`). When `churches.brand_color` is set, the
template substitutes that color for `--accent` and `--link`; otherwise it
falls back to the default green (`#2d5a4a`).

This `themes/` directory is a placeholder for V2. The eventual plan:

1. Each church row stores `themes/<church-slug>.css` (or references one of a
   small set of named themes), and `templates/sermon_page.html.j2` includes
   it via a `<style>` block before the inline default.
2. A theme is just a stylesheet that re-declares the CSS variables — no
   template fork required.

For now: edit `church.brand_color` to recolor; don't add per-church files
here. When V2 lands, this README will be replaced with concrete instructions.
