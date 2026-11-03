from datetime import datetime
from typing import Any

from ...models import CourGroup
from ..constants import COUR_GAP_DAYS


def detect_cours_from_episodes(
    episodes: list[dict[str, Any]], gap_days: int = COUR_GAP_DAYS
) -> list[CourGroup]:
    dated_episodes: list[tuple[int, datetime, str]] = []
    for ep in episodes:
        air_date_str = ep.get("air_date")
        ep_num = ep.get("episode_number")
        if not air_date_str or ep_num is None:
            continue
        try:
            air_date = datetime.strptime(air_date_str, "%Y-%m-%d")
            dated_episodes.append((ep_num, air_date, air_date_str))
        except ValueError:
            continue

    if not dated_episodes:
        return []

    dated_episodes.sort(key=lambda x: (x[1], x[0]))

    groups: list[list[tuple[int, datetime, str]]] = [[dated_episodes[0]]]

    for entry in dated_episodes[1:]:
        _ep_num, air_date, _air_date_str = entry
        prev_date = groups[-1][-1][1]
        delta = (air_date - prev_date).days
        if delta >= gap_days:
            groups.append([])
        groups[-1].append(entry)

    groups = _merge_short_groups(groups)
    return [_build_cour_group(index + 1, group) for index, group in enumerate(groups)]


# homelab: a short burst between two cours (delayed or catch-up episodes, e.g.
# Chitose-kun S01E11-13 aired months after E10) is not a season of its own.
# Folding it into the previous cour keeps fansub "season 2" on the real next
# cour.  The last group is left alone: a new cour may list only a few episodes.
MIN_COUR_EPISODES = 4


def _merge_short_groups(
    groups: list[list[tuple[int, datetime, str]]],
) -> list[list[tuple[int, datetime, str]]]:
    merged: list[list[tuple[int, datetime, str]]] = []
    for index, group in enumerate(groups):
        is_last = index == len(groups) - 1
        if merged and not is_last and len(group) < MIN_COUR_EPISODES:
            merged[-1] = merged[-1] + group
        else:
            merged.append(list(group))
    return merged


def _build_cour_group(
    cour_index: int, entries: list[tuple[int, datetime, str]]
) -> CourGroup:
    return CourGroup(
        cour_index=cour_index,
        start_episode=entries[0][0],
        end_episode=entries[-1][0],
        air_date_start=entries[0][2],
        air_date_end=entries[-1][2],
    )
