import hashlib
import os
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

import httpx

BASE_URL = "https://download.maxmind.com/geoip/databases/{edition}/download"
EDITIONS = (
    "GeoLite2-ASN",
    "GeoLite2-Country",
)
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "list" / "geodata"
TIMEOUT = httpx.Timeout(connect=30.0, read=120.0, write=30.0, pool=30.0)


def get_credentials() -> tuple[str, str]:
    account_id = os.environ.get("MAXMIND_ACCOUNT_ID", "").strip()
    license_key = os.environ.get("MAXMIND_LICENSE_KEY", "").strip()
    missing = [
        name
        for name, value in (
            ("MAXMIND_ACCOUNT_ID", account_id),
            ("MAXMIND_LICENSE_KEY", license_key),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required environment variable(s): {', '.join(missing)}")
    return account_id, license_key


def parse_sha256(content: str) -> str:
    tokens = content.strip().split()
    if not tokens:
        raise ValueError("Empty SHA-256 checksum response")
    digest = tokens[0].lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError(f"Invalid SHA-256 checksum format: {content!r}")
    return digest


def fetch_expected_sha256(client: httpx.Client, edition: str) -> str:
    url = BASE_URL.format(edition=edition)
    response = client.get(url, params={"suffix": "tar.gz.sha256"})
    response.raise_for_status()
    return parse_sha256(response.text)


def download_archive(client: httpx.Client, edition: str, destination: Path) -> str:
    url = BASE_URL.format(edition=edition)
    hasher = hashlib.sha256()
    with client.stream("GET", url, params={"suffix": "tar.gz"}) as response:
        response.raise_for_status()
        with destination.open("wb") as file:
            for chunk in response.iter_bytes():
                file.write(chunk)
                hasher.update(chunk)
    return hasher.hexdigest()


def extract_mmdb(archive_path: Path, edition: str, output_dir: Path) -> Path:
    target_filename = f"{edition}.mmdb"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / target_filename

    with tarfile.open(archive_path, mode="r:gz") as archive:
        matches = [
            member
            for member in archive.getmembers()
            if member.isfile() and PurePosixPath(member.name).name == target_filename
        ]
        if not matches:
            raise FileNotFoundError(f"{target_filename} not found in {archive_path.name}")
        if len(matches) > 1:
            raise ValueError(f"Multiple {target_filename} entries found in {archive_path.name}")

        extracted = archive.extractfile(matches[0])
        if extracted is None:
            raise RuntimeError(f"Failed to extract {target_filename} from {archive_path.name}")

        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=output_dir,
                prefix=f".{edition}.",
                suffix=".tmp",
                delete=False,
            ) as tmp_file:
                tmp_path = Path(tmp_file.name)
                with extracted:
                    shutil.copyfileobj(extracted, tmp_file)
            tmp_path.chmod(0o644)
            tmp_path.replace(output_path)
            tmp_path = None
        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink()

    return output_path


def update_edition(client: httpx.Client, edition: str, output_dir: Path = OUTPUT_DIR) -> Path:
    with tempfile.TemporaryDirectory() as tmp_dir:
        archive_path = Path(tmp_dir) / f"{edition}.tar.gz"
        expected_sha256 = fetch_expected_sha256(client, edition)
        actual_sha256 = download_archive(client, edition, archive_path)

        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"SHA-256 mismatch for {edition}: "
                f"expected {expected_sha256}, got {actual_sha256}"
            )

        return extract_mmdb(archive_path, edition, output_dir)


def main() -> None:
    account_id, license_key = get_credentials()

    with httpx.Client(
        auth=(account_id, license_key),
        follow_redirects=True,
        timeout=TIMEOUT,
    ) as client:
        for edition in EDITIONS:
            output_path = update_edition(client, edition)
            print(f"Updated {edition}: {output_path} ({output_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
