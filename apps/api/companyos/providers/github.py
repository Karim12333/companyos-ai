"""Minimal GitHub REST client. The token stays here; it is never returned to callers or the LLM."""

import base64
from typing import Any

import httpx

API = "https://api.github.com"
_transport: httpx.AsyncBaseTransport | None = None


class GitHubError(Exception):
    pass


def set_github_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    # Tests inject a fake GitHub; production uses the real network
    global _transport
    _transport = transport


class GitHubClient:
    def __init__(self, token: str) -> None:
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        async with httpx.AsyncClient(
            base_url=API, headers=self._headers, timeout=30, transport=_transport
        ) as client:
            response = await client.request(method, path, **kwargs)
        if response.status_code >= 400:
            message = response.json().get("message", "") if response.content else ""
            raise GitHubError(f"GitHub {response.status_code}: {message}"[:500])
        return response.json() if response.content else {}

    async def user(self) -> dict[str, Any]:
        return await self._call("GET", "/user")

    async def repo(self, repo: str) -> dict[str, Any]:
        return await self._call("GET", f"/repos/{repo}")

    async def branch(self, repo: str, branch: str) -> dict[str, Any]:
        return await self._call("GET", f"/repos/{repo}/branches/{branch}")

    async def list_files(self, repo: str, path: str, ref: str) -> list[dict[str, Any]]:
        data = await self._call("GET", f"/repos/{repo}/contents/{path}", params={"ref": ref})
        return data if isinstance(data, list) else [data]

    async def read_file(self, repo: str, path: str, ref: str) -> tuple[str, str]:
        data = await self._call("GET", f"/repos/{repo}/contents/{path}", params={"ref": ref})
        if isinstance(data, list) or data.get("type") != "file":
            raise GitHubError(f"{path} is not a file")
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace"), data["sha"]

    async def search_code(self, repo: str, query: str) -> list[dict[str, Any]]:
        data = await self._call("GET", "/search/code", params={"q": f"{query} repo:{repo}", "per_page": 20})
        return data.get("items", [])

    async def pull_request(self, repo: str, number: int) -> dict[str, Any]:
        return await self._call("GET", f"/repos/{repo}/pulls/{number}")

    async def checks(self, repo: str, ref: str) -> dict[str, Any]:
        return await self._call("GET", f"/repos/{repo}/commits/{ref}/check-runs")

    async def create_branch(self, repo: str, branch: str, from_branch: str) -> dict[str, Any]:
        base = await self.branch(repo, from_branch)
        return await self._call(
            "POST",
            f"/repos/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": base["commit"]["sha"]},
        )

    async def commit_files(
        self, repo: str, branch: str, message: str, files: dict[str, str]
    ) -> dict[str, Any]:
        """One commit for several files via the git data API; the ref update is never forced."""
        head = await self.branch(repo, branch)
        parent_sha = head["commit"]["sha"]
        base_tree = head["commit"]["commit"]["tree"]["sha"]
        tree = await self._call(
            "POST",
            f"/repos/{repo}/git/trees",
            json={
                "base_tree": base_tree,
                "tree": [
                    {"path": path, "mode": "100644", "type": "blob", "content": content}
                    for path, content in files.items()
                ],
            },
        )
        commit = await self._call(
            "POST",
            f"/repos/{repo}/git/commits",
            json={"message": message, "tree": tree["sha"], "parents": [parent_sha]},
        )
        await self._call(
            "PATCH", f"/repos/{repo}/git/refs/heads/{branch}", json={"sha": commit["sha"], "force": False}
        )
        return commit

    async def create_pull_request(
        self, repo: str, head: str, base: str, title: str, body: str
    ) -> dict[str, Any]:
        return await self._call(
            "POST", f"/repos/{repo}/pulls", json={"head": head, "base": base, "title": title, "body": body}
        )

    async def merge_pull_request(self, repo: str, number: int) -> dict[str, Any]:
        return await self._call("PUT", f"/repos/{repo}/pulls/{number}/merge", json={"merge_method": "squash"})

    async def delete_branch(self, repo: str, branch: str) -> dict[str, Any]:
        return await self._call("DELETE", f"/repos/{repo}/git/refs/heads/{branch}")
