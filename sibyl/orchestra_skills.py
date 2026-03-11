"""Registry for external Orchestra Research skills.

Scans ~/.orchestra/skills/ (or a configured directory), parses SKILL.md
frontmatter, and provides a compact index that can be injected into Sibyl
agent prompts so they can invoke relevant skills on demand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import yaml


_DEFAULT_SKILLS_DIR = Path.home() / ".orchestra" / "skills"
_DEFAULT_MAX_SKILLS = 15

# Frontmatter delimiter
_FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


@dataclass(frozen=True)
class SkillEntry:
    """Compact representation of one external skill."""

    name: str
    invoke_name: str  # Claude Code skill invocation name (e.g. "peft")
    description: str
    tags: tuple[str, ...]
    category: str  # e.g. "03-fine-tuning"


@dataclass
class SkillRegistry:
    """Lazy-loaded registry of Orchestra skills with dual-layer filtering."""

    skills_dir: Path = field(default_factory=lambda: _DEFAULT_SKILLS_DIR)
    _entries: list[SkillEntry] | None = field(default=None, repr=False)
    _mtime: float = field(default=0.0, repr=False)

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def _scan(self) -> list[SkillEntry]:
        entries: list[SkillEntry] = []
        if not self.skills_dir.is_dir():
            return entries
        for skill_md in sorted(self.skills_dir.glob("*/*/SKILL.md")):
            entry = self._parse_skill(skill_md)
            if entry is not None:
                entries.append(entry)
        # Also check single-level skills (e.g. 20-ml-paper-writing/SKILL.md)
        for skill_md in sorted(self.skills_dir.glob("*/SKILL.md")):
            if skill_md.parent.parent == self.skills_dir:
                # Already a category-level skill (no subdirectory)
                entry = self._parse_skill(skill_md)
                if entry is not None and entry not in entries:
                    entries.append(entry)
        return entries

    @staticmethod
    def _parse_skill(path: Path) -> SkillEntry | None:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        m = _FM_RE.match(text)
        if not m:
            return None
        try:
            fm = yaml.safe_load(m.group(1))
        except yaml.YAMLError:
            return None
        if not isinstance(fm, dict) or "name" not in fm:
            return None

        name = str(fm["name"])
        description = str(fm.get("description", ""))
        # Truncate to first sentence for compactness
        first_sentence = description.split(". ")[0].rstrip(".")
        tags_raw = fm.get("tags", [])
        tags = tuple(str(t) for t in tags_raw) if isinstance(tags_raw, list) else ()

        # Derive category from directory structure
        rel = path.relative_to(path.parents[2]) if len(path.parts) > 3 else path
        category = rel.parts[0] if rel.parts else ""

        # Invoke name: the directory name (e.g. "peft", "vllm")
        invoke_name = path.parent.name
        # If it's a category-level skill, use the category name
        if path.parent.parent == path.parents[2]:
            invoke_name = path.parent.name

        return SkillEntry(
            name=name,
            invoke_name=invoke_name,
            description=first_sentence,
            tags=tags,
            category=category,
        )

    def _ensure_loaded(self) -> list[SkillEntry]:
        if self._entries is not None and self.skills_dir.is_dir():
            try:
                current_mtime = self.skills_dir.stat().st_mtime
            except OSError:
                current_mtime = 0.0
            if current_mtime <= self._mtime:
                return self._entries
        self._entries = self._scan()
        try:
            self._mtime = self.skills_dir.stat().st_mtime if self.skills_dir.is_dir() else 0.0
        except OSError:
            self._mtime = 0.0
        return self._entries

    @property
    def entries(self) -> list[SkillEntry]:
        return list(self._ensure_loaded())

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def filter_skills(
        self,
        *,
        agent_name: str | None = None,
        topic: str = "",
        max_results: int = _DEFAULT_MAX_SKILLS,
    ) -> list[SkillEntry]:
        """Dual-layer filter: role-based category filter + topic keyword matching.

        Since the user opted for "all agents get everything", the role layer
        currently passes all categories through. It's kept as a hook for
        future fine-tuning.
        """
        all_entries = self._ensure_loaded()
        if not all_entries:
            return []

        # Layer 1: role-based (currently pass-through)
        candidates = all_entries

        # Layer 2: topic keyword scoring
        if not topic:
            return candidates[:max_results]

        topic_lower = topic.lower()
        topic_words = set(re.findall(r"[a-z]{3,}", topic_lower))

        scored: list[tuple[float, SkillEntry]] = []
        for entry in candidates:
            score = _topic_score(entry, topic_lower, topic_words)
            scored.append((score, entry))

        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:max_results]]

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_index(
        self,
        skills: Sequence[SkillEntry] | None = None,
        *,
        agent_name: str | None = None,
        topic: str = "",
        max_results: int = _DEFAULT_MAX_SKILLS,
    ) -> str:
        """Render a compact markdown table for prompt injection."""
        if skills is None:
            skills = self.filter_skills(
                agent_name=agent_name,
                topic=topic,
                max_results=max_results,
            )
        if not skills:
            return ""

        lines = [
            "以下技能可通过 Skill tool 按需调用，获取该领域的专家级指导和最佳实践。",
            "仅在确实需要深入了解某个工具/库/方法时调用，不要为了调用而调用。",
            "",
            "| Skill | 说明 | Tags |",
            "|-------|------|------|",
        ]
        for entry in skills:
            tags_str = ", ".join(entry.tags[:4]) if entry.tags else ""
            desc = entry.description[:100]
            lines.append(f"| {entry.invoke_name} | {desc} | {tags_str} |")

        lines.append("")
        lines.append(
            '调用示例：当你需要 vLLM 推理服务的详细用法时，使用 Skill tool 调用 "vllm"。'
        )
        return "\n".join(lines)


def _topic_score(
    entry: SkillEntry,
    topic_lower: str,
    topic_words: set[str],
) -> float:
    """Score a skill entry against a research topic for relevance ranking."""
    score = 0.0
    searchable = f"{entry.name} {entry.description} {' '.join(entry.tags)}".lower()

    # Direct substring match in topic
    if entry.invoke_name.lower() in topic_lower:
        score += 10.0
    if entry.name.lower() in topic_lower:
        score += 8.0

    # Tag overlap with topic words
    entry_words = set(re.findall(r"[a-z]{3,}", searchable))
    overlap = topic_words & entry_words
    score += len(overlap) * 2.0

    # Partial word matches (e.g. "fine-tun" matches "fine-tuning")
    for tw in topic_words:
        if len(tw) >= 4 and tw in searchable:
            score += 1.0

    return score


# Module-level singleton for convenience
_registry: SkillRegistry | None = None


def get_registry(skills_dir: Path | str | None = None) -> SkillRegistry:
    """Get or create the module-level skill registry singleton."""
    global _registry
    resolved = Path(skills_dir).expanduser() if skills_dir else _DEFAULT_SKILLS_DIR
    if _registry is None or _registry.skills_dir != resolved:
        _registry = SkillRegistry(skills_dir=resolved)
    return _registry
