from pathlib import Path

from app.models import ArticleMeta, Author, FileLink
from app.redif import build_filename, build_handle, to_redif

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "V8i3p1429-1448.redif"


def test_build_filename():
    meta = ArticleMeta(doi="10.33411/IJIST/1936", volume="8", issue="3", pages="1429-1448")
    assert build_filename(meta) == "V8i3p1429-1448.redif"


def test_build_handle():
    meta = ArticleMeta(
        doi="10.33411/IJIST/1936",
        volume="8",
        issue="3",
        pages="1429-1448",
        year="2026",
    )
    assert build_handle(meta) == "RePEc:abq:IJIST1:v:8:y:2026:i:3:p:1429-1448"


def test_to_redif_matches_sample_shape():
    meta = ArticleMeta(
        doi="10.33411/IJIST/1936",
        title="No Smoke: Smart Surveillance for Cigarette Smoking Detection and Student Identification System",
        abstract="Cigarette smoking in educational institutes poses significant health...",
        keywords=["Cigarette smoking", "Face Detection", "Computer Vision", "Web Dashboard", "Object Detection"],
        authors=[
            Author(
                name="Zartasha Baloch",
                email="zartasha.baloch@faculty.muet.edu.pk",
                workplace="Mehran University of Engineering and Technology, Jamshoro",
            ),
            Author(
                name="Irfan Ali",
                workplace="Mehran University of Engineering and Technology, Jamshoro",
            ),
        ],
        journal="International Journal of Innovations in Science and Technology",
        pages="1429-1448",
        volume="8",
        issue="3",
        year="2026",
        month="June",
        file_links=[
            FileLink(
                url="https://journal.50sea.com/index.php/IJIST/article/view/1936/2862",
                format="Application/pdf",
            ),
            FileLink(
                url="https://journal.50sea.com/index.php/IJIST/article/view/1936",
                format="text/html",
            ),
        ],
    )
    text = to_redif(meta)
    assert text.startswith("Template-Type: ReDIF-Article 1.0\r\n")
    assert "Author-Name:Zartasha Baloch\r\n" in text
    assert "Author-Email:zartasha.baloch@faculty.muet.edu.pk\r\n" in text
    assert "Title:No Smoke:" in text
    assert "File-Format: Application/pdf\r\n" in text
    assert "Handle: RePEc:abq:IJIST1:v:8:y:2026:i:3:p:1429-1448\r\n" in text
    assert text.endswith("\r\n")

    # Sample file should share the same core field order markers
    sample = SAMPLE.read_text(encoding="utf-8")
    for marker in [
        "Template-Type: ReDIF-Article 1.0",
        "Author-Name:",
        "Title:",
        "Abstract:",
        "Keywords:",
        "Journal:",
        "Pages:",
        "Volume:",
        "Issue:",
        "Year:",
        "Month:",
        "DOI:",
        "File-URL:",
        "File-Format:",
        "Handle:",
    ]:
        assert marker in sample
        assert marker in text
