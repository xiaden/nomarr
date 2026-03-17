"""Tests for subsonic_client_comp.py."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import pytest
import requests

from nomarr.components.navidrome.subsonic_client_comp import SubsonicClient
from nomarr.helpers.exceptions import SubsonicApiError


def _ok_response(body: dict | None = None) -> dict:
    """Build a wrapped Subsonic JSON response with status=ok."""
    resp: dict = {"subsonic-response": {"status": "ok", "version": "1.16.1"}}
    if body:
        resp["subsonic-response"].update(body)
    return resp


def _error_response(code: int = 40, message: str = "Wrong credentials") -> dict:
    """Build a Subsonic error JSON response."""
    return {
        "subsonic-response": {
            "status": "failed",
            "version": "1.16.1",
            "error": {"code": code, "message": message},
        }
    }


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Create a mock requests Response."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


@pytest.mark.unit
class TestSubsonicAuthTokenGeneration:
    """Verify Subsonic token authentication scheme."""

    def test_auth_params_contain_required_keys(self) -> None:
        """Auth params must include u, t, s, v, c, f."""
        client = SubsonicClient("http://navidrome:4533", "admin", "secret")
        params = client._make_auth_params()

        assert params["u"] == "admin"
        assert params["v"] == "1.16.1"
        assert params["c"] == "nomarr"
        assert params["f"] == "json"
        assert "t" in params
        assert "s" in params

    def test_token_is_md5_of_password_plus_salt(self) -> None:
        """Token must be md5(password + salt)."""
        client = SubsonicClient("http://navidrome:4533", "admin", "secret")
        params = client._make_auth_params()

        expected = hashlib.md5(("secret" + params["s"]).encode()).hexdigest()
        assert params["t"] == expected

    def test_salt_is_12_hex_chars(self) -> None:
        """Salt must be 12 hex characters."""
        client = SubsonicClient("http://navidrome:4533", "admin", "secret")
        params = client._make_auth_params()
        salt = params["s"]

        assert len(salt) == 12
        assert all(c in "0123456789abcdef" for c in salt)

    def test_salt_changes_per_request(self) -> None:
        """Each call should generate a unique salt."""
        client = SubsonicClient("http://navidrome:4533", "admin", "secret")
        params1 = client._make_auth_params()
        params2 = client._make_auth_params()

        assert params1["s"] != params2["s"]


@pytest.mark.unit
class TestSubsonicUrlConstruction:
    """Verify URL construction and parameter encoding."""

    @patch.object(requests.Session, "get")
    def test_url_includes_rest_endpoint(self, mock_get: MagicMock) -> None:
        """Request URL is {base_url}/rest/{endpoint}."""
        mock_get.return_value = _mock_response(_ok_response())
        client = SubsonicClient("http://navidrome:4533", "admin", "secret")

        client.ping()

        call_args = mock_get.call_args
        assert call_args[0][0] == "http://navidrome:4533/rest/ping.view"

    @patch.object(requests.Session, "get")
    def test_trailing_slash_stripped_from_base_url(self, mock_get: MagicMock) -> None:
        """Trailing slash on base_url must not cause double slashes."""
        mock_get.return_value = _mock_response(_ok_response())
        client = SubsonicClient("http://navidrome:4533/", "admin", "secret")

        client.ping()

        call_args = mock_get.call_args
        assert call_args[0][0] == "http://navidrome:4533/rest/ping.view"

    @patch.object(requests.Session, "get")
    def test_common_auth_params_present(self, mock_get: MagicMock) -> None:
        """All 6 common auth params must be in every request."""
        mock_get.return_value = _mock_response(
            _ok_response({"albumList2": {"album": []}})
        )
        client = SubsonicClient("http://navidrome:4533", "admin", "secret")

        client.get_album_list2("alphabeticalByName", 500, 0)

        call_args = mock_get.call_args
        params = call_args[1]["params"] if "params" in call_args[1] else call_args[0][1]
        # params is a list of (key, value) tuples
        param_keys = [k for k, _ in params]

        for key in ["u", "t", "s", "v", "c", "f"]:
            assert key in param_keys, f"Missing auth param: {key}"


@pytest.mark.unit
class TestSubsonicJsonResponseParsing:
    """Verify JSON response body parsing."""

    @patch.object(requests.Session, "get")
    def test_ping_returns_true_on_ok(self, mock_get: MagicMock) -> None:
        """ping() returns True when status is ok."""
        mock_get.return_value = _mock_response(_ok_response())
        client = SubsonicClient("http://navidrome:4533", "admin", "secret")

        assert client.ping() is True

    @patch.object(requests.Session, "get")
    def test_ping_returns_false_on_error(self, mock_get: MagicMock) -> None:
        """ping() returns False when server returns a Subsonic error."""
        mock_get.return_value = _mock_response(_error_response())
        client = SubsonicClient("http://navidrome:4533", "admin", "secret")

        assert client.ping() is False

    @patch.object(requests.Session, "get")
    def test_ping_returns_false_on_http_error(self, mock_get: MagicMock) -> None:
        """ping() returns False when HTTP request fails."""
        mock_get.side_effect = requests.ConnectionError("Connection refused")
        client = SubsonicClient("http://navidrome:4533", "admin", "secret")

        assert client.ping() is False

    @patch.object(requests.Session, "get")
    def test_get_album_list2_returns_album_list(self, mock_get: MagicMock) -> None:
        """get_album_list2 extracts album list from response."""
        albums = [{"id": "al-1", "name": "Album 1"}, {"id": "al-2", "name": "Album 2"}]
        mock_get.return_value = _mock_response(
            _ok_response({"albumList2": {"album": albums}})
        )
        client = SubsonicClient("http://navidrome:4533", "admin", "secret")

        result = client.get_album_list2("alphabeticalByName", 500, 0)

        assert result == albums

    @patch.object(requests.Session, "get")
    def test_get_album_list2_returns_empty_on_no_albums(self, mock_get: MagicMock) -> None:
        """get_album_list2 returns empty list when albumList2 has no album key."""
        mock_get.return_value = _mock_response(
            _ok_response({"albumList2": {}})
        )
        client = SubsonicClient("http://navidrome:4533", "admin", "secret")

        result = client.get_album_list2("alphabeticalByName", 500, 0)

        assert result == []

    @patch.object(requests.Session, "get")
    def test_get_album_returns_album_with_songs(self, mock_get: MagicMock) -> None:
        """get_album extracts album dict including songs."""
        album = {
            "id": "al-1",
            "name": "High Voltage",
            "song": [
                {"id": "s-1", "title": "The Jack", "path": "ACDC/High voltage/ACDC - The Jack.mp3"},
                {"id": "s-2", "title": "TNT", "path": "ACDC/High voltage/ACDC - TNT.mp3"},
            ],
        }
        mock_get.return_value = _mock_response(_ok_response({"album": album}))
        client = SubsonicClient("http://navidrome:4533", "admin", "secret")

        result = client.get_album("al-1")

        assert result["id"] == "al-1"
        assert len(result["song"]) == 2
        assert result["song"][0]["path"] == "ACDC/High voltage/ACDC - The Jack.mp3"

    @patch.object(requests.Session, "get")
    def test_get_playlists_returns_playlist_list(self, mock_get: MagicMock) -> None:
        """get_playlists extracts playlist list from response."""
        playlists = [{"id": "pl-1", "name": "My Mix"}]
        mock_get.return_value = _mock_response(
            _ok_response({"playlists": {"playlist": playlists}})
        )
        client = SubsonicClient("http://navidrome:4533", "admin", "secret")

        result = client.get_playlists()

        assert result == playlists


@pytest.mark.unit
class TestSubsonicRepeatedSongIdEncoding:
    """Verify repeated songId parameter encoding for createPlaylist."""

    @patch.object(requests.Session, "get")
    def test_song_ids_encoded_as_repeated_params(self, mock_get: MagicMock) -> None:
        """createPlaylist sends songId=X&songId=Y&songId=Z."""
        mock_get.return_value = _mock_response(_ok_response())
        client = SubsonicClient("http://navidrome:4533", "admin", "secret")

        client.create_or_replace_playlist("Test", ["s-1", "s-2", "s-3"])

        call_args = mock_get.call_args
        params = call_args[1]["params"] if "params" in call_args[1] else call_args[0][1]
        song_ids = [v for k, v in params if k == "songId"]

        assert song_ids == ["s-1", "s-2", "s-3"]

    @patch.object(requests.Session, "get")
    def test_playlist_id_included_for_replace(self, mock_get: MagicMock) -> None:
        """When playlist_id is set, it is included in params."""
        mock_get.return_value = _mock_response(_ok_response())
        client = SubsonicClient("http://navidrome:4533", "admin", "secret")

        client.create_or_replace_playlist("Test", ["s-1"], playlist_id="pl-42")

        call_args = mock_get.call_args
        params = call_args[1]["params"] if "params" in call_args[1] else call_args[0][1]
        param_dict = dict(params)

        assert param_dict["playlistId"] == "pl-42"
        assert param_dict["name"] == "Test"


@pytest.mark.unit
class TestSubsonicErrorHandling:
    """Verify Subsonic error response handling."""

    @patch.object(requests.Session, "get")
    def test_subsonic_error_raises_exception(self, mock_get: MagicMock) -> None:
        """Non-ok Subsonic response raises SubsonicApiError."""
        mock_get.return_value = _mock_response(
            _error_response(code=40, message="Wrong username or password")
        )
        client = SubsonicClient("http://navidrome:4533", "admin", "wrong")

        with pytest.raises(SubsonicApiError) as exc_info:
            client.get_album_list2("alphabeticalByName", 500, 0)

        assert exc_info.value.code == 40
        assert "Wrong username or password" in exc_info.value.message

    @patch.object(requests.Session, "get")
    def test_error_code_preserved(self, mock_get: MagicMock) -> None:
        """Error code from Subsonic response is accessible on exception."""
        mock_get.return_value = _mock_response(
            _error_response(code=70, message="Not found")
        )
        client = SubsonicClient("http://navidrome:4533", "admin", "secret")

        with pytest.raises(SubsonicApiError) as exc_info:
            client.get_album("nonexistent")

        assert exc_info.value.code == 70

    @patch.object(requests.Session, "get")
    def test_http_error_propagates(self, mock_get: MagicMock) -> None:
        """HTTP-level errors (404, 500) are raised as requests exceptions."""
        mock_resp = MagicMock(spec=requests.Response)
        mock_resp.raise_for_status.side_effect = requests.HTTPError(
            "Server Error",
            response=mock_resp,
        )
        mock_get.return_value = mock_resp
        client = SubsonicClient("http://navidrome:4533", "admin", "secret")

        with pytest.raises(requests.HTTPError):
            client.get_album("al-1")
