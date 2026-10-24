"""Generate synthetic demo borehole logs into DATA_DIR/reports.csv.

    python scripts/seed_demo_data.py            # 123 logs, refuses to overwrite existing data
    python scripts/seed_demo_data.py --force    # overwrite
    python scripts/seed_demo_data.py -n 40 --seed 7

The data is random and only meant for trying the dashboards; it is deterministic for a
given --seed so screenshots and tests are reproducible.
"""
import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.app import storage  # noqa: E402  (DATA_DIR is read at import time)

PROJECTS = {
    "Proyek Jalan Layang Timur": ["Zona A", "Zona B", "Zona C"],
    "Gedung Perkantoran Sudirman": ["Blok 1", "Blok 2"],
    "Jembatan Kali Ciliwung": ["Abutment Utara", "Abutment Selatan", "Pilar P1"],
    "Reklamasi Pelabuhan Tanjung": ["Dermaga 1", "Dermaga 2", "Area Timbunan"],
}
METHODS = ["Wash Boring + SPT", "Rotary Wash + SPT", "Hollow Stem Auger", "Coring + SPT"]
CONTRACTORS = ["PT GeoBore", "PT Tanah Mandiri", "CV Bor Nusantara"]
GEOLOGISTS = ["R. Santoso", "A. Wijaya", "D. Pratama", "S. Lestari"]
SOILS = {
    "CL": ("Lempung berlanau, lunak sampai teguh", (4, 14)),
    "ML": ("Lanau lempungan, teguh", (6, 18)),
    "SM": ("Pasir berlanau, lepas sampai padat sedang", (10, 30)),
    "SC": ("Pasir lempungan, padat sedang", (12, 32)),
    "GC": ("Kerikil lempungan, padat", (25, 50)),
    "SP": ("Pasir bergradasi buruk, lepas", (8, 24)),
    "SW": ("Pasir bergradasi baik, padat sedang", (15, 35)),
}
REMARKS = ["", "", "Muka air tanah naik setelah hujan", "Casing tersangkut pada kedalaman 12 m",
           "Traffic control diperlukan", "Lapisan lunak, perlu perhatian pondasi"]


def build_rows(count: int, seed: int):
    rng = random.Random(seed)
    rows = []
    for index in range(1, count + 1):
        project = rng.choice(list(PROJECTS))
        site = rng.choice(PROJECTS[project])
        start = date(2024, 1, 1) + timedelta(days=rng.randint(0, 360))
        end = start + timedelta(days=rng.randint(0, 2))
        target = rng.choice([15, 20, 25, 30, 35, 40])
        final = round(target + rng.choice([0, 0, 0, -1.5, -3.0, 1.5]), 1)
        uscs = rng.choice(list(SOILS))
        description, (spt_low, spt_high) = SOILS[uscs]
        has_water = rng.random() < 0.75
        rows.append({
            "BoreholeID": f"BH-2024-{index:03d}",
            "ProjectName": project,
            "SiteName": site,
            "Latitude": f"{-6.1 - rng.random() * 0.2:.5f}",
            "Longitude": f"{106.7 + rng.random() * 0.25:.5f}",
            "GroundElevation_mRL": f"{rng.uniform(1, 25):.1f}",
            "StartDate": start.isoformat(),
            "EndDate": end.isoformat(),
            "DrillingMethod": rng.choice(METHODS),
            "BoreholeDiameter_mm": rng.choice([100, 150]),
            "TargetDepth_m": target,
            "FinalDepth_m": final,
            "CasingInstalled_mm": rng.choice([76, 100]),
            "GroundwaterDepth_m": f"{rng.uniform(0.8, 6.5):.1f}" if has_water else "",
            "GroundwaterEncountered": "True" if has_water else "False",
            "SoilDescription": description,
            "USCS_Class": uscs,
            "Avg_SPT_N60": rng.randint(spt_low, spt_high),
            "Contractor": rng.choice(CONTRACTORS),
            "LoggingGeologist": rng.choice(GEOLOGISTS),
            "Remarks": rng.choice(REMARKS),
            "SubmittedBy": "demo@example.com",
        })
    rows.sort(key=lambda r: r["StartDate"])
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-n", "--count", type=int, default=123)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force", action="store_true", help="overwrite an existing reports.csv")
    args = parser.parse_args()

    if storage.FILE.exists() and not args.force:
        print(f"{storage.FILE} already exists; use --force to overwrite.", file=sys.stderr)
        return 1
    storage._write_reports(build_rows(args.count, args.seed))
    print(f"Wrote {args.count} synthetic logs to {storage.FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
