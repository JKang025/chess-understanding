from __future__ import annotations

import json
import os
import platform
import shutil
import stat
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

STOCKFISH_REPO = "official-stockfish/Stockfish"
RELEASES_API = f"https://api.github.com/repos/{STOCKFISH_REPO}/releases/latest"


def stockfish_binary_path(base_dir: Path | None = None) -> Path:
    root = base_dir or Path("artifacts/bin")
    return root / "stockfish"


def ensure_stockfish(base_dir: Path | None = None) -> Path:
    path = stockfish_binary_path(base_dir)
    if path.is_file() and os.access(path, os.X_OK):
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    _download_stockfish(path)
    return path


def _download_stockfish(dest: Path) -> None:
    asset_name, download_url = _resolve_release_asset()
    with tempfile.TemporaryDirectory() as tmp_dir:
        archive_path = Path(tmp_dir) / asset_name
        _download_file(download_url, archive_path)
        _extract_binary(archive_path, dest)


def _resolve_release_asset() -> tuple[str, str]:
    request = urllib.request.Request(
        RELEASES_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "chess-understanding"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            release = json.load(response)
    except urllib.error.URLError as exc:
        raise RuntimeError("Failed to fetch Stockfish release metadata.") from exc

    assets = {asset["name"]: asset["browser_download_url"] for asset in release["assets"]}
    for candidate in _asset_candidates():
        if candidate in assets:
            return candidate, assets[candidate]

    available = ", ".join(sorted(assets))
    raise RuntimeError(
        f"No compatible Stockfish binary found for this platform. Available assets: {available}"
    )


def _asset_candidates() -> list[str]:
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin":
        if machine in {"arm64", "aarch64"}:
            return ["stockfish-macos-m1-apple-silicon.tar"]
        return [
            "stockfish-macos-x86-64-avx2.tar",
            "stockfish-macos-x86-64-bmi2.tar",
            "stockfish-macos-x86-64-sse41-popcnt.tar",
            "stockfish-macos-x86-64.tar",
        ]

    if system == "linux":
        if machine in {"arm64", "aarch64"}:
            return ["stockfish-android-armv8.tar", "stockfish-android-armv8-dotprod.tar"]
        return [
            "stockfish-ubuntu-x86-64-avx2.tar",
            "stockfish-ubuntu-x86-64-bmi2.tar",
            "stockfish-ubuntu-x86-64-sse41-popcnt.tar",
            "stockfish-ubuntu-x86-64.tar",
        ]

    raise RuntimeError(f"Unsupported platform: {system} {machine}")


def _download_file(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "chess-understanding"})
    try:
        with urllib.request.urlopen(request, timeout=300) as response, dest.open("wb") as out:
            shutil.copyfileobj(response, out)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to download Stockfish from {url}") from exc


def _extract_binary(archive_path: Path, dest: Path) -> None:
    with tarfile.open(archive_path) as archive:
        executables = [
            member
            for member in archive.getmembers()
            if member.isfile() and (member.mode & stat.S_IXUSR)
        ]
        if not executables:
            raise RuntimeError(f"Could not find stockfish binary in {archive_path.name}")

        binary_member = next(
            (member for member in executables if Path(member.name).name == "stockfish"),
            executables[0],
        )

        extracted = archive.extractfile(binary_member)
        if extracted is None:
            raise RuntimeError(f"Failed to extract stockfish binary from {archive_path.name}")

        with extracted, dest.open("wb") as out:
            shutil.copyfileobj(extracted, out)

    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    _clear_macos_quarantine(dest)


def _clear_macos_quarantine(path: Path) -> None:
    if platform.system().lower() != "darwin":
        return
    if shutil.which("xattr") is None:
        return
    try:
        import subprocess

        subprocess.run(
            ["xattr", "-d", "com.apple.quarantine", str(path)],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass
