"""Tests for sibyl.orchestra_skills — SkillRegistry scan, parse, filter, render."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from sibyl.orchestra_skills import SkillEntry, SkillRegistry, _topic_score


@pytest.fixture
def tmp_skills(tmp_path: Path) -> Path:
    """Create a minimal orchestra skills tree for testing."""
    # Category 1: fine-tuning
    ft_dir = tmp_path / "03-fine-tuning" / "peft"
    ft_dir.mkdir(parents=True)
    (ft_dir / "SKILL.md").write_text(dedent("""\
        ---
        name: peft-fine-tuning
        description: Parameter-efficient fine-tuning for LLMs using LoRA, QLoRA, and 25+ methods. Use when fine-tuning large models.
        tags: [Fine-Tuning, PEFT, LoRA, QLoRA]
        ---
        # PEFT
        Fine-tune LLMs efficiently.
    """))

    # Category 2: inference
    inf_dir = tmp_path / "12-inference" / "vllm"
    inf_dir.mkdir(parents=True)
    (inf_dir / "SKILL.md").write_text(dedent("""\
        ---
        name: vllm-serving
        description: High throughput LLM serving with PagedAttention and continuous batching. Best for production deployment.
        tags: [Inference, Serving, vLLM, PagedAttention]
        ---
        # vLLM
        Serve LLMs fast.
    """))

    # Category 3: evaluation
    eval_dir = tmp_path / "11-evaluation" / "lm-evaluation-harness"
    eval_dir.mkdir(parents=True)
    (eval_dir / "SKILL.md").write_text(dedent("""\
        ---
        name: lm-evaluation-harness
        description: Evaluates LLMs across 60+ academic benchmarks including MMLU, HumanEval, GSM8K.
        tags: [Evaluation, Benchmarks, MMLU, GSM8K]
        ---
        # LM Eval
        Evaluate models.
    """))

    # Category-level skill (no subdirectory)
    paper_dir = tmp_path / "20-ml-paper-writing"
    paper_dir.mkdir(parents=True)
    (paper_dir / "SKILL.md").write_text(dedent("""\
        ---
        name: ml-paper-writing
        description: Write publication-ready ML papers for NeurIPS, ICML, ICLR.
        tags: [Paper Writing, LaTeX, NeurIPS]
        ---
        # ML Paper Writing
    """))

    # Malformed skill (no frontmatter)
    bad_dir = tmp_path / "99-bad" / "broken"
    bad_dir.mkdir(parents=True)
    (bad_dir / "SKILL.md").write_text("No frontmatter here.\n")

    return tmp_path


class TestSkillRegistryScanning:
    def test_scan_finds_all_valid_skills(self, tmp_skills: Path) -> None:
        reg = SkillRegistry(skills_dir=tmp_skills)
        entries = reg.entries
        names = {e.name for e in entries}
        assert "peft-fine-tuning" in names
        assert "vllm-serving" in names
        assert "lm-evaluation-harness" in names
        assert "ml-paper-writing" in names
        # Malformed skill should be skipped
        assert len(entries) == 4

    def test_scan_empty_dir(self, tmp_path: Path) -> None:
        reg = SkillRegistry(skills_dir=tmp_path)
        assert reg.entries == []

    def test_scan_nonexistent_dir(self, tmp_path: Path) -> None:
        reg = SkillRegistry(skills_dir=tmp_path / "nonexistent")
        assert reg.entries == []


class TestSkillEntryParsing:
    def test_entry_fields(self, tmp_skills: Path) -> None:
        reg = SkillRegistry(skills_dir=tmp_skills)
        peft = next(e for e in reg.entries if e.invoke_name == "peft")
        assert peft.name == "peft-fine-tuning"
        assert "Parameter-efficient" in peft.description
        assert "LoRA" in peft.tags
        assert "03-fine-tuning" in peft.category

    def test_description_truncated_to_first_sentence(self, tmp_skills: Path) -> None:
        reg = SkillRegistry(skills_dir=tmp_skills)
        vllm = next(e for e in reg.entries if e.invoke_name == "vllm")
        # Should be truncated at first period
        assert "Best for production" not in vllm.description
        assert "High throughput" in vllm.description


class TestFiltering:
    def test_no_topic_returns_all_up_to_max(self, tmp_skills: Path) -> None:
        reg = SkillRegistry(skills_dir=tmp_skills)
        result = reg.filter_skills(max_results=10)
        assert len(result) == 4

    def test_max_results_limits_output(self, tmp_skills: Path) -> None:
        reg = SkillRegistry(skills_dir=tmp_skills)
        result = reg.filter_skills(max_results=2)
        assert len(result) == 2

    def test_topic_scoring_ranks_relevant_first(self, tmp_skills: Path) -> None:
        reg = SkillRegistry(skills_dir=tmp_skills)
        result = reg.filter_skills(topic="LoRA fine-tuning for large language models")
        assert result[0].invoke_name == "peft"

    def test_topic_scoring_inference(self, tmp_skills: Path) -> None:
        reg = SkillRegistry(skills_dir=tmp_skills)
        result = reg.filter_skills(topic="vLLM inference serving deployment")
        assert result[0].invoke_name == "vllm"


class TestTopicScoring:
    def test_direct_name_match_scores_high(self) -> None:
        entry = SkillEntry(
            name="vllm-serving",
            invoke_name="vllm",
            description="LLM serving",
            tags=("Inference",),
            category="12-inference",
        )
        score = _topic_score(entry, "vllm deployment", {"vllm", "deployment"})
        assert score >= 10.0

    def test_no_match_scores_zero(self) -> None:
        entry = SkillEntry(
            name="peft-fine-tuning",
            invoke_name="peft",
            description="Fine-tuning with LoRA",
            tags=("LoRA",),
            category="03-fine-tuning",
        )
        score = _topic_score(entry, "quantum computing", {"quantum", "computing"})
        assert score == 0.0


class TestRendering:
    def test_render_index_produces_table(self, tmp_skills: Path) -> None:
        reg = SkillRegistry(skills_dir=tmp_skills)
        output = reg.render_index(max_results=10)
        assert "| Skill |" in output
        assert "peft" in output
        assert "vllm" in output
        assert "Skill tool" in output

    def test_render_index_empty_registry(self, tmp_path: Path) -> None:
        reg = SkillRegistry(skills_dir=tmp_path)
        assert reg.render_index() == ""

    def test_render_index_respects_max(self, tmp_skills: Path) -> None:
        reg = SkillRegistry(skills_dir=tmp_skills)
        output = reg.render_index(max_results=2)
        # Should have header + 2 data rows
        table_rows = [l for l in output.splitlines() if l.startswith("| ") and not l.startswith("| Skill") and not l.startswith("|---")]
        assert len(table_rows) == 2
