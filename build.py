"""Build the font file from input SVGs."""
import math
import pathlib
import re
import xml.etree.ElementTree as ET

from fontTools.agl import toUnicode
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from shapely.geometry import LineString, Polygon, MultiPolygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from svgpathtools import Line, parse_path

FONT_NAME = "Zircular"
FONT_STYLE = "Regular"
FONT_VERSION = "1.0"
FONT_FLAVOR = "woff2"

OS2_WEIGHT_CLASS = 400
OS2_WIDTH_CLASS = 5
OS2_FS_SELECTION = 1 << 6

BASELINE = 8

CURVE_SAMPLES_PER_UNIT = 8
MIN_CURVE_SAMPLES = 8

SCALE = 128
UNITS_PER_EM = 8 * SCALE
LINE_GAP = 1 * SCALE
X_HEIGHT = 4 * SCALE
CAP_HEIGHT = 8 * SCALE

NOTDEF = ".notdef"
SVG_PATH_TAG = "{http://www.w3.org/2000/svg}path"

ROOT = pathlib.Path(__file__).parent


def load_stroke_style():
    css = (ROOT / "style.css").read_text()
    return dict(re.findall(r"([\w-]+)\s*:\s*([^;}]+)", css))


def load_svg(file):
    root = ET.parse(file).getroot()

    # Load path
    if len(root) == 0:
        path = ""
    else:
        assert len(root) == 1 and root[0].tag == SVG_PATH_TAG
        path = root[0].get("d", "")

    # Parse viewbox
    viewbox = root.get("viewBox", "").split(" ")
    assert len(viewbox) == 4
    viewbox = list(map(float, viewbox))

    return path, viewbox


def create_geometry(path, style):
    # Load style properties
    stroke_width = float(style["stroke-width"])
    cap_style = style["stroke-linecap"]
    join_style = style["stroke-linejoin"]

    # Sample subpaths to create line strings
    shapes = []
    for subpath in parse_path(path).continuous_subpaths():
        line = []
        for segment in subpath:
            if isinstance(segment, Line):
                n_samples = 2
            else:
                n_samples = max(
                    math.ceil(segment.length() * CURVE_SAMPLES_PER_UNIT),
                    MIN_CURVE_SAMPLES
                )
            for sample in range(n_samples):
                point = segment.point(sample / (n_samples - 1))
                xy = (point.real, point.imag)
                line.append(xy)
        shapes.append(LineString(line).buffer(
            stroke_width / 2, cap_style=cap_style, join_style=join_style
        ))

    return unary_union(shapes)


def draw_glyph(geometry):
    # Prepare polygon list
    polygons = []
    if isinstance(geometry, Polygon):
        polygons = [geometry]
    if isinstance(geometry, MultiPolygon):
        polygons = geometry.geoms

    # Create glyph using TTGlyphPen
    pen = TTGlyphPen(None)
    for polygon in polygons:
        polygon = orient(polygon, sign=1)
        for ring in [polygon.exterior, *polygon.interiors]:
            coords = [(round(x * SCALE), round((BASELINE - y) * SCALE))
                      for x, y in list(ring.coords)]
            pen.moveTo(coords[0])
            for point in coords[1:-1]:
                pen.lineTo(point)
            pen.closePath()
    glyph = pen.glyph()
    glyph.recalcBounds(None)

    return glyph


style = load_stroke_style()

glyph_files = sorted((ROOT / "glyphs").rglob("*.svg"))
glyphs = {}
glyph_order = []
horizontal_metrics = {}
character_map = {}

for file in glyph_files:
    name = file.stem

    # Setup glyph order and character map
    glyph_order.append(name)
    codepoint = 0 if name == NOTDEF else ord(toUnicode(name))
    character_map[codepoint] = name

    # Create glyph from SVG
    path, viewbox = load_svg(file)
    glyph_width = viewbox[2]
    geometry = create_geometry(path, style)
    glyph = draw_glyph(geometry)
    glyphs[name] = glyph
    advance_width = round((glyph_width) * SCALE)
    horizontal_metrics[name] = (advance_width, glyph.xMin)

ascent = max(glyph.yMax for glyph in glyphs.values() if glyph.numberOfContours)
descent = min(glyph.yMin for glyph in glyphs.values() if glyph.numberOfContours)

font = FontBuilder(UNITS_PER_EM, isTTF=True)
font.setupNameTable({
    "familyName": FONT_NAME, "styleName": FONT_STYLE, "version": FONT_VERSION,
    "fullName": FONT_NAME, "uniqueFontIdentifier": f"{FONT_NAME} {FONT_STYLE} {FONT_VERSION}",
})
font.setupGlyf(glyphs)
font.setupGlyphOrder(glyph_order)
font.setupCharacterMap(character_map)
font.setupHorizontalMetrics(horizontal_metrics)
font.setupHorizontalHeader(ascent=ascent, descent=descent, lineGap=LINE_GAP)
font.setupPost(keepGlyphNames=True)
font.setupMaxp()
font.setupOS2(
    sTypoAscender=ascent, sTypoDescender=descent, sTypoLineGap=LINE_GAP,
    usWinAscent=ascent, usWinDescent=-descent,
    sxHeight=X_HEIGHT, sCapHeight=CAP_HEIGHT,
    usWeightClass=OS2_WEIGHT_CLASS, usWidthClass=OS2_WIDTH_CLASS,
    fsSelection=OS2_FS_SELECTION,
)

outfile = (ROOT / FONT_NAME.lower()).with_suffix(f".{FONT_FLAVOR}")
font.font.flavor = FONT_FLAVOR
font.save(outfile)
print(f"Wrote {outfile}")
