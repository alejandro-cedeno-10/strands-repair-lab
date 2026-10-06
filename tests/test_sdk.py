"""Real SDK with a scripted model: validates the wiring, not an autonomous repair."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from strands.models import Model
from repairlab.agent import Budget, build
from repairlab.workspace import Workspace, EDITABLE
from test_controls import TrustedControlsRunner, BUG_FILE, REF_FILE


class ScriptedModel(Model):
    def update_config(self, **kwargs):
        pass

    def get_config(self):
        return {"model_id": "offline-scripted", "context_window_limit": 100000}

    async def structured_output(self, *args, **kwargs):
        raise NotImplementedError
        yield

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        steps = [
            ("list_files", {}),
            ("read_file", {"path": "README.md"}),
            ("read_file", {"path": EDITABLE}),
            ("run_tests", {}),
            ("replace_text", {"path": EDITABLE, "expected_sha256": hashlib.sha256(BUG_FILE.read_bytes()).hexdigest(),
                              "old": BUG_FILE.read_text(), "new": REF_FILE.read_text()}),
            ("run_tests", {}),
            ("show_diff", {}),
            ("submit_patch", {"explanation": "Scripted control: applies the reference solution written by the lab author"}),
        ]
        index = sum("toolUse" in c for m in messages for c in m.get("content", []))
        yield {"messageStart": {"role": "assistant"}}
        if index < len(steps):
            name, args = steps[index]
            yield {"contentBlockStart": {"contentBlockIndex": 0, "start": {"toolUse": {"toolUseId": f"step-{index}", "name": name}}}}
            yield {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolUse": {"input": json.dumps(args)}}}}
        else:
            yield {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}}
            yield {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "End of SIMULATED control"}}}
        yield {"contentBlockStop": {"contentBlockIndex": 0}}
        yield {"messageStop": {"stopReason": "tool_use" if index < len(steps) else "end_turn"}}
        yield {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15}, "metrics": {"latencyMs": 0}}}


class SDKIntegration(unittest.TestCase):
    def test_tool_loop_red_edit_green_submit(self):
        with tempfile.TemporaryDirectory() as directory:
            ws = Workspace(Path(directory) / "run", TrustedControlsRunner())
            budget = Budget()
            agent, reviews = build(ws, ScriptedModel(), budget, with_reviewer=False)
            result = agent("Simulated control")
            self.assertEqual(str(result.stop_reason), "end_turn")
            self.assertIsNotNone(ws.submitted)
            self.assertEqual(ws.baseline["status"], "FAIL")
            self.assertEqual(ws.last_tests["status"], "PASS")
            self.assertEqual(budget.calls, 9)
            self.assertEqual(budget.tools, 8)
            self.assertEqual(reviews, [])

    def test_budget_stops_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            ws = Workspace(Path(directory) / "run", TrustedControlsRunner())
            budget = Budget(max_calls=1)
            agent, _ = build(ws, ScriptedModel(), budget, with_reviewer=False)
            agent("Simulated control")
            self.assertEqual(budget.calls, 1)
            self.assertTrue(budget.blocked)
            self.assertIsNone(ws.submitted)

    def test_tools_exclude_shell_and_grader(self):
        with tempfile.TemporaryDirectory() as directory:
            ws = Workspace(Path(directory) / "run", TrustedControlsRunner())
            agent, _ = build(ws, ScriptedModel(), Budget(), with_reviewer=True)
            self.assertEqual(set(agent.tool_registry.registry), {"list_files", "read_file", "replace_text", "run_tests", "show_diff", "submit_patch", "review_patch"})

    def test_harness_defaults_add_only_context_retrieval(self):
        with tempfile.TemporaryDirectory() as directory:
            ws = Workspace(Path(directory) / "run", TrustedControlsRunner())
            budget = Budget()
            agent, _ = build(ws, ScriptedModel(), budget, with_reviewer=True, harness_defaults=True)
            self.assertEqual(set(agent.tool_registry.registry) - {"list_files", "read_file", "replace_text", "run_tests",
                             "show_diff", "submit_patch", "review_patch"}, {"retrieve_context", "retrieve_offloaded_content"})
            agent("Simulated control")
            self.assertIsNotNone(ws.submitted)
            self.assertTrue((ws.output / "harness-session").is_dir())


if __name__ == "__main__":
    unittest.main()
