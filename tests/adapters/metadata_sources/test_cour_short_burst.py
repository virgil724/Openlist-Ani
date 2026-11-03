"""homelab: a short delayed burst must not count as its own cour.

TMDB 261343 (Chitose-kun wa Ramune Bin no Naka) keeps everything in S01:
E01-E10 (2025-10..12), E11-E13 (2026-03, delayed), E14-E25 (2026-10.., the
fansubs' "season 2").  Fansub S2E03 is S01E16, not S01E13.
"""

from __future__ import annotations

from openlist_ani.adapters.metadata_sources.models import SeasonInfo
from openlist_ani.adapters.metadata_sources.tmdb.cour.detector import (
    detect_cours_from_episodes,
)
from openlist_ani.adapters.metadata_sources.tmdb.episode_mapper import (
    CourMappingStrategy,
    MappingContext,
)

_DATES = [
    "2025-10-07", "2025-10-14", "2025-10-21", "2025-10-28", "2025-11-04",
    "2025-12-02", "2025-12-09", "2025-12-16", "2025-12-23", "2025-12-30",
    "2026-03-30", "2026-03-31", "2026-03-31",
    "2026-10-13", "2026-10-20", "2026-10-27", "2026-11-03", "2026-11-10",
    "2026-11-17", "2026-11-24", "2026-12-01", "2026-12-08", "2026-12-15",
    "2026-12-22", "2026-12-29",
]  # fmt: skip
EPISODES = [
    {"episode_number": index + 1, "air_date": date} for index, date in enumerate(_DATES)
]


class FakeTMDB:
    async def get_season_episodes(self, tmdb_id, season_number):
        return EPISODES


def test_short_middle_burst_is_folded_into_previous_cour():
    cours = detect_cours_from_episodes(EPISODES)
    assert [(c.start_episode, c.end_episode) for c in cours] == [(1, 13), (14, 25)]


def test_short_last_group_is_kept_as_new_cour():
    episodes = EPISODES[:10] + [{"episode_number": 11, "air_date": "2026-10-13"}]
    cours = detect_cours_from_episodes(episodes)
    assert [(c.start_episode, c.end_episode) for c in cours] == [(1, 10), (11, 11)]


async def test_fansub_season_two_maps_to_real_second_cour():
    ctx = MappingContext(
        tmdb_id=261343,
        fansub_season=2,
        fansub_episode=3,
        sorted_seasons=[SeasonInfo(season_number=1, episode_count=25)],
        tmdb_client=FakeTMDB(),
    )
    mapping = await CourMappingStrategy().try_map(ctx)
    assert (mapping.season, mapping.episode) == (1, 16)
