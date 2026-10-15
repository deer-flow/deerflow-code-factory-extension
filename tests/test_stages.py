import pytest

from deerflow_code_factory.stages import AgentStages, parse_json_answer


def test_parse_json_answer_rejects_non_object():
    with pytest.raises(ValueError):
        parse_json_answer("[1, 2]")
    assert parse_json_answer('```json\n{"ready": true}\n```') == {"ready": True}


class FakeRuns:
    def __init__(self, answers):
        self.answers = answers
        self.prompts = []
        self.threads = 0

    async def create_thread(self, **kwargs):
        self.threads += 1
        return f"thread-{self.threads}"

    async def start(self, *, thread_id, input, idempotency_key):
        self.prompts.append((thread_id, input["messages"][0]["content"]))
        return type("Run", (), {"run_id": f"run-{self.threads}"})()

    async def wait(self, **kwargs):
        return type("Run", (), {"status": "success"})()

    async def get_state(self, **kwargs):
        return {
            "next": [],
            "values": {"messages": [{"type": "ai", "content": self.answers.pop(0)}]},
        }


@pytest.mark.asyncio
async def test_stages_use_independent_reviewer_thread():
    runs = FakeRuns(
        [
            '{"ready": true, "spec": "CSV export with a test", "relevant_paths": []}',
            '{"files": [{"path": "src/export.py", "content": "def export(): return 1\\n"}], "summary": "Added export"}',
            '{"approved": true, "findings": []}',
        ]
    )
    stages = AgentStages(runs)
    spec = await stages.plan(
        "Export records", "Acceptance Criteria: CSV output", "repo tree"
    )
    code = await stages.code(spec["spec"], "repo context")
    review = await stages.review(spec["spec"], code["files"])
    assert review["approved"] is True
    assert len({thread for thread, _ in runs.prompts}) == 3


@pytest.mark.asyncio
async def test_stages_refuse_implicit_interrupt_approval():
    runs = FakeRuns(['{"ready": true}'])

    async def interrupted(**kwargs):
        return {"next": ["approval"], "interrupts": ["approve"]}

    runs.get_state = interrupted
    with pytest.raises(RuntimeError, match="interrupt"):
        await AgentStages(runs).plan("x", "Acceptance Criteria: x", "tree")
