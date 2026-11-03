from __future__ import annotations

import pytest

from openlist_ani.adapters.download_backends.openlist.jellyfin import (
    JellyfinNotifier,
)
from openlist_ani.adapters.download_backends.openlist.library import (
    OpenListLibraryResolver,
    has_episode,
)
from openlist_ani.adapters.download_backends.openlist.models import FileEntry
from openlist_ani.application.ports import OrganizationRequest
from openlist_ani.domain.metadata import MetadataDocument, ReleaseMetadata
from openlist_ani.domain.naming import ReleaseDirectoryPlanner

BASE = "/video/動畫"


class FakeClient:
    def __init__(self, tree: dict[str, list[tuple[str, bool]]]) -> None:
        self.tree = tree
        self.calls: list[str] = []

    async def list_files(self, path: str):
        self.calls.append(path)
        if path not in self.tree:
            return None
        return [FileEntry(name=name, is_dir=is_dir) for name, is_dir in self.tree[path]]


def _metadata(**values) -> ReleaseMetadata:
    defaults = dict(
        anime_name="冷淡的佐藤同学只对我撒娇",
        season=1,
        episode=4,
        year=2026,
        external_ids={"tmdb": "316891"},
    )
    defaults.update(values)
    return ReleaseMetadata(**defaults)


def _request(metadata: ReleaseMetadata) -> OrganizationRequest:
    return OrganizationRequest(
        item_key="item",
        video_relative_path="a.mkv",
        sidecars=(),
        target_directory_path=ReleaseDirectoryPlanner().target_directory_path(
            BASE, metadata
        ),
        target_filename="x - S01E04.mkv",
        metadata=MetadataDocument(values=metadata),
    )


def test_planner_tags_tmdb_id_and_year():
    path = ReleaseDirectoryPlanner().target_directory_path(BASE, _metadata())
    assert path == f"{BASE}/冷淡的佐藤同学只对我撒娇 (2026) [tmdbid-316891]/Season 1"


def test_planner_without_tmdb_keeps_upstream_layout():
    path = ReleaseDirectoryPlanner().target_directory_path(
        BASE, _metadata(external_ids={})
    )
    assert path == f"{BASE}/冷淡的佐藤同学只对我撒娇/Season 1"


@pytest.mark.asyncio
async def test_existing_folder_matched_by_tmdb_id_and_season_folder_reused():
    series = "Shiotaiou no Satou-san ga Ore ni dake Amai (2026) [tmdbid-316891]"
    client = FakeClient(
        {
            BASE: [(series, True), ("Other (2020) [tmdbid-1]", True), (".x", True)],
            f"{BASE}/{series}": [("Season 01", True)],
            f"{BASE}/{series}/Season 01": [("Satou - S01E01.mkv", False)],
        }
    )
    [resolved] = await OpenListLibraryResolver(client).resolve(
        BASE, (_request(_metadata()),)
    )
    assert resolved.target_directory_path == f"{BASE}/{series}/Season 01"


@pytest.mark.asyncio
async def test_existing_episode_goes_to_hidden_duplicates_tree():
    series = "Shiotaiou no Satou-san ga Ore ni dake Amai (2026) [tmdbid-316891]"
    client = FakeClient(
        {
            BASE: [(series, True)],
            f"{BASE}/{series}": [("Season 01", True)],
            f"{BASE}/{series}/Season 01": [
                ("Satou - S01E04.mkv", False),
                ("Satou - S01E04.zh-TW.ass", False),
            ],
        }
    )
    [resolved] = await OpenListLibraryResolver(client).resolve(
        BASE, (_request(_metadata()),)
    )
    assert resolved.target_directory_path == (
        f"{BASE}/.oani-duplicates/{series}/Season 01"
    )


@pytest.mark.asyncio
async def test_new_series_keeps_planned_target():
    client = FakeClient({BASE: [("Other (2020) [tmdbid-1]", True)]})
    request = _request(_metadata())
    [resolved] = await OpenListLibraryResolver(client).resolve(BASE, (request,))
    assert resolved is request


@pytest.mark.asyncio
async def test_unlistable_base_keeps_planned_target():
    request = _request(_metadata())
    [resolved] = await OpenListLibraryResolver(FakeClient({})).resolve(BASE, (request,))
    assert resolved is request


def test_has_episode_matches_tokens_not_substrings():
    assert has_episode(["A - S01E04.mkv"], 1, 4)
    assert has_episode(["A S1E4 [1080p].mp4"], 1, 4)
    assert not has_episode(["A - S01E14.mkv"], 1, 4)
    assert not has_episode(["A - S01E04.ass"], 1, 4)
    assert not has_episode(["AS01E04x.mkv"], 1, 4)


def test_jellyfin_path_mapping_skips_duplicates_and_outside_paths():
    notifier = JellyfinNotifier("http://jf", "key", ("/video", "/media/video"))
    assert notifier.jellyfin_path("/video/動畫/A/Season 01/a.mkv") == (
        "/media/video/動畫/A/Season 01/a.mkv"
    )
    assert notifier.jellyfin_path("/video/動畫/.oani-duplicates/A/a.mkv") is None
    assert notifier.jellyfin_path("/videos/a.mkv") is None


def test_jellyfin_notifier_disabled_without_environment(monkeypatch):
    for name in (
        "OANI_JELLYFIN_URL",
        "OANI_JELLYFIN_API_KEY",
        "OANI_JELLYFIN_PATH_MAP",
    ):
        monkeypatch.delenv(name, raising=False)
    assert JellyfinNotifier.from_environment() is None
