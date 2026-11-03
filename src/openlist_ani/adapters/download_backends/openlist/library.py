"""Fit organization targets into an existing Jellyfin library.

The planner names new series ``Name (Year) [tmdbid-N]/Season N``.  A library
that already holds the series under another name (another language, a manual
rename) is matched by its ``[tmdbid-N]`` tag instead, and an existing
``Season 01``-style folder is reused.  An episode that is already present is
sent to a hidden ``.oani-duplicates`` tree (Jellyfin ignores dot paths) rather
than getting a ``(1)`` suffix next to the original.

Resolution runs once, before the organization requests are persisted, so a
retried job keeps the same targets.
"""

from __future__ import annotations

import os
import posixpath
import re
from dataclasses import replace

from openlist_ani.application.ports import OrganizationRequest
from openlist_ani.logger import logger

from .client import OpenListClient
from .models import FileEntry

DUPLICATES_DIRECTORY_NAME = ".oani-duplicates"

_TMDB_TAG = re.compile(r"\[tmdbid-(\d+)\]", re.IGNORECASE)
_SEASON_DIRECTORY = re.compile(r"^season\s*0*(\d+)$", re.IGNORECASE)
_VIDEO_EXTENSIONS = frozenset(
    {".mkv", ".mp4", ".avi", ".m2ts", ".ts", ".webm", ".mov", ".wmv", ".flv", ".rmvb"}
)


def tmdb_id_of(directory_name: str) -> str | None:
    match = _TMDB_TAG.search(directory_name)
    return match.group(1) if match else None


def season_number_of(directory_name: str) -> int | None:
    match = _SEASON_DIRECTORY.match(directory_name.strip())
    return int(match.group(1)) if match else None


_ANY_SEASON_EPISODE = re.compile(r"(?<![0-9a-z])s\d+e\d+(?![0-9])", re.IGNORECASE)
# Fansub-style numbering for files without SxxEyy; the season comes from the
# folder.  " - 04 ", " - 04v2", "[04]", "第04話", "EP04".
_BARE_EPISODE = re.compile(
    r"(?:\s-\s|\[|第|(?<![0-9a-z])ep?\s?)0*(\d{1,4})(?:v\d+)?(?=[\s\].(_]|話|话|集|$)",
    re.IGNORECASE,
)


def episode_numbers(filename: str, season: int) -> set[int]:
    """Episode numbers a video filename claims for ``season``."""
    stem = os.path.splitext(filename)[0]
    tokens = _ANY_SEASON_EPISODE.findall(stem)
    if tokens:
        found = set()
        for token in tokens:
            s, e = re.match(r"s(\d+)e(\d+)", token, re.IGNORECASE).groups()
            if int(s) == season:
                found.add(int(e))
        return found
    return {int(number) for number in _BARE_EPISODE.findall(stem)}


def has_episode(filenames: list[str], season: int, episode: int) -> bool:
    return any(
        os.path.splitext(name)[1].lower() in _VIDEO_EXTENSIONS
        and episode in episode_numbers(name, season)
        for name in filenames
    )


class OpenListLibraryResolver:
    def __init__(self, client: OpenListClient) -> None:
        self._client = client

    async def resolve(
        self, base_path: str, requests: tuple[OrganizationRequest, ...]
    ) -> tuple[OrganizationRequest, ...]:
        listings: dict[str, list[FileEntry] | None] = {}

        async def listing(path: str) -> list[FileEntry] | None:
            if path not in listings:
                listings[path] = await self._client.list_files(path)
            return listings[path]

        return tuple(
            [
                await self._resolve_one(base_path, request, listing)
                for request in requests
            ]
        )

    async def _resolve_one(self, base_path, request, listing) -> OrganizationRequest:
        base = posixpath.normpath(base_path or "/")
        target = posixpath.normpath(request.target_directory_path)
        relative = posixpath.relpath(target, base)
        parts = relative.split("/")
        if len(parts) != 2 or relative.startswith(".."):
            return request
        series, season_dir = parts
        values = request.metadata.values

        base_entries = await listing(base)
        if base_entries is None:
            logger.warning(f"Library lookup skipped, cannot list {base}")
            return request
        directories = sorted(entry.name for entry in base_entries if entry.is_dir)

        tmdb_id = tmdb_id_of(series)
        if tmdb_id:
            matches = [name for name in directories if tmdb_id_of(name) == tmdb_id]
            if matches:
                if len(matches) > 1:
                    logger.warning(
                        f"Several library folders carry tmdbid-{tmdb_id}: "
                        f"{matches}; using {matches[0]}"
                    )
                series = matches[0]

        season_files: list[str] = []
        if series in directories:
            series_entries = await listing(posixpath.join(base, series)) or []
            for entry in sorted(series_entries, key=lambda item: item.name):
                if entry.is_dir and season_number_of(entry.name) == (
                    values.season or 1
                ):
                    season_dir = entry.name
                    break
            season_entries = await listing(posixpath.join(base, series, season_dir))
            season_files = [
                entry.name for entry in season_entries or () if not entry.is_dir
            ]

        resolved = posixpath.join(base, series, season_dir)
        if (
            values.season is not None
            and values.episode is not None
            and has_episode(season_files, values.season, values.episode)
        ):
            resolved = posixpath.join(
                base, DUPLICATES_DIRECTORY_NAME, series, season_dir
            )
            logger.warning(
                f"S{values.season:02d}E{values.episode:02d} already exists in "
                f"{series}/{season_dir}; organizing into {resolved}"
            )
        elif resolved != target:
            logger.info(f"Library folder matched: {target} -> {resolved}")
        if resolved == target:
            return request
        return replace(request, target_directory_path=resolved)
