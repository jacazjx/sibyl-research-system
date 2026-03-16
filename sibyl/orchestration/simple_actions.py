"""Simple stage action builders extracted from the legacy orchestrator."""

from __future__ import annotations

from typing import Any

from .agent_helpers import codex_reviewer_args
from .common_utils import pack_skill_args
from .prompt_loader import _load_workspace_action_plan


def build_literature_search_action(
    topic: str,
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Single fork skill performs literature search via arXiv + WebSearch."""
    return action_cls(
        action_type="skill",
        skills=[{"name": "sibyl-literature", "args": pack_skill_args(ws, topic)}],
        description="文献调研：arXiv 搜索 + Web 搜索，建立领域现状基础",
        stage="literature_search",
    )


def build_planning_action(
    orchestrator: Any,
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the planning-stage action with pilot experiment config context."""
    pilot_config = (
        f"samples={orchestrator.config.pilot_samples}, "
        f"seeds={orchestrator.config.pilot_seeds}, "
        f"timeout={orchestrator.config.pilot_timeout}s"
    )
    return action_cls(
        action_type="skill",
        skills=[{"name": "sibyl-planner", "args": pack_skill_args(ws, "plan", pilot_config)}],
        description="Design experiment plan with pilot/full configs",
        stage="planning",
    )


def build_idea_validation_decision_action(
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the pilot-validation decision action."""
    return action_cls(
        action_type="skill",
        skills=[{"name": "sibyl-idea-validation-decision", "args": ws}],
        description="Review pilot evidence and decide ADVANCE / REFINE / PIVOT",
        stage="idea_validation_decision",
    )


def build_experiment_decision_action(
    orchestrator: Any,
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the post-experiment supervisor decision action.

    When speculative_outline is enabled (default True), the outline writer runs
    in parallel with the supervisor decision.  If the supervisor decides PROCEED
    and an outline already exists, the pipeline can skip writing_outline entirely.
    If the supervisor decides PIVOT, the speculative outline is simply ignored.
    """
    speculative = getattr(orchestrator.config, "speculative_outline", True)
    if speculative:
        return action_cls(
            action_type="skills_parallel",
            skills=[
                {"name": "sibyl-supervisor-decision", "args": ws},
                {"name": "sibyl-outline-writer", "args": ws},
            ],
            description="Supervisor decision + speculative outline (parallel)",
            stage="experiment_decision",
        )
    return action_cls(
        action_type="skill",
        skills=[{"name": "sibyl-supervisor-decision", "args": ws}],
        description="Supervisor analyzes results and decides PIVOT or PROCEED",
        stage="experiment_decision",
    )


def build_writing_outline_action(
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the outline-writing action."""
    return action_cls(
        action_type="skill",
        skills=[{"name": "sibyl-outline-writer", "args": ws}],
        description="Generate paper outline",
        stage="writing_outline",
    )


def build_writing_integrate_action(
    orchestrator: Any,
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the combined critique + integrate team action.

    Merges the former ``writing_critique`` stage (6 section-critics in parallel)
    with the ``writing_integrate`` editor into a single team action.  The critics
    run as teammates and the editor executes as a post_step after all critics finish.
    """
    from .checkpointing import get_or_create_checkpoint
    from .common_utils import pack_skill_args, paper_writing_requirement
    from .constants import PAPER_SECTIONS
    from .prompt_loader import render_team_prompt

    steps = {sid: f"writing/critique/{sid}_critique.md" for sid, _ in PAPER_SECTIONS}
    cp_info = get_or_create_checkpoint(orchestrator, "writing_integrate", steps)

    if cp_info and cp_info["all_complete"]:
        # All critiques done — only the editor post_step remains.
        return action_cls(
            action_type="skill",
            skills=[{"name": "sibyl-editor", "args": ws}],
            description="所有批评已完成（checkpoint 校验通过），直接执行编辑整合",
            stage="writing_integrate",
            checkpoint_info=cp_info,
        )

    remaining = set(cp_info["remaining_steps"]) if cp_info else None
    sections_info = "\n".join(
        f"- Critic for {name}: read {ws}/writing/sections/{sid}.md, "
        f"write critique to {ws}/writing/critique/{sid}_critique.md"
        for sid, name in PAPER_SECTIONS
        if remaining is None or sid in remaining
    )
    team_instructions = (
        f"Spawn teammates for remaining critiques:\n{sections_info}\n\n"
        f"**Cross-section referencing**: Each critic MUST read related sections for consistency checking. "
        f"All sections are in {ws}/writing/sections/. "
        f"Notation reference: {ws}/writing/notation.md. "
        f"Glossary reference: {ws}/writing/glossary.md.\n\n"
        f"Score each section 1-10 and provide specific improvement suggestions.\n"
        f"{paper_writing_requirement()}\n\n"
        f"After all critics finish, the editor will integrate all sections and critiques "
        f"into a coherent paper."
    )
    team_prompt = render_team_prompt(
        "Parallel section critique + integration",
        team_instructions,
        workspace_path=ws,
        language=orchestrator.config.language,
        paper_output=True,
    )
    teammates = [
        {
            "name": f"critic-{sid}",
            "skill": "sibyl-section-critic",
            "args": pack_skill_args(ws, name, sid),
        }
        for sid, name in PAPER_SECTIONS
        if remaining is None or sid in remaining
    ]
    post_steps = [
        {"type": "skill", "skill": "sibyl-editor", "args": ws},
    ]

    return action_cls(
        action_type="team",
        team={
            "team_name": "sibyl-writing-integrate",
            "teammates": teammates,
            "post_steps": post_steps,
            "prompt": team_prompt,
        },
        description=f"Agent Team: {len(teammates)}人并行批评 → 编辑整合"
        + (
            f"（恢复：已完成 {len(cp_info['completed_steps'])}/6）"
            if cp_info and cp_info["resuming"]
            else ""
        ),
        stage="writing_integrate",
        checkpoint_info=cp_info,
    )


def build_writing_final_review_action(
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the final writing review action."""
    return action_cls(
        action_type="skill",
        skills=[{"name": "sibyl-final-critic", "args": ws}],
        description="Top-tier conference-level paper review",
        stage="writing_final_review",
    )


def build_writing_latex_action(
    orchestrator: Any,
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the LaTeX conversion/compile action.

    Attempts deterministic compilation first (pandoc + latexmk), then falls
    back to the sibyl-latex-writer skill agent on failure.
    """
    from .common_utils import build_repo_python_cli_command

    compile_cmd = build_repo_python_cli_command("latex-compile", ws)
    fallback_skill = {
        "name": "sibyl-latex-writer",
        "args": pack_skill_args(
            ws,
            orchestrator.config.ssh_server,
            orchestrator.config.remote_base,
        ),
    }
    return action_cls(
        action_type="bash",
        bash_command=compile_cmd,
        skills=[fallback_skill],
        description=(
            "LaTeX 编译: 先尝试 pandoc+latexmk 确定性编译，"
            "失败则 fallback 到 sibyl-latex-writer agent"
        ),
        stage="writing_latex",
    )


def build_review_action(
    orchestrator: Any,
    ws: str,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the parallel critic/supervisor/Codex review action."""
    skills = [
        {"name": "sibyl-critic", "args": ws},
        {"name": "sibyl-supervisor", "args": ws},
    ]
    if orchestrator.config.codex_enabled:
        skills.append({
            "name": "sibyl-codex-reviewer",
            "args": codex_reviewer_args(orchestrator.config, "review", ws),
        })
    return action_cls(
        action_type="skills_parallel",
        skills=skills,
        description="并行审查：批评 + 监督" + (" + Codex" if orchestrator.config.codex_enabled else ""),
        stage="review",
    )


def build_reflection_action(
    ws: str,
    iteration: int,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the reflection action."""
    return action_cls(
        action_type="skill",
        skills=[{"name": "sibyl-reflection", "args": pack_skill_args(ws, iteration)}],
        description="Reflection agent: classify issues, generate improvement plan and lessons",
        stage="reflection",
    )


def build_quality_gate_action(
    orchestrator: Any,
    *,
    action_cls: type[Any],
) -> Any:
    """Build the display-only quality gate action."""
    is_done, score, threshold, max_iters, iteration = orchestrator._is_pipeline_done()
    action_plan = _load_workspace_action_plan(orchestrator.ws, persist_normalized=True) or {}
    trajectory = action_plan.get("quality_trajectory", "")
    focus = ""
    recommended_focus = action_plan.get("recommended_focus", [])
    if recommended_focus:
        focus = str(recommended_focus[0])[:120]
    extra_parts = []
    if trajectory:
        extra_parts.append(f"trajectory={trajectory}")
    if focus:
        extra_parts.append(f"focus={focus}")
    extra = f" ({'; '.join(extra_parts)})" if extra_parts else ""

    if is_done:
        return action_cls(
            action_type="done",
            description=(
                f"Pipeline complete (score={score}, threshold={threshold}, "
                f"iter={iteration}/{max_iters}).{extra}"
            ),
            stage="done",
        )

    summary_parts = [
        f"score={score:.1f}",
        f"threshold={threshold:.1f}",
        f"iter={iteration}/{max_iters}",
        f"decision=CONTINUE (score < threshold)",
    ]
    if trajectory:
        summary_parts.append(f"trajectory={trajectory}")
    if focus:
        summary_parts.append(f"next_focus={focus}")
    summary_line = " | ".join(summary_parts)
    return action_cls(
        action_type="bash",
        bash_command=f"echo 'Quality Gate: {summary_line}'",
        description=(
            f"Quality gate: score={score} < {threshold}, "
            f"starting iteration {iteration + 1}{extra}"
        ),
        stage="quality_gate",
    )
