import argparse
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

# Examples:
# uv run python scripts/download_lichess_games.py --month 2024-01
# uv run python scripts/download_lichess_games.py --start-month 2024-01 --end-month 2024-03
# uv run python scripts/download_lichess_games.py --month 2024-01 --out-dir artifacts/lichess
# uv run python scripts/download_lichess_games.py --month 2024-01 --dataset-prefix lichess_db_bullet_rated_

DATABASE_URL = "https://database.lichess.org/"
MONTH_RE = re.compile(r"(\d{4})-(\d{2})")


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for key, value in attrs:
            if key == "href" and value:
                self.hrefs.append(value)


@dataclass(frozen=True)
class YearMonth:
    year: int
    month: int

    @classmethod
    def parse(cls, value: str) -> "YearMonth":
        match = MONTH_RE.fullmatch(value)
        if not match:
            raise ValueError(f"Invalid month '{value}'. Use YYYY-MM.")
        year = int(match.group(1))
        month = int(match.group(2))
        if not 1 <= month <= 12:
            raise ValueError(f"Invalid month '{value}'. Month must be 01-12.")
        return cls(year=year, month=month)

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


def month_range(start: YearMonth, end: YearMonth) -> Iterable[YearMonth]:
    if (start.year, start.month) > (end.year, end.month):
        raise ValueError(f"start-month {start} must be <= end-month {end}")

    year = start.year
    month = start.month
    while (year, month) <= (end.year, end.month):
        yield YearMonth(year=year, month=month)
        month += 1
        if month > 12:
            month = 1
            year += 1


def fetch_links(url: str) -> list[str]:
    with urllib.request.urlopen(url) as response:
        html = response.read().decode("utf-8", errors="replace")

    parser = LinkParser()
    parser.feed(html)
    links = [urllib.parse.urljoin(url, href) for href in parser.hrefs]
    return links


def extract_month_from_name(name: str) -> YearMonth | None:
    match = MONTH_RE.search(name)
    if not match:
        return None
    return YearMonth(year=int(match.group(1)), month=int(match.group(2)))


def pick_matching_links(
    links: Iterable[str],
    months: set[YearMonth],
    prefix: str,
) -> list[str]:
    matches: list[str] = []
    for link in links:
        name = Path(urllib.parse.urlparse(link).path).name
        if not name.endswith(".pgn.zst"):
            continue
        if prefix and not name.startswith(prefix):
            continue

        link_month = extract_month_from_name(name)
        if link_month is None:
            continue
        if link_month in months:
            matches.append(link)

    return sorted(set(matches))


def download_file(url: str, destination: Path, force: bool) -> None:
    if destination.exists() and not force:
        print(f"skip (exists): {destination}")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"download: {url}")
    urllib.request.urlretrieve(url, destination)
    print(f"saved: {destination}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download monthly Lichess game archives by parsing https://database.lichess.org/."
        )
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--month", help="Single month in YYYY-MM format.")
    mode.add_argument("--start-month", help="Range start month in YYYY-MM format.")

    parser.add_argument("--end-month", help="Range end month in YYYY-MM format.")
    parser.add_argument(
        "--dataset-prefix",
        default="lichess_db_standard_rated_",
        help=(
            "Filename prefix to filter dataset links. "
            "Default: lichess_db_standard_rated_"
        ),
    )
    parser.add_argument(
        "--out-dir",
        default="data/lichess_open_database",
        help="Directory to store downloaded files.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download files even if they already exist.",
    )

    args = parser.parse_args()

    if args.month and args.end_month:
        parser.error("--end-month cannot be used with --month")

    if args.start_month and not args.end_month:
        parser.error("--end-month is required when using --start-month")

    if args.end_month and not args.start_month:
        parser.error("--start-month is required when using --end-month")

    return args


def main() -> None:
    args = parse_args()

    if args.month:
        target_months = {YearMonth.parse(args.month)}
    else:
        start = YearMonth.parse(args.start_month)
        end = YearMonth.parse(args.end_month)
        target_months = set(month_range(start, end))

    print(f"querying: {DATABASE_URL}")
    links = fetch_links(DATABASE_URL)
    matching_links = pick_matching_links(links, target_months, args.dataset_prefix)

    if not matching_links:
        raise SystemExit(
            "No matching links found. "
            "Check month(s) and --dataset-prefix against current options on the site."
        )

    output_dir = Path(args.out_dir)
    for link in matching_links:
        filename = Path(urllib.parse.urlparse(link).path).name
        download_file(link, output_dir / filename, force=args.force)

    print(f"done: downloaded {len(matching_links)} file(s)")


if __name__ == "__main__":
    main()
