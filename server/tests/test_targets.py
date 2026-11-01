# Starlette's TestClient is typed against the `httpx2` package; with plain `httpx`
# installed its response types are unknown to pyright.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""The bundled target catalog: OpenNGC's parsing, loose designations, search and API (ADR 0019)."""

import gzip
import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api import create_app
from nocs.api.schemas import CatalogMatch
from nocs.config import Settings
from nocs.targets import TargetCatalog, bundled_catalog, display_id, fold, id_key
from nocs.targets.catalog import FORMAT
from nocs.targets.openngc import OpenNgcError, build

HEADER = (
    "Name;Type;RA;Dec;Const;MajAx;MinAx;PosAng;B-Mag;V-Mag;J-Mag;H-Mag;K-Mag;SurfBr;Hubble;"
    "Pax;Pm-RA;Pm-Dec;RadVel;Redshift;Cstar U-Mag;Cstar B-Mag;Cstar V-Mag;M;NGC;IC;"
    "Cstar Names;Identifiers;Common names;NED notes;OpenNGC notes;Sources"
)


def row(name: str, type_: str, ra: str = "", dec: str = "", **fields: str) -> str:
    columns = HEADER.split(";")
    values = dict.fromkeys(columns, "") | {"Name": name, "Type": type_, "RA": ra, "Dec": dec}
    values |= {k.replace("_", "-"): v for k, v in fields.items()}
    return ";".join(values[c] for c in columns)


NGC = "\n".join(
    [
        HEADER,
        row(
            "NGC0253",
            "G",
            "00:47:33.12",
            "-25:17:17.6",
            Const="Scl",
            MajAx="26.79",
            MinAx="4.58",
            PosAng="53",
            B_Mag="7.94",
            Identifiers="2MASX J00473313-2517196,C 065,ESO 474-029,PGC 002789",
            **{"Common names": "Sculptor Filament,Silver Coin"},
        ),
        row(
            "NGC1976",
            "Cl+N",
            "05:35:16.48",
            "-05:23:22.8",
            Const="Ori",
            V_Mag="4.00",
            B_Mag="4.00",
            M="042",
            Identifiers="LBN 974,MWSC 0582",
            **{"Common names": "Great Orion Nebula,Orion Nebula"},
        ),
        row("NGC5457", "G", "14:03:12.54", "+54:20:56.2", V_Mag="7.90", M="101"),
        row("NGC5866", "G", "15:06:29.56", "+55:45:47.9", V_Mag="9.89"),
        row("NGC0010", "G", "00:08:34.54", "-00:33:51.2"),
        row("IC0011", "Dup", "00:52:59.35", "+56:37:18.8", NGC="0281"),
        row("NGC0281", "HII", "00:52:59.35", "+56:37:18.8", IC="0011"),
        row("IC1064", "NonEx"),
    ]
)
ADDENDUM = "\n".join(
    [HEADER, row("M102", "Dup", M="101"), row("Cl399", "*Ass", "19:26:00", "+20:11:00")]
)


def addendum(*rows: str) -> str:
    return "\n".join([HEADER, *rows])


# -- Text -----------------------------------------------------------------------------


def test_fold_drops_case_accents_and_punctuation() -> None:
    assert fold("Nebulosa de Orión") == fold("nebulosa de orion") == "nebulosa de orion"
    assert fold("Cat's Eye") == fold("Cat\N{RIGHT SINGLE QUOTATION MARK}s Eye") == "cats eye"
    assert fold("  Pequeña  Nube ") == "pequena nube"
    assert fold("Bow-Tie nebula") == "bow tie nebula"


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("M 31", "m31"),
        ("m31", "m31"),
        ("M031", "m31"),
        ("Messier 31", "m31"),
        ("ngc292", "ngc292"),
        ("NGC 0292", "ngc292"),
        ("ngc-292", "ngc292"),
        ("Caldwell 65", "c65"),
        ("C 065", "c65"),
        ("Collinder 399", "cr399"),
        ("Cl 399", "cr399"),
        ("Mel 22", "mel22"),
        ("ESO 56-115", "eso56-115"),
        ("IC 0080 NED01", "ic80ned1"),
        ("IC 186A", "ic186a"),
    ],
)
def test_id_key_reads_designations_loosely(text: str, key: str) -> None:
    assert id_key(text) == key


@pytest.mark.parametrize("text", ["orion", "47 Tuc", "", "  ", "M"])
def test_id_key_ignores_what_is_not_a_designation(text: str) -> None:
    assert id_key(text) is None


def test_display_id_writes_openngc_names_as_people_do() -> None:
    assert display_id("NGC0292") == "NGC 292"
    assert display_id("IC0080 NED01") == "IC 80 NED01"
    assert display_id("Cl399") == "Cr 399"
    assert display_id("ESO056-115") == "ESO 56-115"
    assert display_id("B033") == "B 33"


# -- Parsing OpenNGC --------------------------------------------------------------------


def test_build_reads_objects_and_their_aliases() -> None:
    targets = {t.id: t for t in build([NGC, ADDENDUM])}
    assert set(targets) == {
        "NGC 253",
        "NGC 1976",
        "NGC 5457",
        "NGC 5866",
        "NGC 10",
        "NGC 281",
        "Cr 399",
    }

    sculptor = targets["NGC 253"]
    assert sculptor.type == "galaxy"
    assert sculptor.ra == pytest.approx(0 + 47 / 60 + 33.12 / 3600)
    assert sculptor.dec == pytest.approx(-(25 + 17 / 60 + 17.6 / 3600))
    assert (sculptor.major_axis, sculptor.minor_axis, sculptor.position_angle) == (26.79, 4.58, 53)
    assert sculptor.magnitude == 7.94  # blue: it has no visual one
    assert targets["NGC 5457"].magnitude == 7.9
    assert sculptor.constellation == "Scl"
    # Caldwell first; catalogs nobody searches by are dropped.
    assert sculptor.aliases == ("C 65", "ESO 474-29", "PGC 2789")
    assert sculptor.names == ("Sculptor Filament", "Silver Coin")

    orion = targets["NGC 1976"]
    assert orion.type == "cluster_nebula"
    assert (orion.label, orion.aliases) == ("M 42", ("M 42", "LBN 974"))
    assert orion.magnitude == 4.0

    assert targets["NGC 10"].dec == pytest.approx(-(33 / 60 + 51.2 / 3600))  # -0° keeps its sign


def test_build_turns_duplicates_into_aliases() -> None:
    targets = {t.id: t for t in build([NGC, ADDENDUM])}
    assert targets["NGC 281"].aliases == ("IC 11",)
    assert targets["NGC 5457"].aliases == ("M 101", "M 102")  # OpenNGC's reading of M 102
    assert targets["NGC 5866"].aliases == ()


def test_build_merges_nocs_names() -> None:
    names = (
        "# comment\n"
        "NGC0253\ten\tSculptor Galaxy\n"
        "NGC0253\tes\tGalaxia del Escultor, Moneda de Plata\n"
        "IC0011\tes\tNebulosa Pacman\n"  # a duplicate's name reaches its object
    )
    targets = {t.id: t for t in build([NGC], names)}
    # NOCS's names come first: clients show the first one.
    assert targets["NGC 253"].names == ("Sculptor Galaxy", "Sculptor Filament", "Silver Coin")
    assert targets["NGC 253"].names_es == ("Galaxia del Escultor", "Moneda de Plata")
    assert targets["NGC 281"].names_es == ("Nebulosa Pacman",)


@pytest.mark.parametrize(
    "names",
    ["NGC9999\ten\tNowhere\n", "NGC0253\tfr\tGalaxie du Sculpteur\n", "NGC0253 en Sculptor\n"],
)
def test_build_refuses_names_it_cannot_place(names: str) -> None:
    with pytest.raises(OpenNgcError):
        build([NGC], names)


def test_build_refuses_unknown_types_and_missing_coordinates() -> None:
    with pytest.raises(OpenNgcError, match="unknown type"):
        build([addendum(row("X1", "Blob", "00:00:00", "+00:00:00"))])
    with pytest.raises(OpenNgcError, match="no coordinates"):
        build([addendum(row("X1", "G"))])


def test_catalog_reads_what_the_build_writes() -> None:
    targets = build([NGC, ADDENDUM])
    source = {
        "name": "OpenNGC",
        "version": "v0",
        "url": "u",
        "license": "CC BY-SA 4.0",
        "license_url": "l",
        "attribution": "a",
    }
    document = {"format": FORMAT, "sources": [source], "objects": [t.to_row() for t in targets]}
    catalog = TargetCatalog.from_bytes(gzip.compress(json.dumps(document).encode()))
    assert list(catalog.targets) == targets
    assert catalog.sources[0].license == "CC BY-SA 4.0"

    with pytest.raises(ValueError, match="format"):
        TargetCatalog.from_bytes(gzip.compress(json.dumps(document | {"format": 0}).encode()))


# -- The bundled catalog ----------------------------------------------------------------


@pytest.fixture(scope="module")
def catalog() -> TargetCatalog:
    return bundled_catalog()


def first(catalog: TargetCatalog, query: str) -> tuple[str, str]:
    match = catalog.search(query, limit=1)[0]
    return match.target.id, match.matched


def test_bundled_catalog_has_ngc_ic_and_the_addendum(catalog: TargetCatalog) -> None:
    assert len(catalog.targets) > 13000
    assert catalog.sources[0].name == "OpenNGC"
    assert "CC BY-SA 4.0" in catalog.sources[0].attribution
    messier = {a for t in catalog.targets for a in (t.id, *t.aliases) if a.startswith("M ")}
    assert len(messier) == 110  # M 102 included, as a duplicate of M 101
    sculptor = catalog.get("NGC 253")
    assert sculptor is not None
    assert sculptor.magnitude == 7.94  # B: OpenNGC's V (11.11) is off
    caldwell = {a for t in catalog.targets for a in (t.id, *t.aliases) if a.startswith("C ")}
    assert len(caldwell) == 109


def test_finds_the_exit_test_targets(catalog: TargetCatalog) -> None:
    for query in ["NGC 292", "ngc292", "NGC 0292", "smc", "Small Magellanic Cloud"]:
        assert first(catalog, query)[0] == "NGC 292", query
    assert first(catalog, "pequeña nube de magallanes") == ("NGC 292", "Pequeña Nube de Magallanes")
    for query in ["NGC 253", "ngc253", "Sculptor Galaxy", "sculptor", "C 65", "Caldwell 65"]:
        assert first(catalog, query)[0] == "NGC 253", query
    assert first(catalog, "galaxia del escultor") == ("NGC 253", "Galaxia del Escultor")

    smc = catalog.get("ngc 292")
    assert smc is not None
    assert (round(smc.ra, 3), round(smc.dec, 2)) == (0.879, -72.83)
    assert smc.major_axis == pytest.approx(299.92)


def test_finds_m42_in_english_and_spanish(catalog: TargetCatalog) -> None:
    for query in ["M42", "m 42", "Messier 42", "Orion Nebula", "orion"]:
        assert first(catalog, query)[0] == "NGC 1976", query
    assert first(catalog, "nebulosa de orion") == ("NGC 1976", "Nebulosa de Orión")
    assert first(catalog, "NEBULOSA ORIÓN") == ("NGC 1976", "Nebulosa de Orión")
    target = catalog.get("m42")
    assert target is not None
    assert (target.id, target.label) == ("NGC 1976", "M 42")


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Mel 22", "Mel 22"),
        ("M45", "Mel 22"),
        ("pleyades", "Mel 22"),
        ("M 102", "NGC 5457"),
        ("PGC 2789", "NGC 253"),
        ("Collinder 399", "Cr 399"),
        ("lmc", "ESO 56-115"),
        ("gran nube", "ESO 56-115"),
        ("47 tuc", "NGC 104"),
        ("omega centauri", "NGC 5139"),
        ("cats eye nebula", "NGC 6543"),
        ("running man", "NGC 1977"),
        ("Gabriela Mistral", "NGC 3324"),
    ],
)
def test_finds_aliases_and_names(catalog: TargetCatalog, query: str, expected: str) -> None:
    assert first(catalog, query)[0] == expected


def test_ranks_exact_designations_then_the_rest(catalog: TargetCatalog) -> None:
    ids = [m.target.label for m in catalog.search("m3", limit=11)]
    assert ids[0] == "M 3"
    assert sorted(ids[1:]) == [f"M {n}" for n in range(30, 40)]  # by brightness
    ids = [m.target.id for m in catalog.search("ngc 29", limit=12)]
    assert ids[0] == "NGC 21"  # NGC 29 is a duplicate of NGC 21
    assert {f"NGC {n}" for n in range(290, 300)} - {"NGC 291"} <= set(ids)


def test_brighter_objects_win_ties(catalog: TargetCatalog) -> None:
    matches = catalog.search("nube de magallanes")
    assert [m.target.id for m in matches[:2]] == ["ESO 56-115", "NGC 292"]


def test_search_respects_the_limit_and_misses_politely(catalog: TargetCatalog) -> None:
    assert len(catalog.search("galaxy", limit=3)) == 3
    assert catalog.search("no such thing") == []
    assert catalog.search("   ") == []
    assert catalog.get("NGC 99999") is None
    assert catalog.get("orion") is None


# -- API --------------------------------------------------------------------------------


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(indi_host="127.0.0.1", indi_port=9)  # nothing listens there
    with TestClient(create_app(settings)) as client:
        pair_owner(client)
        yield client


def test_api_searches_the_catalog(client: TestClient) -> None:
    response = client.get("/api/targets/search", params={"q": "nebulosa de orion", "limit": 5})
    assert response.status_code == 200
    first_match = response.json()[0]
    assert first_match["matched"] == "Nebulosa de Orión"
    found = first_match["object"]
    assert (found["id"], found["label"], found["type"]) == ("NGC 1976", "M 42", "cluster_nebula")
    assert found["names_es"] == ["Gran Nebulosa de Orión", "Nebulosa de Orión"]
    CatalogMatch.model_validate(first_match)

    assert len(client.get("/api/targets/search", params={"q": "galaxy"}).json()) == 20
    assert client.get("/api/targets/search", params={"q": ""}).status_code == 422
    assert client.get("/api/targets/search", params={"q": "m", "limit": 0}).status_code == 422


def test_api_gets_one_object_by_a_loose_designation(client: TestClient) -> None:
    for designation in ["NGC 292", "ngc0292", "NGC%20292"]:
        response = client.get(f"/api/targets/objects/{designation}")
        assert response.status_code == 200, designation
        assert response.json()["names"] == ["Small Magellanic Cloud", "SMC"]
    assert client.get("/api/targets/objects/m42").json()["id"] == "NGC 1976"
    assert client.get("/api/targets/objects/NGC 99999").status_code == 404


def test_api_names_its_sources(client: TestClient) -> None:
    sources = client.get("/api/targets/sources").json()
    assert [(s["name"], s["license"]) for s in sources] == [
        ("OpenNGC", "CC BY-SA 4.0"),
        ("Tycho-2", "CC BY-NC 3.0 IGO"),
    ]


def test_observers_may_search(client: TestClient) -> None:
    assert client.put("/api/auth/observer", json={"enabled": True}).status_code == 204
    client.cookies.clear()
    assert client.get("/api/targets/search", params={"q": "m42"}).status_code == 200
    assert client.get("/api/targets/objects/m42").status_code == 200
    assert client.get("/api/targets/sources").status_code == 200
    assert client.put("/api/auth/observer", json={"enabled": False}).status_code == 401
