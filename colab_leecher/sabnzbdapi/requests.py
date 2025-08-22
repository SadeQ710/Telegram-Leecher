import httpx
from typing import Any, Dict, List, Optional, Union


class SabnzbdClient:
    """
    A minimal asynchronous SABnzbd API wrapper.

    This client implements only the subset of the SABnzbd API that is
    required by the Telegram‑Leecher project. Additional endpoints can
    be added as needed by extending this class.
    """

    # Track login status globally.  The upstream implementation toggles
    # this flag based on a successful check of server configuration.  For
    # simplicity we leave it as False and leave login management to the
    # caller.
    LOGGED_IN: bool = False

    def __init__(
        self,
        host: str,
        api_key: str,
        port: Union[int, str] = 8070,
        verify_certificate: bool = False,
        timeout: int = 60,
    ) -> None:
        host = host.rstrip("/")
        self._base_url = f"{host}:{port}/sabnzbd/api"
        self._default_params: Dict[str, Any] = {
            "apikey": api_key,
            "output": "json",
        }
        self._client = httpx.AsyncClient(
            verify=verify_certificate,
            timeout=timeout,
        )

    async def _request(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform a GET request against the SABnzbd API and return the JSON response.

        Raises a generic RuntimeError if the request fails for any reason.  The
        calling code is expected to handle these errors gracefully.
        """
        try:
            response = await self._client.get(
                self._base_url,
                params={**self._default_params, **params},
            )
            response.raise_for_status()
            data = response.json()
            if data is None:
                raise RuntimeError("Empty response from SABnzbd")
            return data
        except Exception as exc:
            raise RuntimeError(f"SABnzbd API request failed: {exc}") from exc

    # Basic API methods -------------------------------------------------------
    async def add_uri(
        self,
        url: str = "",
        file: str = "",
        nzbname: str = "",
        password: str = "",
        cat: str = "*",
        priority: int = 0,
        pp: int = 1,
    ) -> Dict[str, Any]:
        """
        Add an NZB URI or a local file to SABnzbd.

        Parameters mirror the official API; see the SABnzbd API docs for details.
        """
        mode = "addlocalfile" if file else "addurl"
        name = file if file else url
        params = {
            "mode": mode,
            "name": name,
            "nzbname": nzbname,
            "password": password,
            "cat": cat,
            "priority": priority,
            "pp": pp,
        }
        return await self._request(params)

    async def get_downloads(self, nzo_ids: Optional[Union[str, List[str]]] = None) -> Dict[str, Any]:
        """
        Retrieve the current download queue from SABnzbd.

        If `nzo_ids` is provided it can be a single ID or a list of IDs.
        """
        params: Dict[str, Any] = {"mode": "queue"}
        if nzo_ids:
            if isinstance(nzo_ids, list):
                params["nzo_ids"] = ",".join(nzo_ids)
            else:
                params["nzo_ids"] = nzo_ids
        return await self._request(params)

    async def get_history(self, nzo_ids: Optional[Union[str, List[str]]] = None) -> Dict[str, Any]:
        """
        Retrieve the download history from SABnzbd.
        """
        params: Dict[str, Any] = {"mode": "history"}
        if nzo_ids:
            if isinstance(nzo_ids, list):
                params["nzo_ids"] = ",".join(nzo_ids)
            else:
                params["nzo_ids"] = nzo_ids
        return await self._request(params)

    async def delete_history(self, nzo_id: str, delete_files: bool = False) -> Dict[str, Any]:
        """
        Delete a history entry. If `delete_files` is True the associated files are removed.
        """
        params: Dict[str, Any] = {
            "mode": "history",
            "name": "delete",
            "value": nzo_id,
        }
        if delete_files:
            params["del_files"] = "1"
        return await self._request(params)

    async def delete_job(self, nzo_id: str, delete_files: bool = False) -> Dict[str, Any]:
        """
        Delete a job from the queue. Optionally delete downloaded files.
        """
        params: Dict[str, Any] = {
            "mode": "queue",
            "name": "delete",
            "value": nzo_id,
        }
        if delete_files:
            params["del_files"] = "1"
        return await self._request(params)

    async def pause_job(self, nzo_id: str) -> Dict[str, Any]:
        """
        Pause an active job.
        """
        return await self._request({"mode": "queue", "name": "pause", "value": nzo_id})

    async def resume_job(self, nzo_id: str) -> Dict[str, Any]:
        """
        Resume a paused job.
        """
        return await self._request({"mode": "queue", "name": "resume", "value": nzo_id})

    async def create_category(self, name: str, directory: str) -> Dict[str, Any]:
        """
        Create or update a category with the given name and path.
        """
        return await self._request(
            {"mode": "set_category", "name": name, "dir": directory}
        )

    async def delete_category(self, name: str) -> Dict[str, Any]:
        """
        Delete a previously defined category.
        """
        return await self._request({"mode": "delete_category", "value": name})

    async def get_files(self, nzo_id: str) -> Dict[str, Any]:
        """
        Get the list of files associated with a given job ID.
        """
        return await self._request({"mode": "listfiles", "value": nzo_id})

    async def close(self) -> None:
        """
        Close the underlying HTTP client.
        """
        await self._client.aclose()