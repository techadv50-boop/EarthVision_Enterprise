"""IJIST header fixtures and parser tests."""

from app.services.citation_parser import parse_ijist_header, format_house_citation

GALLEY_EDDSA = """
International Journal of Innovations in Science & Technology
August 2026|Vol 8 | Issue 5 \tPage |1788
Secure and Efficient Digital Signature Scheme for Document
Authentication using EDDSA and Watermarking
Sahibzada Hasanain1, Qazi Ejaz Ali1
*Correspondence: qaziejazali@uop.edu.pk
Citation| Hasanain. S, Ali. Q. E, “Secure and Efficient Digital Signature Scheme for Document Authentication using EDDSA and Watermarking”, IJIST, Vol. 8 Issue. 5 pp 1788-1813, August 2026
Received| July 09, 2026 Revised| July 31, 2026 Accepted| Aug 02, 2026 Published| Aug 13, 2026.
This paper introduces an efficient integrated digital signature scheme that combines Edward’s curve Digital Signature Algorithm (EDDSA) for deterministic and nonce secure digital signing together with watermarking for tamper detection.
Keywords: Digital Document Authentication; EdDSA (Ed25519); Multi-signature Scheme
"""

GALLEY_WATER = """
International Journal of Innovations in Science & Technology
August 2026|Vol 8 | Issue 5 \tPage |2211
Integrated Source Tracking and Assessment of Drinking Water
Contamination in Rural Sindh, Pakistan
Asim Ali1, Jabir Ali Keerio1
*Correspondence: asimali@bbsutsd.edu.pk
Citation| Ali. A, Keerio. J. A, “Integrated Source Tracking and Assessment of Drinking Water Contamination in Rural Sindh, Pakistan”, IJIST, Vol. 8 Issue. 5 pp 2211-2224, August 2026
Received| July 22, 2026 Revised| Aug 18, 2026 Accepted| Aug 21, 2026 Published| Aug 23, 2026.
Introduction/Importance of Study: Water is essential for life, and it can be contaminated by physical, chemical, and biological pollutants. Water Quality Index (WQI) and Synthetic Pollution Index (SPI) models were calibrated for Khairpur groundwater.
Keywords: Physio-Chemical Analysis; Mathematical Models; WHO Standards; Khairpur City and Arsenic
"""


def test_parse_eddsa_galley():
    meta = parse_ijist_header(GALLEY_EDDSA)
    assert meta["volume"] == 8
    assert meta["issue"] == 5
    assert meta["page_start"] == 1788
    assert meta["page_end"] == 1813
    assert meta["year"] == 2026
    assert "Digital Signature" in (meta["title"] or "")
    assert meta["published_date"] and "13" in meta["published_date"]
    assert meta["doi"] is None or meta["doi"]


def test_parse_water_galley():
    meta = parse_ijist_header(GALLEY_WATER)
    assert meta["volume"] == 8
    assert meta["issue"] == 5
    assert meta["page_start"] == 2211
    assert meta["page_end"] == 2224
    assert "Drinking Water" in (meta["title"] or "")
    assert meta["published_date"] and "23" in meta["published_date"]
    assert meta["keywords"]


def test_house_citation_format():
    text = format_house_citation(
        authors=["Hasanain. S", "Ali. Q. E"],
        title="Secure Scheme",
        volume=8,
        issue=5,
        page_start=1788,
        page_end=1813,
        month="August",
        year=2026,
        journal_name="International Journal of Innovations in Science & Technology",
        abbreviation="IJIST",
        doi="10.33411/IJIST/202608051788",
    )
    assert "IJIST" in text
    assert "vol. 8" in text
    assert "no. 5" in text
    assert "1788-1813" in text
    assert "doi: 10.33411/IJIST/202608051788" in text
    assert ", doi:" in text
    assert "Secure Scheme" in text
    assert text.endswith(".")


GALLEY_FCSI = """
Frontiers in Computational Spatial Intelligence
May 2025|Vol 03 | Issue 02 Page |66
An Integrated Ant Colony and Dynamic Window Approach for
Cooperative Multi-Robot Trajectory Planning in Safflower
Cultivation
Rashida Naseer1, Shahid Khan1
1Quaid e Azam university, Lahore
*Correspondence: rabia.naseer@gmail.com
Citation| Azeem. N, Khan. S, “An Integrated Ant Colony and Dynamic Window Approach for Cooperative Multi-Robot Trajectory Planning in Safflower Cultivation”, FCSI, Vol. 03 Issue. 2 pp 66-76, May 2025
DOI| https://doi.org/10.33411/fcsi/202532066076
Received| April 08, 2025 Revised| May 06, 2025 Accepted| May 07, 2025 Published| May 08, 2025.
The increasing adoption of agricultural robotics has highlighted the need for efficient trajectory planning in crop fields.
Keywords: Agricultural Robotics; Trajectory Planning; Ant Colony Optimization (ACO)
Introduction:
Safflower is an oilseed crop. Multi-robot coordination in safflower fields remains a research direction.
"""


def test_parse_fcsi_galley():
    meta = parse_ijist_header(
        GALLEY_FCSI,
        journal_name="Frontiers in Computational Spatial Intelligence",
        abbreviation="FCSI",
    )
    assert meta["abbreviation"] == "FCSI"
    assert meta["volume"] == 3
    assert meta["issue"] == 2
    assert meta["page_start"] == 66
    assert meta["page_end"] == 76
    assert "Safflower" in (meta["title"] or "")
    assert "Frontiers in Computational Spatial Intelligence" not in (meta["title"] or "")
    assert meta["authors"]
    assert "Azeem" in " ".join(meta["authors"])
    assert meta["doi"] == "10.33411/fcsi/202532066076"


def test_broken_banner_title_is_detected():
    from app.services.citation_parser import metadata_looks_broken

    assert metadata_looks_broken(
        "Frontiers in Computational Spatial Intelligence underexplored. Efficient scheduling.",
        [],
        journal_name="Frontiers in Computational Spatial Intelligence",
    )
    assert not metadata_looks_broken(
        "Harnessing Drone Swarms for Enhanced Search and Rescue Operations",
        ["Khan. A"],
        journal_name="Frontiers in Computational Spatial Intelligence",
    )
