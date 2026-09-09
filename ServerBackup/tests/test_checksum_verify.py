from pathlib import Path

from app.backup.checksum import sha256_file
from app.backup.verify import ArchiveIntegrityError, verify_archive
from tests.helpers import make_valid_archive


def test_sha256_stable(tmp_path: Path):
    path = tmp_path / "file.bin"
    path.write_bytes(b"hello world")
    assert sha256_file(path) == sha256_file(path)
    assert len(sha256_file(path)) == 64


def test_verify_valid_archive(tmp_path: Path):
    archive = make_valid_archive(tmp_path / "server-backup.tar.gz")
    result = verify_archive(
        archive,
        website_directories=["/var/www/journal.50sea.com"],
        ojs_private_files="/var/www/ojs-files",
        nginx_directory="/etc/nginx",
        databases=["journal"],
    )
    assert result["size"] > 0


def test_corrupt_archive_rejected(tmp_path: Path):
    archive = tmp_path / "server-backup.tar.gz"
    archive.write_bytes(b"this is not a tar")
    try:
        verify_archive(archive)
        assert False, "corrupt archive must not pass"
    except ArchiveIntegrityError:
        pass
