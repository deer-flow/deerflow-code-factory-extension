import assert from "node:assert/strict";
import test from "node:test";
import { parseRepositoryUrl } from "../src/deerflow_code_factory/static/index.mjs";

test("accepts a GitHub repository URL", () => {
  assert.deepEqual(parseRepositoryUrl("github", "https://github.com/example/my-repo"), { owner: "example", repo: "my-repo" });
  assert.deepEqual(parseRepositoryUrl("github", " https://github.com/example/my-repo.git/ "), { owner: "example", repo: "my-repo" });
});

test("rejects other platforms and non-repository URLs", () => {
  for (const [provider, url] of [
    ["gitlab", "https://gitlab.com/example/my-repo"],
    ["github", "https://github.com/example/my-repo/issues"],
    ["github", "http://github.com/example/my-repo"],
    ["github", "https://github.com/example/my-repo?tab=readme"],
    ["github", "https://github.com/example%2Fother/my-repo"],
  ]) assert.throws(() => parseRepositoryUrl(provider, url));
});
