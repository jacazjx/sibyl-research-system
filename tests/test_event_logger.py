"""Tests for sibyl.event_logger module."""
import json
import time

import pytest

from sibyl.event_logger import EventLogger


@pytest.fixture
def el(tmp_path):
    return EventLogger(tmp_path)


class TestEventLoggerBasic:
    def test_log_creates_file_and_appends(self, el, tmp_path):
        ev = el.log("test_event", key="value")
        assert ev["event"] == "test_event"
        assert ev["key"] == "value"
        assert "ts" in ev

        events_file = tmp_path / "logs" / "events.jsonl"
        assert events_file.exists()
        lines = events_file.read_text().strip().split("\n")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["event"] == "test_event"

    def test_log_appends_multiple(self, el, tmp_path):
        el.log("ev1")
        el.log("ev2")
        el.log("ev3")
        events_file = tmp_path / "logs" / "events.jsonl"
        lines = events_file.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_log_handles_non_serializable_default_str(self, el):
        from pathlib import Path
        ev = el.log("test", path=Path("/foo/bar"))
        assert ev["path"] == Path("/foo/bar")
        # File should be written without error
        events = el.read_all()
        assert len(events) == 1
        assert events[0]["path"] == "/foo/bar"


class TestStageEvents:
    def test_stage_start(self, el):
        ev = el.stage_start("literature_search", iteration=1,
                            action_type="skill", description="Search lit")
        assert ev["event"] == "stage_start"
        assert ev["stage"] == "literature_search"
        assert ev["iteration"] == 1
        assert ev["action_type"] == "skill"

    def test_stage_end(self, el):
        ev = el.stage_end("literature_search", iteration=1,
                          duration_sec=120.5, score=7.5,
                          next_stage="idea_debate")
        assert ev["event"] == "stage_end"
        assert ev["duration_sec"] == 120.5
        assert ev["score"] == 7.5
        assert ev["next_stage"] == "idea_debate"


class TestAgentEvents:
    def test_agent_start(self, el):
        ev = el.agent_start("idea_debate", "sibyl-innovator",
                            model_tier="sibyl-standard", iteration=1,
                            prompt_summary="Generate innovative ideas")
        assert ev["event"] == "agent_start"
        assert ev["agent"] == "sibyl-innovator"
        assert ev["model_tier"] == "sibyl-standard"

    def test_agent_end(self, el):
        ev = el.agent_end("idea_debate", "sibyl-innovator",
                          status="ok", duration_sec=45.2,
                          output_files=["idea/perspectives/innovator.md"],
                          output_summary="Proposed TTT-based approach",
                          iteration=1)
        assert ev["event"] == "agent_end"
        assert ev["status"] == "ok"
        assert ev["duration_sec"] == 45.2
        assert ev["output_files"] == ["idea/perspectives/innovator.md"]

    def test_agent_end_defaults(self, el):
        ev = el.agent_end("review", "sibyl-critic")
        assert ev["output_files"] == []
        assert ev["status"] == "ok"


class TestSystemEvents:
    def test_project_init(self, el):
        ev = el.project_init("TTT-DLM", project_name="ttt-dlm")
        assert ev["event"] == "project_init"
        assert ev["topic"] == "TTT-DLM"

    def test_pause(self, el):
        ev = el.pause("rate_limit", stage="experiment_cycle", iteration=2)
        assert ev["event"] == "pause"
        assert ev["reason"] == "rate_limit"

    def test_resume(self, el):
        ev = el.resume(stage="experiment_cycle", iteration=2)
        assert ev["event"] == "resume"

    def test_error(self, el):
        ev = el.error("SSH failed", stage="pilot_experiments",
                      category="build", iteration=1)
        assert ev["event"] == "error"
        assert ev["category"] == "build"

    def test_iteration_complete(self, el):
        ev = el.iteration_complete(iteration=3, score=7.8, issues_count=4)
        assert ev["event"] == "iteration_complete"
        assert ev["score"] == 7.8
        assert ev["issues_count"] == 4


class TestExperimentEvents:
    def test_task_dispatch(self, el):
        ev = el.task_dispatch(["task_a", "task_b"], [0, 1], iteration=1)
        assert ev["event"] == "task_dispatch"
        assert ev["task_ids"] == ["task_a", "task_b"]
        assert ev["gpu_ids"] == [0, 1]

    def test_experiment_recover(self, el):
        ev = el.experiment_recover(["task_c"], iteration=2)
        assert ev["event"] == "experiment_recover"
        assert ev["recovered_tasks"] == ["task_c"]

    def test_checkpoint_step(self, el):
        ev = el.checkpoint_step("writing_sections", "intro", iteration=1)
        assert ev["event"] == "checkpoint_step"
        assert ev["step_id"] == "intro"


class TestQueryHelpers:
    def test_read_all_empty(self, el):
        assert el.read_all() == []

    def test_read_all(self, el):
        el.log("a")
        el.log("b")
        events = el.read_all()
        assert len(events) == 2
        assert events[0]["event"] == "a"
        assert events[1]["event"] == "b"

    def test_tail_returns_last_n(self, el):
        for i in range(20):
            el.log("ev", idx=i)
        tail = el.tail(5)
        assert len(tail) == 5
        assert tail[0]["idx"] == 15
        assert tail[4]["idx"] == 19

    def test_tail_empty(self, el):
        assert el.tail() == []

    def test_tail_fewer_than_n(self, el):
        el.log("only")
        tail = el.tail(10)
        assert len(tail) == 1

    def test_query_by_event_type(self, el):
        el.stage_start("a", 1)
        el.stage_end("a", 1)
        el.agent_start("a", "innovator")
        results = el.query(event_type="agent_start")
        assert len(results) == 1
        assert results[0]["agent"] == "innovator"

    def test_query_by_stage(self, el):
        el.stage_start("lit", 1)
        el.stage_start("idea", 1)
        results = el.query(stage="idea")
        assert len(results) == 1

    def test_query_by_agent(self, el):
        el.agent_end("idea", "innovator")
        el.agent_end("idea", "pragmatist")
        results = el.query(agent="pragmatist")
        assert len(results) == 1

    def test_query_since(self, el):
        el.log("old")
        cutoff = time.time()
        time.sleep(0.01)
        el.log("new")
        results = el.query(since=cutoff)
        assert len(results) == 1
        assert results[0]["event"] == "new"

    def test_query_limit(self, el):
        for i in range(10):
            el.log("ev")
        results = el.query(limit=3)
        assert len(results) == 3


class TestStageDurations:
    def test_computes_durations_from_pairs(self, el):
        el.stage_start("lit", 1)
        time.sleep(0.01)
        el.stage_end("lit", 1, next_stage="idea")
        durations = el.get_stage_durations()
        assert len(durations) == 1
        assert durations[0]["stage"] == "lit"
        assert durations[0]["duration_sec"] is not None
        assert durations[0]["duration_sec"] > 0

    def test_uses_explicit_duration_if_provided(self, el):
        el.stage_start("lit", 1)
        el.stage_end("lit", 1, duration_sec=99.9)
        durations = el.get_stage_durations()
        assert durations[0]["duration_sec"] == 99.9

    def test_filter_by_iteration(self, el):
        el.stage_start("lit", 1)
        el.stage_end("lit", 1)
        el.stage_start("lit", 2)
        el.stage_end("lit", 2)
        durations = el.get_stage_durations(iteration=2)
        assert len(durations) == 1
        assert durations[0]["iteration"] == 2


class TestAgentSummary:
    def test_summarizes_agent_invocations(self, el):
        el.agent_end("idea", "innovator", duration_sec=30,
                     output_files=["a.md"], output_summary="did stuff")
        el.agent_end("idea", "pragmatist", duration_sec=25)
        summary = el.get_agent_summary()
        assert len(summary) == 2
        assert summary[0]["agent"] == "innovator"
        assert summary[0]["output_summary"] == "did stuff"

    def test_filter_by_iteration(self, el):
        el.agent_end("idea", "a", iteration=1)
        el.agent_end("idea", "b", iteration=2)
        summary = el.get_agent_summary(iteration=1)
        assert len(summary) == 1
        assert summary[0]["agent"] == "a"


class TestWorkspaceStageStartedAt:
    """Test stage_started_at field in WorkspaceStatus."""

    def test_update_stage_sets_stage_started_at(self, tmp_path):
        from sibyl.workspace import Workspace
        ws = Workspace(tmp_path, "test-project")
        ws.update_stage("literature_search")
        status = ws.get_status()
        assert status.stage_started_at is not None
        assert status.stage_started_at > 0

    def test_update_stage_and_iteration_sets_stage_started_at(self, tmp_path):
        from sibyl.workspace import Workspace
        ws = Workspace(tmp_path, "test-project")
        ws.update_stage_and_iteration("quality_gate", 2)
        status = ws.get_status()
        assert status.stage == "quality_gate"
        assert status.iteration == 2
        assert status.stage_started_at is not None

    def test_stage_started_at_in_metadata(self, tmp_path):
        from sibyl.workspace import Workspace
        ws = Workspace(tmp_path, "test-project")
        ws.update_stage("idea_debate")
        meta = ws.get_project_metadata()
        assert "stage_started_at" in meta
        assert meta["stage_started_at"] is not None

    def test_backward_compat_old_status_without_field(self, tmp_path):
        """Old status.json without stage_started_at should still load."""
        from sibyl.workspace import Workspace, workspace_status_from_data
        ws = Workspace(tmp_path, "test-project")
        # Write status without stage_started_at
        status_path = ws.root / "status.json"
        data = json.loads(status_path.read_text())
        data.pop("stage_started_at", None)
        status_path.write_text(json.dumps(data))
        # Should load without error
        status = ws.get_status()
        assert status.stage_started_at is None
