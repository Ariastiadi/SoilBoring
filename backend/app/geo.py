"""Coordinates: WGS84 latitude/longitude to and from UTM, and Google Earth (KML) files."""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Tuple
from xml.sax.saxutils import escape

# WGS84
_A = 6378137.0
_F = 1 / 298.257223563
_K0 = 0.9996
_E2 = _F * (2 - _F)
_EP2 = _E2 / (1 - _E2)


def utm_zone(lat: float, lon: float) -> int:
    zone = int((lon + 180) // 6) + 1
    # Norway and Svalbard exceptions do not matter for Indonesia but keep the standard rule.
    if 56 <= lat < 64 and 3 <= lon < 12:
        zone = 32
    return max(1, min(60, zone))


def to_utm(lat: float, lon: float, zone: Optional[int] = None) -> Dict[str, Any]:
    """Latitude/longitude (degrees) to UTM easting/northing (m)."""
    if not -80 <= lat <= 84:
        raise ValueError("Latitude must be between -80 and 84 for UTM")
    if not -180 <= lon <= 180:
        raise ValueError("Longitude must be between -180 and 180")
    zone = zone or utm_zone(lat, lon)
    lon0 = math.radians((zone - 1) * 6 - 180 + 3)
    phi, lam = math.radians(lat), math.radians(lon)
    n = _A / math.sqrt(1 - _E2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = _EP2 * math.cos(phi) ** 2
    a = math.cos(phi) * (lam - lon0)
    e4, e6 = _E2 ** 2, _E2 ** 3
    m = _A * ((1 - _E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
              - (3 * _E2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
              + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
              - (35 * e6 / 3072) * math.sin(6 * phi))
    easting = _K0 * n * (a + (1 - t + c) * a ** 3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * _EP2) * a ** 5 / 120) + 500000.0
    northing = _K0 * (m + n * math.tan(phi) * (a * a / 2 + (5 - t + 9 * c + 4 * c * c) * a ** 4 / 24
                                             + (61 - 58 * t + t * t + 600 * c - 330 * _EP2) * a ** 6 / 720))
    hemisphere = "N" if lat >= 0 else "S"
    if hemisphere == "S":
        northing += 10000000.0
    return {"zone": zone, "hemisphere": hemisphere, "easting": round(easting, 3), "northing": round(northing, 3)}


def from_utm(easting: float, northing: float, zone: int, hemisphere: str = "S") -> Dict[str, float]:
    """UTM easting/northing (m) to latitude/longitude (degrees)."""
    if not 1 <= zone <= 60:
        raise ValueError("UTM zone must be 1 to 60")
    x = easting - 500000.0
    y = northing - (10000000.0 if hemisphere.upper().startswith("S") else 0.0)
    lon0 = math.radians((zone - 1) * 6 - 180 + 3)
    e4, e6 = _E2 ** 2, _E2 ** 3
    m = y / _K0
    mu = m / (_A * (1 - _E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256))
    e1 = (1 - math.sqrt(1 - _E2)) / (1 + math.sqrt(1 - _E2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    n1 = _A / math.sqrt(1 - _E2 * math.sin(phi1) ** 2)
    t1 = math.tan(phi1) ** 2
    c1 = _EP2 * math.cos(phi1) ** 2
    r1 = _A * (1 - _E2) / (1 - _E2 * math.sin(phi1) ** 2) ** 1.5
    d = x / (n1 * _K0)
    lat = phi1 - (n1 * math.tan(phi1) / r1) * (d * d / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * _EP2) * d ** 4 / 24
                                                + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * _EP2 - 3 * c1 * c1) * d ** 6 / 720)
    lon = lon0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6
                  + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * _EP2 + 24 * t1 * t1) * d ** 5 / 120) / math.cos(phi1)
    return {"latitude": round(math.degrees(lat), 8), "longitude": round(math.degrees(lon), 8)}


def dms(value: float, positive: str, negative: str) -> str:
    """-6.2 -> 6° 12' 0.00\" S"""
    sign = positive if value >= 0 else negative
    v = abs(value)
    d = int(v)
    m = int((v - d) * 60)
    s = (v - d - m / 60) * 3600
    if s >= 59.995:
        s, m = 0.0, m + 1
    if m == 60:
        m, d = 0, d + 1
    return f"{d}° {m}' {s:.2f}\" {sign}"


def describe(lat: Optional[float], lon: Optional[float]) -> Optional[Dict[str, Any]]:
    """UTM and degree-minute-second forms of a point, for display."""
    if lat is None or lon is None:
        return None
    try:
        utm = to_utm(float(lat), float(lon))
    except (TypeError, ValueError):
        return None
    return {**utm, "dms": f"{dms(float(lat), 'N', 'S')}, {dms(float(lon), 'E', 'W')}"}


Point = Tuple[str, float, float, Optional[float], str, str]  # name, lat, lon, elevation, folder, description


def kml(name: str, points: Iterable[Point]) -> str:
    """A KML document with one folder per kind of point (boreholes, CPT, ...)."""
    folders: Dict[str, List[str]] = {}
    styles = {"Boreholes": "ff1f5f8b", "CPT / sondir": "ff00c4f5", "Field work": "ff3c9a2e"}
    for pname, lat, lon, elev, folder, desc in points:
        alt = f",{elev:g}" if elev is not None else ""
        style = f"#{folder.replace(' ', '_').replace('/', '')}" if folder in styles else ""
        folders.setdefault(folder, []).append(
            f"<Placemark><name>{escape(pname)}</name>"
            + (f"<styleUrl>{style}</styleUrl>" if style else "")
            + (f"<description>{escape(desc)}</description>" if desc else "")
            + f"<Point><coordinates>{lon:.8f},{lat:.8f}{alt}</coordinates></Point></Placemark>")
    style_xml = "".join(
        f'<Style id="{k.replace(" ", "_").replace("/", "")}"><IconStyle><color>{v}</color><scale>1.1</scale>'
        f'<Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon></IconStyle></Style>'
        for k, v in styles.items())
    body = "".join(f"<Folder><name>{escape(f)}</name>{''.join(items)}</Folder>" for f, items in folders.items())
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            f"<name>{escape(name)}</name>{style_xml}{body}</Document></kml>\n")
