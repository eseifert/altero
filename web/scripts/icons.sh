#!/bin/sh
# Render the installed application's icons from src/assets/app-icon.svg.
#
# The PNGs are committed, as the SVG is: they change only when the mark does,
# and a build should not need a rasteriser. Run from web/ after editing the
# SVG, and commit what it writes. Needs rsvg-convert (librsvg).
set -eu
source=src/assets/app-icon.svg
for size in 192 512; do
  rsvg-convert -w "$size" -h "$size" "$source" -o "public/icon-$size.png"
done
# iOS draws its own rounded corners and takes no transparency.
rsvg-convert -w 180 -h 180 "$source" -o public/apple-touch-icon.png
