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
        authors=["Hasanain. S"],
        title="Secure Scheme",
        volume=8,
        issue=5,
        page_start=1788,
        page_end=1813,
        month="August",
        year=2026,
    )
    assert "IJIST" in text
    assert "Vol. 8" in text
    assert "1788-1813" in text
