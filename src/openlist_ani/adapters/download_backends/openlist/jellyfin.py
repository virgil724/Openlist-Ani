"""Tell Jellyfin about newly organized files.

Files reach the library through OpenList on another NFS client, so Jellyfin
gets no inotify event.  ``POST /Library/Media/Updated`` queues a refresh of
just the touched paths, the same call Sonarr and Radarr use.

Configured through the environment; nothing happens when it is unset:

- ``OANI_JELLYFIN_URL``      e.g. ``http://jellyfin.jellyfin.svc:8096``
- ``OANI_JELLYFIN_API_KEY``  Jellyfin API key
- ``OANI_JELLYFIN_PATH_MAP`` ``<openlist prefix>=<jellyfin prefix>``,
  e.g. ``/video=/media/video``
"""

from __future__ import annotations

import os
import posixpath
from collections.abc import Iterable

import aiohttp

from openlist_ani.logger import logger

from .library import DUPLICATES_DIRECTORY_NAME


class JellyfinNotifier:
    def __init__(self, url: str, api_key: str, path_map: tuple[str, str]) -> None:
        self._url = url.rstrip("/")
        self._api_key = api_key
        self._source_prefix = path_map[0].rstrip("/")
        self._target_prefix = path_map[1].rstrip("/")

    @classmethod
    def from_environment(cls) -> JellyfinNotifier | None:
        url = os.environ.get("OANI_JELLYFIN_URL", "").strip()
        api_key = os.environ.get("OANI_JELLYFIN_API_KEY", "").strip()
        path_map = os.environ.get("OANI_JELLYFIN_PATH_MAP", "").strip()
        if not (url and api_key and "=" in path_map):
            return None
        source, target = path_map.split("=", 1)
        return cls(url, api_key, (source.strip(), target.strip()))

    def jellyfin_path(self, openlist_path: str) -> str | None:
        path = posixpath.normpath(openlist_path)
        if f"/{DUPLICATES_DIRECTORY_NAME}/" in f"{path}/":
            return None
        if path != self._source_prefix and not path.startswith(
            self._source_prefix + "/"
        ):
            return None
        return self._target_prefix + path[len(self._source_prefix) :]

    async def notify(self, openlist_paths: Iterable[str]) -> None:
        paths = sorted(
            {mapped for item in openlist_paths if (mapped := self.jellyfin_path(item))}
        )
        if not paths:
            return
        body = {"Updates": [{"Path": path, "UpdateType": "Created"} for path in paths]}
        headers = {"Authorization": f'MediaBrowser Token="{self._api_key}"'}
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            ) as session:
                async with session.post(
                    f"{self._url}/Library/Media/Updated", json=body, headers=headers
                ) as response:
                    if response.status >= 300:
                        logger.warning(
                            f"Jellyfin media update returned HTTP {response.status}"
                        )
                        return
            logger.info(f"Jellyfin notified of {len(paths)} new file(s)")
        except (aiohttp.ClientError, TimeoutError) as error:
            logger.warning(f"Jellyfin media update failed: {error}")
