import json

import pytest

from deerflow_code_factory.review_repair import ReviewRepair
from deerflow_code_factory.store import FactoryStore


@pytest.mark.asyncio
@pytest.mark.parametrize("checks_pass", [True, False])
async def test_review_feedback_repairs_only_after_tests_and_review(
    tmp_path, monkeypatch, checks_pass
):
    store = FactoryStore(tmp_path / "factory.sqlite")
    factory = store.create_factory(
        owner_user_id="alice", repository_id=42, owner="acme", repo="widget"
    )
    job = store.create_or_get_job(factory["id"], issue_id=70, issue_number=7)
    store.transition(
        job["id"], expected_version=0, phase="awaiting_review", evidence={}
    )
    job = store.get_job_internal(job["id"])
    actions = []

    class Workspace:
        def __init__(self, *args):
            self.path = tmp_path

        def prepare_review(self, *args):
            actions.append("clone")

        def context(self):
            return "counter.py"

        def apply_files(self, files):
            actions.append("apply")

        def diff(self):
            return "+fix"

        def commit_and_push_review(self, issue_number):
            actions.append("push")
            return "b" * 40

    class Checker:
        def require_ready(self):
            actions.append("preflight")

        def run(self, path):
            actions.append("test")
            return type(
                "Result",
                (),
                {
                    "passed": checks_pass,
                    "exit_code": 0 if checks_pass else 1,
                    "output": "OK" if checks_pass else "failed",
                },
            )()

    class Invoker:
        async def invoke(self, request):
            if request.model_role == "repair":
                return type(
                    "Response",
                    (),
                    {
                        "content": json.dumps(
                            {
                                "files": [
                                    {
                                        "path": "counter.py",
                                        "content": "def mul(a,b): return a*b\n",
                                    }
                                ]
                            }
                        )
                    },
                )()
            actions.append("review")
            return type(
                "Response",
                (),
                {"content": json.dumps({"approved": True, "findings": []})},
            )()

    class Gh:
        async def api(self, path, **kwargs):
            if path.endswith("pulls/9"):
                return {"state": "open", "merged": False, "head": {"sha": "a" * 40}}
            raise AssertionError(path)

    class Delivery:
        def __init__(self, gh):
            pass

        async def post_review_summary(self, *args):
            actions.append("summary")

        async def reply_to_review_thread(self, *args):
            actions.append("reply")

    monkeypatch.setattr("deerflow_code_factory.review_repair.JobWorkspace", Workspace)
    monkeypatch.setattr("deerflow_code_factory.review_repair.GitHubDelivery", Delivery)
    worker = ReviewRepair(store, Gh(), tmp_path, Checker())
    worker.set_invoker(Invoker())
    delivery = {
        "pr_number": 9,
        "pr_url": "https://github.com/acme/widget/pull/9",
        "head_branch": "code-factory/issue-7-run-0",
        "head_sha": "a" * 40,
    }
    feedback = [
        {
            "id": "comment-1",
            "body": "Handle zero",
            "path": "counter.py",
            "thread_id": "thread-1",
        }
    ]
    await worker._run(job, factory, delivery, feedback, "Add mul")
    phase = store.get_job_internal(job["id"])["phase"]
    if checks_pass:
        assert phase == "awaiting_checks"
        assert actions == [
            "preflight",
            "clone",
            "apply",
            "test",
            "review",
            "push",
            "summary",
            "reply",
        ]
        assert store.list_events(job["id"])[-1]["evidence"][
            "addressed_feedback_ids"
        ] == ["comment-1"]
    else:
        assert phase == "review_blocked"
        assert "push" not in actions
        assert actions.count("test") == 3
