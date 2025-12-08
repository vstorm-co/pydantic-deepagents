"""Mock GitHub tools for demonstration.

These tools simulate GitHub API operations with mock data.
They don't connect to real GitHub API - just return fake data for demo purposes.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from pydantic_deep.deps import DeepAgentDeps

# Mock data
MOCK_REPOS = [
    {"name": "pydantic-deep", "stars": 1234, "forks": 89, "language": "Python"},
    {"name": "fastapi-starter", "stars": 567, "forks": 45, "language": "Python"},
    {"name": "react-dashboard", "stars": 890, "forks": 123, "language": "TypeScript"},
    {"name": "ml-pipeline", "stars": 345, "forks": 67, "language": "Python"},
    {"name": "data-viz-tool", "stars": 234, "forks": 34, "language": "JavaScript"},
]

MOCK_ISSUES = [
    {
        "number": 42,
        "title": "Add support for streaming responses",
        "state": "open",
        "labels": ["enhancement", "priority-high"],
    },
    {
        "number": 41,
        "title": "Fix memory leak in long-running sessions",
        "state": "open",
        "labels": ["bug", "priority-critical"],
    },
    {
        "number": 40,
        "title": "Update documentation for v2.0",
        "state": "open",
        "labels": ["documentation"],
    },
    {
        "number": 39,
        "title": "Add type hints to legacy code",
        "state": "closed",
        "labels": ["tech-debt"],
    },
    {
        "number": 38,
        "title": "Implement rate limiting",
        "state": "closed",
        "labels": ["enhancement"],
    },
]

MOCK_PRS = [
    {
        "number": 100,
        "title": "feat: add RuntimeConfig support",
        "state": "open",
        "author": "alice",
        "additions": 450,
        "deletions": 120,
    },
    {
        "number": 99,
        "title": "fix: resolve race condition in session manager",
        "state": "merged",
        "author": "bob",
        "additions": 23,
        "deletions": 15,
    },
    {
        "number": 98,
        "title": "docs: update getting started guide",
        "state": "open",
        "author": "charlie",
        "additions": 89,
        "deletions": 12,
    },
]

MOCK_USERS = [
    {"login": "alice", "name": "Alice Smith", "followers": 1234, "repos": 45},
    {"login": "bob", "name": "Bob Johnson", "followers": 567, "repos": 23},
    {"login": "charlie", "name": "Charlie Brown", "followers": 890, "repos": 67},
]


def create_github_toolset(id: str | None = None) -> FunctionToolset[DeepAgentDeps]:  # noqa: C901
    """Create a toolset with mock GitHub operations.

    Args:
        id: Optional unique ID for the toolset.

    Returns:
        FunctionToolset with 5 mock GitHub tools.
    """
    toolset: FunctionToolset[DeepAgentDeps] = FunctionToolset(id=id)

    @toolset.tool
    async def github_list_repos(
        ctx: RunContext[DeepAgentDeps],
        username: str | None = None,
        sort_by: str = "stars",
    ) -> str:
        """List GitHub repositories.

        Args:
            username: GitHub username (optional, defaults to current user).
            sort_by: Sort by 'stars', 'forks', or 'name'.
        """
        repos = MOCK_REPOS.copy()

        if sort_by == "stars":
            repos.sort(key=lambda x: x["stars"], reverse=True)
        elif sort_by == "forks":
            repos.sort(key=lambda x: x["forks"], reverse=True)
        else:
            repos.sort(key=lambda x: x["name"])

        lines = [f"Repositories for {username or 'current user'}:"]
        for repo in repos:
            lines.append(
                f"  - {repo['name']} ({repo['language']}): ⭐ {repo['stars']} | 🍴 {repo['forks']}"
            )

        return "\n".join(lines)

    @toolset.tool
    async def github_list_issues(
        ctx: RunContext[DeepAgentDeps],
        repo: str,
        state: str = "open",
    ) -> str:
        """List issues in a repository.

        Args:
            repo: Repository name (e.g., 'pydantic-deep').
            state: Filter by state: 'open', 'closed', or 'all'.
        """
        issues = MOCK_ISSUES.copy()

        if state != "all":
            issues = [i for i in issues if i["state"] == state]

        if not issues:
            return f"No {state} issues found in {repo}"

        lines = [f"Issues in {repo} ({state}):"]
        for issue in issues:
            labels = ", ".join(issue["labels"]) if issue["labels"] else "no labels"
            lines.append(f"  #{issue['number']}: {issue['title']} [{labels}]")

        return "\n".join(lines)

    @toolset.tool
    async def github_list_pull_requests(
        ctx: RunContext[DeepAgentDeps],
        repo: str,
        state: str = "open",
    ) -> str:
        """List pull requests in a repository.

        Args:
            repo: Repository name (e.g., 'pydantic-deep').
            state: Filter by state: 'open', 'merged', or 'all'.
        """
        prs = MOCK_PRS.copy()

        if state != "all":
            prs = [p for p in prs if p["state"] == state]

        if not prs:
            return f"No {state} pull requests found in {repo}"

        lines = [f"Pull requests in {repo} ({state}):"]
        for pr in prs:
            lines.append(
                f"  #{pr['number']}: {pr['title']} "
                f"by @{pr['author']} (+{pr['additions']}/-{pr['deletions']})"
            )

        return "\n".join(lines)

    @toolset.tool
    async def github_get_user(
        ctx: RunContext[DeepAgentDeps],
        username: str,
    ) -> str:
        """Get information about a GitHub user.

        Args:
            username: GitHub username to look up.
        """
        # Find user or generate random mock data
        user = next((u for u in MOCK_USERS if u["login"] == username), None)

        if not user:
            user = {
                "login": username,
                "name": f"{username.title()} User",
                "followers": random.randint(10, 500),
                "repos": random.randint(5, 50),
            }

        return (
            f"GitHub User: @{user['login']}\n"
            f"  Name: {user['name']}\n"
            f"  Followers: {user['followers']}\n"
            f"  Public repos: {user['repos']}"
        )

    @toolset.tool
    async def github_get_repo_stats(
        ctx: RunContext[DeepAgentDeps],
        repo: str,
    ) -> str:
        """Get detailed statistics for a repository.

        Args:
            repo: Repository name (e.g., 'pydantic-deep').
        """
        # Find repo or generate mock data
        repo_data = next((r for r in MOCK_REPOS if r["name"] == repo), None)

        if not repo_data:
            repo_data = {
                "name": repo,
                "stars": random.randint(100, 2000),
                "forks": random.randint(10, 200),
                "language": random.choice(["Python", "JavaScript", "TypeScript"]),
            }

        # Generate additional mock stats
        commits_last_month = random.randint(20, 150)
        contributors = random.randint(5, 50)
        open_issues = random.randint(5, 30)
        open_prs = random.randint(2, 15)
        last_commit = datetime.now() - timedelta(hours=random.randint(1, 72))

        return (
            f"Repository: {repo_data['name']}\n"
            f"  Language: {repo_data['language']}\n"
            f"  Stars: {repo_data['stars']}\n"
            f"  Forks: {repo_data['forks']}\n"
            f"  Open issues: {open_issues}\n"
            f"  Open PRs: {open_prs}\n"
            f"  Contributors: {contributors}\n"
            f"  Commits (last month): {commits_last_month}\n"
            f"  Last commit: {last_commit.strftime('%Y-%m-%d %H:%M')}"
        )

    return toolset


# System prompt for GitHub tools
GITHUB_SYSTEM_PROMPT = """
## GitHub Tools

You have access to mock GitHub tools for demonstration:

- `github_list_repos`: List repositories for a user
- `github_list_issues`: List issues in a repository
- `github_list_pull_requests`: List PRs in a repository
- `github_get_user`: Get user profile information
- `github_get_repo_stats`: Get detailed repository statistics

Note: These tools return simulated data for demonstration purposes.
"""
