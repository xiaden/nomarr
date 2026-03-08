"""Synchronous Subsonic API client for Navidrome communication.

Uses the Subsonic token authentication scheme and JSON responses.
All methods raise SubsonicApiError on non-ok Subsonic responses.
"""

import hashlib
import logging
import secrets
from typing import Any

import httpx

from nomarr.helpers.exceptions import SubsonicApiError

logger = logging.getLogger(__name__)

_API_VERSION = "1.16.1"
_CLIENT_NAME = "nomarr"
_SALT_LENGTH = 12


class SubsonicClient:
    """Synchronous HTTP client for the Subsonic/Navidrome API.

    Uses token-based authentication (md5(password + salt)) and requests
    JSON responses via the ``f=json`` parameter.
    """

    def __init__(self, base_url: str, user: str, password: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._user = user
        self._password = password
        self._http = httpx.Client(timeout=60.0)

    def close(self) -> None:
        """Close the underlying HTTP client to release resources."""
        self._http.close()

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _make_auth_params(self) -> dict[str, str]:
        """Generate per-request auth parameters using the Subsonic token scheme."""
        salt = secrets.token_hex(_SALT_LENGTH // 2)  # 12 hex chars
        token = hashlib.md5((self._password + salt).encode()).hexdigest()
        return {
            "u": self._user,
            "t": token,
            "s": salt,
            "v": _API_VERSION,
            "c": _CLIENT_NAME,
            "f": "json",
        }

    # ------------------------------------------------------------------
    # Request infrastructure
    # ------------------------------------------------------------------

    def _request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        raw_params: list[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Send a GET request and return the parsed Subsonic response body.

        Args:
            endpoint: Subsonic REST endpoint (e.g. ``ping.view``).
            params: Additional query parameters as a dict.
            raw_params: Raw (key, value) pairs for repeated-parameter encoding
                        (e.g. multiple ``songId`` values for createPlaylist).

        Returns:
            The inner response dict from ``subsonic-response``.

        Raises:
            SubsonicApiError: If the Subsonic response status is not ``ok``.
            httpx.HTTPStatusError: If the HTTP status code indicates failure.
        """
        url = f"{self._base_url}/rest/{endpoint}"
        query_params: list[tuple[str, str | int | float | bool | None]] = list(self._make_auth_params().items())
        if params:
            query_params.extend((str(k), str(v)) for k, v in params.items())
        if raw_params:
            query_params.extend(raw_params)

        response = self._http.get(url, params=httpx.QueryParams(query_params))
        response.raise_for_status()

        data: dict[str, Any] = response.json()
        subsonic_response: dict[str, Any] = data.get("subsonic-response", {})

        status = subsonic_response.get("status", "")
        if status != "ok":
            error = subsonic_response.get("error", {})
            raise SubsonicApiError(
                code=error.get("code", -1),
                message=error.get("message", f"Unknown Subsonic error (status={status})"),
            )

        return subsonic_response

    # ------------------------------------------------------------------
    # API methods
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Test the connection to the Subsonic server.

        Returns:
            ``True`` if the server responds with status ``ok``.
        """
        try:
            self._request("ping.view")
        except (SubsonicApiError, httpx.HTTPError):
            return False
        return True

    def get_album_list2(
        self, type: str, size: int, offset: int
    ) -> list[dict[str, Any]]:
        """Get a list of albums using ID3 tags (``getAlbumList2``).

        Args:
            type: Sort order (e.g. ``alphabeticalByName``, ``newest``).
            size: Max number of albums to return (max 500).
            offset: Pagination offset.

        Returns:
            List of album dicts.
        """
        resp = self._request("getAlbumList2.view", {"type": type, "size": size, "offset": offset})
        album_list = resp.get("albumList2", {})
        albums: list[dict[str, Any]] = album_list.get("album", [])
        return albums

    def get_album(self, album_id: str) -> dict[str, Any]:
        """Get details of an album including its songs (``getAlbum``).

        Args:
            album_id: The album ID.

        Returns:
            Album dict with a ``song`` list containing individual tracks.
        """
        resp = self._request("getAlbum.view", {"id": album_id})
        album: dict[str, Any] = resp.get("album", {})
        return album

    def get_playlists(self) -> list[dict[str, Any]]:
        """Get all playlists visible to the authenticated user.

        Returns:
            List of playlist dicts.
        """
        resp = self._request("getPlaylists.view")
        playlists_container = resp.get("playlists", {})
        playlists: list[dict[str, Any]] = playlists_container.get("playlist", [])
        return playlists

    def create_or_replace_playlist(
        self,
        name: str,
        song_ids: list[str],
        playlist_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new playlist or replace an existing one.

        Uses the Subsonic ``createPlaylist`` endpoint. When ``playlist_id`` is
        provided, the existing playlist is replaced (all songs are overwritten).
        Song IDs use Subsonic's repeated-parameter convention
        (``songId=1&songId=2&songId=3``).

        Args:
            name: Playlist name.
            song_ids: List of Navidrome song IDs to include.
            playlist_id: If set, replaces the existing playlist with this ID.

        Returns:
            The Subsonic response dict.
        """
        params: dict[str, str] = {"name": name}
        if playlist_id:
            params["playlistId"] = playlist_id

        raw_params: list[tuple[str, str]] = [("songId", sid) for sid in song_ids]

        return self._request("createPlaylist.view", params=params, raw_params=raw_params)

    def start_scan(self, full_scan: bool = False) -> dict[str, Any]:
        """Trigger a Navidrome library scan.

        The ``fullScan`` parameter is a Navidrome extension to the Subsonic API
        spec (the standard ``startScan`` takes no parameters).

        Args:
            full_scan: If ``True``, performs a full rescan instead of incremental.

        Returns:
            The Subsonic response dict with scan status.
        """
        params: dict[str, Any] = {}
        if full_scan:
            params["fullScan"] = "true"
        return self._request("startScan.view", params=params)
