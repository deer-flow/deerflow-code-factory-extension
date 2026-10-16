"""Bounded repository context for implementation Agent prompts."""

import base64


async def load_repository_context(gh, factory, base_branch: str, relevant_paths=None):
    root = f"repos/{factory['owner']}/{factory['repo']}"
    ref = await gh.api(f"{root}/git/ref/heads/{base_branch}")
    commit = await gh.api(f"{root}/git/commits/{ref['object']['sha']}")
    tree = await gh.api(f"{root}/git/trees/{commit['tree']['sha']}?recursive=1")
    if tree.get("truncated"):
        raise ValueError("repository tree is too large for MVP context")
    paths = [row["path"] for row in tree.get("tree", []) if row.get("type") == "blob"]
    if len(paths) > 5000:
        raise ValueError("repository has too many files for MVP context")
    # Planning may name files it intends to create. They have no base content.
    if relevant_paths is None:
        selected = [
            path
            for path in paths
            if not path.startswith(".github/")
            and path.endswith((".py", ".md", ".toml", ".txt", ".json", ".yaml", ".yml"))
        ][:20]
    else:
        selected = [path for path in dict.fromkeys(relevant_paths) if path in paths][
            :20
        ]
    pieces = ["Repository files:\n" + "\n".join(paths)]
    total = 0
    for path in selected:
        item = await gh.api(f"{root}/contents/{path}?ref={base_branch}")
        if item.get("encoding") != "base64":
            raise ValueError("unsupported repository content encoding")
        content = base64.b64decode(item["content"], validate=False).decode("utf-8")
        total += len(content.encode("utf-8"))
        if total > 80_000:
            raise ValueError("repository context exceeds 80 KiB")
        pieces.append(f"\n--- {path} ---\n{content}")
    return "\n".join(pieces)
