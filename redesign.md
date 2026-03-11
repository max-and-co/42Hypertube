Redesign the visual style of this project to match a 1930s Hollywood Art Deco title card aesthetic. Do not change any functionality, routing, or data logic — only touch styling.
Typography:

Import from Google Fonts: Playfair Display (weights 700, 900) for all headings and display text; Cinzel (weights 400, 700) for labels, navigation, buttons, and UI chrome
All caps + wide letter-spacing (0.3em–0.6em) on small labels and nav items
Italic Playfair Display for subheadings and secondary titles

Color palette (CSS variables):
css--silver-light: #e8e8e8;
--silver: #c8c8c8;
--silver-dim: #888888;
--gold: #c8a84b;
--black: #000000;
--near-black: #080808;
--surface: #0d0d0d;
--border: #1a1a1a;
Metallic text effect on all primary headings:
cssbackground: linear-gradient(180deg, #fff 0%, #e0e0e0 20%, #b0b0b0 50%, #d8d8d8 70%, #909090 100%);
-webkit-background-clip: text;
-webkit-text-fill-color: transparent;
background-clip: text;
Backgrounds & surfaces:

Page background: #000 with a radial vignette (radial-gradient(ellipse at center, transparent 40%, rgba(0,0,0,0.85) 100%))
Cards/panels: #0d0d0d with border: 1px solid #1a1a1a
Subtle film grain overlay using an SVG noise filter at low opacity (mix-blend-mode: overlay)
Scanlines: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.03) 2px, rgba(0,0,0,0.03) 4px)

UI elements:

Dividers: linear-gradient(90deg, transparent, #888, transparent) — no solid lines
Buttons: transparent background, 1px solid #888 border, Cinzel font, wide letter-spacing, hover state brightens border to #e8e8e8
Inputs: background: #0a0a0a, border: 1px solid #222, silver text, no border-radius or minimal (2px max)
Box shadows: 0 0 80px rgba(0,0,0,0.9) — deep and dark, no coloured glows

Animation:

Page/component load: fade-in + subtle translateY(8px → 0) per element, staggered with animation-delay
Use opacity: 0 as default, animate to opacity: 1 — no pop-in
Optional flicker on key elements: brief opacity dips at random intervals to simulate a projector lamp

General rules:

No border-radius above 3px anywhere
No white backgrounds, no light themes
No coloured accent palette — this is strictly silver, black, and occasional gold
Spacing should feel cinematic and generous — increase padding and line-height throughout