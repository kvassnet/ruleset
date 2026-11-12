from pathlib import Path

import httpx

SOURCE_URL = "https://static-file-global.353355.xyz/rules/cn-additional-list.txt"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "list" / "domain-set" / "cn-additional-list.txt"


def main() -> None:
    response = httpx.get(SOURCE_URL, timeout=30.0, follow_redirects=True)
    response.raise_for_status()

    lines = [
        f".{line}"
        for raw_line in response.text.splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    ]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
