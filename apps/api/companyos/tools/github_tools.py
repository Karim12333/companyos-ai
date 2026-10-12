"""GitHub agent tools. Allowlist, write switch and protected-branch rules are enforced here, not in prompts."""

import json
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.events import record_activity
from companyos.models import Integration
from companyos.models.enums import ActorType, RiskLevel
from companyos.providers.github import GitHubClient, GitHubError
from companyos.services.integrations import get_integration_secret
from companyos.tools.base import ToolContext, ToolDefinition, ToolExecutionError, ToolResult

PROTECTED_BRANCHES = {"main", "master"}
MAX_FILE_CHARS = 20_000
REPO_PATTERN = r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
BRANCH_PATTERN = r"^[A-Za-z0-9._/-]{1,100}$"


class RepoArgs(BaseModel):
    repo: str = Field(pattern=REPO_PATTERN, description="owner/name, must be on the organization allowlist")


class ListFilesArgs(RepoArgs):
    path: str = Field(default="", max_length=300)
    ref: str | None = Field(default=None, pattern=BRANCH_PATTERN)


class ReadFileArgs(RepoArgs):
    path: str = Field(min_length=1, max_length=300)
    ref: str | None = Field(default=None, pattern=BRANCH_PATTERN)


class SearchCodeArgs(RepoArgs):
    query: str = Field(min_length=2, max_length=200)


class BranchArgs(RepoArgs):
    branch: str = Field(pattern=BRANCH_PATTERN)


class PullRequestArgs(RepoArgs):
    number: int = Field(ge=1)


class CreateBranchArgs(BranchArgs):
    from_branch: str | None = Field(default=None, pattern=BRANCH_PATTERN)


class WriteFileArgs(BranchArgs):
    path: str = Field(min_length=1, max_length=300)
    content: str = Field(max_length=200_000)
    message: str = Field(min_length=3, max_length=300)


class CommitChangesArgs(BranchArgs):
    files: dict[str, str] = Field(min_length=1, max_length=30, description="path -> full new file content")
    message: str = Field(min_length=3, max_length=300)


class CreatePullRequestArgs(RepoArgs):
    head: str = Field(pattern=BRANCH_PATTERN)
    base: str | None = Field(default=None, pattern=BRANCH_PATTERN)
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(default="", max_length=20_000)


async def _connection(
    ctx: ToolContext, session: AsyncSession, repo: str, write: bool = False
) -> tuple[GitHubClient, dict[str, Any]]:
    integration = await session.scalar(
        select(Integration).where(
            Integration.organization_id == ctx.organization_id, Integration.provider_key == "github"
        )
    )
    token = (
        await get_integration_secret(session, integration) if integration and integration.enabled else None
    )
    if integration is None or not token:
        raise ToolExecutionError("GitHub is not connected for this organization")
    config = integration.config or {}
    allowed = {item.lower() for item in config.get("allowed_repos", [])}
    if repo.lower() not in allowed:
        raise ToolExecutionError(f"Repository '{repo}' is not on this organization's allowlist")
    if write and not config.get("write_enabled"):
        raise ToolExecutionError("Write actions are disabled for GitHub in this organization")
    return GitHubClient(token), config


def _protected(branch: str, config: dict[str, Any]) -> bool:
    return branch.lower() in PROTECTED_BRANCHES | {str(config.get("default_branch", "main")).lower()}


def _guard_branch(branch: str, config: dict[str, Any]) -> None:
    # Hard block: no setting or approval can open a direct write to main/master/default
    if _protected(branch, config):
        raise ToolExecutionError(
            f"Direct changes to protected branch '{branch}' are blocked; use a new branch and a PR"
        )


async def _record(
    ctx: ToolContext, session: AsyncSession, event: str, summary: str, data: dict[str, Any]
) -> None:
    await record_activity(
        session,
        organization_id=ctx.organization_id,
        event_type=f"github.{event}",
        summary=summary,
        objective_id=ctx.objective_id,
        agent_id=ctx.agent_id,
        task_id=ctx.task_id,
        actor_type=ActorType.AGENT,
        data=data,
    )


async def _guarded(call: Any) -> Any:
    try:
        return await call
    except GitHubError as error:
        raise ToolExecutionError(str(error)) from error


async def github_get_repo_info(ctx: ToolContext, session: AsyncSession, args: RepoArgs) -> ToolResult:
    client, _ = await _connection(ctx, session, args.repo)
    repo = await _guarded(client.repo(args.repo))
    info = {
        key: repo.get(key) for key in ("full_name", "description", "default_branch", "language", "visibility")
    }
    return ToolResult(content=json.dumps(info), data={"repo": args.repo})


async def github_list_files(ctx: ToolContext, session: AsyncSession, args: ListFilesArgs) -> ToolResult:
    client, config = await _connection(ctx, session, args.repo)
    items = await _guarded(
        client.list_files(args.repo, args.path, args.ref or config.get("default_branch", "main"))
    )
    listing = "\n".join(f"{item.get('type')}  {item.get('path')}" for item in items[:300])
    return ToolResult(content=listing or "(empty)", untrusted=True)


async def github_read_file(ctx: ToolContext, session: AsyncSession, args: ReadFileArgs) -> ToolResult:
    client, config = await _connection(ctx, session, args.repo)
    content, _ = await _guarded(
        client.read_file(args.repo, args.path, args.ref or config.get("default_branch", "main"))
    )
    return ToolResult(content=content[:MAX_FILE_CHARS], untrusted=True)


async def github_search_code(ctx: ToolContext, session: AsyncSession, args: SearchCodeArgs) -> ToolResult:
    client, _ = await _connection(ctx, session, args.repo)
    items = await _guarded(client.search_code(args.repo, args.query))
    return ToolResult(
        content="\n".join(item.get("path", "") for item in items) or "No matches.", untrusted=True
    )


async def github_get_branch(ctx: ToolContext, session: AsyncSession, args: BranchArgs) -> ToolResult:
    client, _ = await _connection(ctx, session, args.repo)
    branch = await _guarded(client.branch(args.repo, args.branch))
    return ToolResult(
        content=json.dumps(
            {"name": branch["name"], "sha": branch["commit"]["sha"], "protected": branch.get("protected")}
        )
    )


async def github_get_pull_request(
    ctx: ToolContext, session: AsyncSession, args: PullRequestArgs
) -> ToolResult:
    client, _ = await _connection(ctx, session, args.repo)
    pr = await _guarded(client.pull_request(args.repo, args.number))
    info = {key: pr.get(key) for key in ("number", "title", "state", "merged", "html_url", "mergeable")}
    return ToolResult(content=json.dumps(info), untrusted=True)


async def github_get_checks(ctx: ToolContext, session: AsyncSession, args: BranchArgs) -> ToolResult:
    client, _ = await _connection(ctx, session, args.repo)
    data = await _guarded(client.checks(args.repo, args.branch))
    runs = [
        {"name": run.get("name"), "status": run.get("status"), "conclusion": run.get("conclusion")}
        for run in data.get("check_runs", [])
    ]
    await _record(
        ctx,
        session,
        "checks",
        f"Checked CI on {args.repo}@{args.branch}",
        {"repo": args.repo, "branch": args.branch, "checks": runs},
    )
    return ToolResult(content=json.dumps(runs) if runs else "No check runs reported for this branch yet.")


async def github_create_branch(ctx: ToolContext, session: AsyncSession, args: CreateBranchArgs) -> ToolResult:
    client, config = await _connection(ctx, session, args.repo, write=True)
    _guard_branch(args.branch, config)
    await _guarded(
        client.create_branch(args.repo, args.branch, args.from_branch or config.get("default_branch", "main"))
    )
    await _record(
        ctx,
        session,
        "branch_created",
        f"Created branch {args.branch} on {args.repo}",
        {"repo": args.repo, "branch": args.branch},
    )
    return ToolResult(
        content=f"Branch {args.branch} created.", data={"repo": args.repo, "branch": args.branch}
    )


async def _commit(
    ctx: ToolContext, session: AsyncSession, repo: str, branch: str, message: str, files: dict[str, str]
) -> ToolResult:
    client, config = await _connection(ctx, session, repo, write=True)
    _guard_branch(branch, config)
    commit = await _guarded(client.commit_files(repo, branch, message, files))
    data = {"repo": repo, "branch": branch, "sha": commit["sha"], "files": sorted(files)}
    await _record(
        ctx, session, "commit", f"Committed {len(files)} file(s) to {repo}@{branch}: {message}", data
    )
    return ToolResult(content=f"Committed {commit['sha'][:10]} to {branch}.", data=data)


async def github_write_file(ctx: ToolContext, session: AsyncSession, args: WriteFileArgs) -> ToolResult:
    return await _commit(ctx, session, args.repo, args.branch, args.message, {args.path: args.content})


async def github_commit_changes(
    ctx: ToolContext, session: AsyncSession, args: CommitChangesArgs
) -> ToolResult:
    return await _commit(ctx, session, args.repo, args.branch, args.message, args.files)


async def github_create_pull_request(
    ctx: ToolContext, session: AsyncSession, args: CreatePullRequestArgs
) -> ToolResult:
    client, config = await _connection(ctx, session, args.repo, write=True)
    _guard_branch(args.head, config)
    base = args.base or config.get("default_branch", "main")
    pr = await _guarded(client.create_pull_request(args.repo, args.head, base, args.title, args.body))
    data = {
        "repo": args.repo,
        "branch": args.head,
        "pr_number": pr["number"],
        "pr_url": pr["html_url"],
        "pr_state": "open",
    }
    await _record(ctx, session, "pr_opened", f"Opened PR #{pr['number']} on {args.repo}: {args.title}", data)
    return ToolResult(content=f"Opened {pr['html_url']}", data=data)


async def github_merge_pull_request(
    ctx: ToolContext, session: AsyncSession, args: PullRequestArgs
) -> ToolResult:
    client, _ = await _connection(ctx, session, args.repo, write=True)
    await _guarded(client.merge_pull_request(args.repo, args.number))
    data = {"repo": args.repo, "pr_number": args.number, "pr_state": "merged"}
    await _record(ctx, session, "pr_merged", f"Merged PR #{args.number} on {args.repo}", data)
    return ToolResult(content=f"Merged PR #{args.number}.", data=data)


async def github_delete_branch(ctx: ToolContext, session: AsyncSession, args: BranchArgs) -> ToolResult:
    client, config = await _connection(ctx, session, args.repo, write=True)
    _guard_branch(args.branch, config)
    await _guarded(client.delete_branch(args.repo, args.branch))
    await _record(
        ctx,
        session,
        "branch_deleted",
        f"Deleted branch {args.branch} on {args.repo}",
        {"repo": args.repo, "branch": args.branch},
    )
    return ToolResult(content=f"Deleted {args.branch}.")


async def github_write_to_protected_branch(
    ctx: ToolContext, session: AsyncSession, args: WriteFileArgs
) -> ToolResult:
    # Registered only so the request is audited and visible; it can never succeed, even if approved
    raise ToolExecutionError(
        "Direct writes to protected branches are permanently blocked; open a pull request instead"
    )


def _tool(
    key: str, description: str, risk: RiskLevel, args: type[BaseModel], handler: Any, **extra: Any
) -> ToolDefinition:
    return ToolDefinition(key, description, risk, args, handler, **extra)


GITHUB_TOOLS: list[ToolDefinition] = [
    _tool(
        "github_get_repo_info",
        "Get repository metadata (default branch, language).",
        RiskLevel.AUTONOMOUS,
        RepoArgs,
        github_get_repo_info,
    ),
    _tool(
        "github_list_files",
        "List files in a repository directory.",
        RiskLevel.AUTONOMOUS,
        ListFilesArgs,
        github_list_files,
    ),
    _tool(
        "github_read_file",
        "Read a file from a repository (untrusted content).",
        RiskLevel.AUTONOMOUS,
        ReadFileArgs,
        github_read_file,
    ),
    _tool(
        "github_search_code",
        "Search code in a repository.",
        RiskLevel.AUTONOMOUS,
        SearchCodeArgs,
        github_search_code,
    ),
    _tool(
        "github_get_branch",
        "Get a branch and its head commit.",
        RiskLevel.AUTONOMOUS,
        BranchArgs,
        github_get_branch,
    ),
    _tool(
        "github_get_pull_request",
        "Get a pull request's status.",
        RiskLevel.AUTONOMOUS,
        PullRequestArgs,
        github_get_pull_request,
    ),
    _tool(
        "github_run_repository_checks",
        "Read CI check results (lint/build/tests) for a branch.",
        RiskLevel.AUTONOMOUS,
        BranchArgs,
        github_get_checks,
    ),
    _tool(
        "github_create_branch",
        "Create a new work branch (never main/master).",
        RiskLevel.CONTROLLED,
        CreateBranchArgs,
        github_create_branch,
        external=True,
        default_requires_approval=False,
    ),
    _tool(
        "github_write_file",
        "Write one file on a work branch as a commit.",
        RiskLevel.CONTROLLED,
        WriteFileArgs,
        github_write_file,
        external=True,
        default_requires_approval=False,
    ),
    _tool(
        "github_commit_changes",
        "Commit several files to a work branch in one commit.",
        RiskLevel.CONTROLLED,
        CommitChangesArgs,
        github_commit_changes,
        external=True,
        default_requires_approval=False,
    ),
    _tool(
        "github_create_pull_request",
        "Open a pull request. Requires CEO approval.",
        RiskLevel.HUMAN_APPROVAL,
        CreatePullRequestArgs,
        github_create_pull_request,
        external=True,
    ),
    _tool(
        "github_merge_pull_request",
        "Merge a pull request. Requires CEO approval.",
        RiskLevel.HUMAN_APPROVAL,
        PullRequestArgs,
        github_merge_pull_request,
        external=True,
    ),
    _tool(
        "github_delete_branch",
        "Delete a work branch. Requires CEO approval.",
        RiskLevel.HUMAN_APPROVAL,
        BranchArgs,
        github_delete_branch,
        external=True,
    ),
    _tool(
        "github_write_to_protected_branch",
        "Write directly to main/master. Always blocked.",
        RiskLevel.HUMAN_APPROVAL,
        WriteFileArgs,
        github_write_to_protected_branch,
        external=True,
    ),
]
