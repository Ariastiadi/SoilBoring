"""AGS4 export: the file must pass the official AGS4 checker (python-ags4)."""
import pytest

from backend.app import storage
from backend.app.ags import build_ags

from .conftest import sample_report

AGS4 = pytest.importorskip("python_ags4.AGS4")


def _check(tmp_path, text, name="export.ags"):
    path = tmp_path / name
    path.write_bytes(text.encode("ascii"))
    result = AGS4.check_file(str(path))
    # "Metadata" and "Summary of data" are informational, everything else is a rule violation.
    return {rule: items for rule, items in result.items() if items and rule not in {"Metadata", "Summary of data"}}


def _rows():
    return [
        dict(sample_report(BoreholeID="BH-01", ProjectName="Jembatan Kali", Latitude="-6.175123",
                           Longitude="106.865201", GroundElevation_mRL="8.5", BoreholeDiameter_mm="150",
                           CasingInstalled_mm="100", GroundwaterEncountered="True", GroundwaterDepth_m="3.2",
                           SoilDescription='Lempung "lanau", abu-abu', USCS_Class="CH", Avg_SPT_N60="27.5",
                           DrillingMethod="Wash Boring + SPT", LoggingGeologist="Andi Pérez")),
        dict(sample_report(BoreholeID="BH-02", ProjectName="Jembatan Kali", DrillingMethod="Sonic + vane",
                           Latitude="", Longitude="", GroundwaterEncountered="False", FinalDepth_m="12")),
        dict(sample_report(BoreholeID="BH-03", ProjectName="Jembatan Kali", DrillingMethod="Hollow Stem Auger",
                           EndDate="")),
        dict(sample_report(BoreholeID="OTHER-1", ProjectName="Another project")),
    ]


def test_export_passes_official_checker(tmp_path):
    name, text = build_ags("jembatan kali", _rows())
    assert name == "JEMBATAN-KALI.ags"
    assert _check(tmp_path, text, name) == {}
    tables, _ = AGS4.AGS4_to_dataframe(str(tmp_path / name))
    loca = tables["LOCA"]
    data = loca[loca.HEADING == "DATA"]
    assert sorted(data.LOCA_ID) == ["BH-01", "BH-02", "BH-03"]  # other projects excluded
    bh1 = data[data.LOCA_ID == "BH-01"].iloc[0]
    assert bh1.LOCA_TYPE == "W"
    assert bh1.LOCA_FDEP == "30.00"
    assert bh1.LOCA_LAT.startswith("-06:10:30")
    assert "USCS: CH" in bh1.LOCA_REM and "Average SPT N60: 27.5" in bh1.LOCA_REM
    abbr = tables["ABBR"]
    assert set(abbr[abbr.HEADING == "DATA"].ABBR_CODE) >= {"W", "AUGH", "M1"}
    wstg = tables["WSTG"]
    # BH-02 has no groundwater; BH-01 and BH-03 (sample default) do.
    assert sorted(wstg[wstg.HEADING == "DATA"].LOCA_ID) == ["BH-01", "BH-03"]
    assert "3.20" in list(wstg[wstg.HEADING == "DATA"].WSTG_DPTH)
    assert "\r\n" in text and text.isascii()


def test_minimal_log_still_valid(tmp_path):
    rows = [dict(sample_report(BoreholeID="X1", Latitude="", Longitude="", BoreholeDiameter_mm="",
                               CasingInstalled_mm="", GroundwaterEncountered="False"))]
    name, text = build_ags(rows[0]["ProjectName"], rows)
    assert _check(tmp_path, text, name) == {}


def test_ids_that_collide_after_ascii_conversion_are_refused():
    rows = [dict(sample_report(BoreholeID="BH-é1")), dict(sample_report(BoreholeID="BH-e1"))]
    with pytest.raises(ValueError):
        build_ags(rows[0]["ProjectName"], rows)


def test_export_endpoint(client, general_headers):
    storage._write_reports(_rows())
    res = client.get("/api/export/ags", params={"project": "Jembatan Kali"}, headers=general_headers)
    assert res.status_code == 200
    assert res.headers["content-disposition"] == 'attachment; filename="JEMBATAN-KALI.ags"'
    assert res.text.startswith('"GROUP","PROJ"')
    assert client.get("/api/export/ags", params={"project": "Nope"}, headers=general_headers).status_code == 404
    assert client.get("/api/export/ags", params={"project": "Jembatan Kali"}).status_code == 401


def test_cpt_and_hand_auger_use_standard_codes(tmp_path):
    rows = [
        dict(sample_report(BoreholeID="S-01", DrillingMethod="CPT / CPTu (Sondir)")),
        dict(sample_report(BoreholeID="HA-01", DrillingMethod="Hand Auger")),
    ]
    name, text = build_ags(rows[0]["ProjectName"], rows)
    assert _check(tmp_path, text, name) == {}
    assert '"DATA","S-01","SCP"' in text and '"DATA","HA-01","HA"' in text
    assert '"LOCA_TYPE","SCP","Static cone penetrometer","AGS4"' in text
