"""Registry for external Orchestra Research skills.

Scans ~/.orchestra/skills/ (or a configured directory), parses SKILL.md
frontmatter, and provides a compact index that can be injected into Sibyl
agent prompts so they can invoke relevant skills on demand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Sequence

import yaml


_DEFAULT_SKILLS_DIR = Path.home() / ".orchestra" / "skills"
_DEFAULT_MAX_SKILLS = 15

# Frontmatter delimiter
_FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_ASCII_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+._-]{2,}")

_TOPIC_CONCEPT_ALIASES: dict[str, tuple[str, ...]] = {
    "planning": (
        "planning",
        "plan",
        "task plan",
        "methodology",
        "experiment design",
        "规划",
        "计划",
        "方案",
        "实验设计",
        "资源规划",
    ),
    "pilot": (
        "pilot",
        "pretest",
        "feasibility",
        "smoke test",
        "small-scale",
        "small scale",
        "预实验",
        "先导",
        "小规模",
        "快速验证",
        "可行性验证",
    ),
    "full": (
        "full experiment",
        "full-scale",
        "full scale",
        "all-scale",
        "complete run",
        "全量",
        "完整实验",
        "正式实验",
        "大规模",
    ),
    "training": (
        "training",
        "train",
        "pretraining",
        "pre-train",
        "post-training",
        "post training",
        "训练",
        "预训练",
        "后训练",
    ),
    "fine_tuning": (
        "fine-tuning",
        "fine tuning",
        "finetuning",
        "instruction tuning",
        "sft",
        "lora",
        "qlora",
        "adapter",
        "adapter tuning",
        "微调",
        "指令微调",
    ),
    "distributed": (
        "distributed",
        "multi-gpu",
        "multi gpu",
        "multi-node",
        "ddp",
        "fsdp",
        "deepspeed",
        "tensor parallel",
        "pipeline parallel",
        "model parallel",
        "sharded",
        "分布式",
        "多卡",
        "多机",
        "并行训练",
    ),
    "evaluation": (
        "evaluation",
        "evaluate",
        "benchmark",
        "benchmarks",
        "judge",
        "validation",
        "test",
        "testing",
        "评测",
        "测试",
        "基准",
        "验证",
        "打榜",
    ),
    "inference": (
        "inference",
        "serve",
        "serving",
        "deployment",
        "deploy",
        "latency",
        "throughput",
        "batch inference",
        "推理",
        "部署",
        "服务",
        "吞吐",
        "延迟",
        "在线推理",
    ),
    "optimization": (
        "optimization",
        "optimize",
        "oom",
        "memory",
        "vram",
        "throughput",
        "speedup",
        "flash attention",
        "batch size",
        "utilization",
        "优化",
        "加速",
        "显存",
        "显存利用率",
        "吃满显存",
        "批大小",
        "性能",
    ),
    "quantization": (
        "quantization",
        "quantize",
        "4-bit",
        "8-bit",
        "4bit",
        "8bit",
        "int4",
        "int8",
        "nf4",
        "awq",
        "gptq",
        "gguf",
        "hqq",
        "量化",
        "低比特",
    ),
    "data": (
        "data",
        "dataset",
        "datasets",
        "etl",
        "dedup",
        "curation",
        "preprocess",
        "preprocessing",
        "batch inference",
        "数据",
        "数据集",
        "清洗",
        "预处理",
        "去重",
    ),
    "observability": (
        "observability",
        "monitoring",
        "tracking",
        "trace",
        "logging",
        "dashboard",
        "监控",
        "追踪",
        "可观测",
        "日志",
        "仪表盘",
    ),
    "rl": (
        "rlhf",
        "reinforcement learning",
        "grpo",
        "ppo",
        "dpo",
        "rloo",
        "kto",
        "orpo",
        "preference optimization",
        "强化学习",
        "偏好优化",
    ),
    "multimodal": (
        "multimodal",
        "vision",
        "image",
        "audio",
        "speech",
        "video",
        "caption",
        "segmentation",
        "多模态",
        "视觉",
        "图像",
        "音频",
        "视频",
    ),
}

_TOPIC_STAGE_HINTS: tuple[tuple[tuple[str, ...], dict[str, float]], ...] = (
    (
        ("planning", "plan", "规划", "计划", "实验设计", "资源规划"),
        {"planning": 6.0, "evaluation": 3.0, "pilot": 2.0, "distributed": 1.5},
    ),
    (
        ("pilot", "预实验", "先导", "小规模", "快速验证", "可行性验证"),
        {"pilot": 6.0, "evaluation": 4.0, "inference": 3.0, "optimization": 3.0},
    ),
    (
        ("full", "全量", "完整实验", "正式实验", "大规模"),
        {"training": 4.0, "distributed": 4.0, "evaluation": 4.0, "observability": 2.0},
    ),
    (
        ("training", "train", "训练", "预训练", "微调", "后训练"),
        {"training": 5.0, "fine_tuning": 4.0, "distributed": 2.5, "optimization": 2.5},
    ),
    (
        ("evaluation", "eval", "benchmark", "评测", "测试", "基准", "验证"),
        {"evaluation": 6.0, "inference": 2.5, "observability": 1.5},
    ),
    (
        ("inference", "serving", "deployment", "推理", "部署", "服务"),
        {"inference": 6.0, "optimization": 3.0, "quantization": 2.0},
    ),
)

_ENTRY_CATEGORY_CONCEPTS: dict[str, dict[str, float]] = {
    "01-model-architecture": {"training": 1.5, "inference": 1.0},
    "03-fine-tuning": {"fine_tuning": 6.0, "training": 4.0, "optimization": 1.0},
    "05-data-processing": {"data": 6.0, "training": 1.5},
    "06-post-training": {"training": 5.0, "fine_tuning": 2.0, "rl": 4.0},
    "08-distributed-training": {"distributed": 6.0, "training": 4.5, "optimization": 1.0},
    "09-infrastructure": {"distributed": 2.0, "inference": 1.5},
    "10-optimization": {"optimization": 3.5, "quantization": 2.0},
    "11-evaluation": {"evaluation": 4.5, "inference": 1.0},
    "12-inference-serving": {"inference": 6.0, "optimization": 2.0, "quantization": 1.0},
    "13-mlops": {"observability": 5.0, "evaluation": 1.0},
    "15-rag": {"data": 2.0},
    "17-observability": {"observability": 6.0},
    "18-multimodal": {"multimodal": 6.0, "training": 1.0, "inference": 1.0},
    "20-ml-paper-writing": {"planning": 1.0},
    "21-research-ideation": {"planning": 4.0},
}

_ENTRY_INVOKE_CONCEPTS: dict[str, dict[str, float]] = {
    "peft": {"fine_tuning": 6.0, "training": 3.0, "optimization": 1.0},
    "axolotl": {"fine_tuning": 6.0, "training": 3.0},
    "llama-factory": {"fine_tuning": 6.0, "training": 3.0},
    "unsloth": {"fine_tuning": 5.0, "training": 3.0, "optimization": 2.0},
    "accelerate": {"distributed": 5.0, "training": 3.0},
    "deepspeed": {"distributed": 6.0, "training": 4.0, "optimization": 2.0},
    "pytorch-fsdp2": {"distributed": 6.0, "training": 4.0},
    "megatron-core": {"distributed": 6.0, "training": 4.0},
    "ray-train": {"distributed": 5.0, "training": 3.0},
    "torchtitan": {"distributed": 5.0, "training": 3.0},
    "vllm": {"inference": 6.0, "optimization": 3.0, "quantization": 1.0},
    "sglang": {"inference": 6.0, "optimization": 3.0},
    "tensorrt-llm": {"inference": 6.0, "optimization": 4.0, "quantization": 2.0},
    "llama-cpp": {"inference": 5.0, "quantization": 3.0},
    "lm-evaluation-harness": {"evaluation": 6.0},
    "bigcode-evaluation-harness": {"evaluation": 4.0},
    "nemo-evaluator": {"evaluation": 6.0},
    "flash-attention": {"optimization": 6.0, "training": 2.0, "inference": 2.0},
    "bitsandbytes": {"optimization": 3.0, "quantization": 5.0, "fine_tuning": 2.0},
    "awq": {"optimization": 2.0, "quantization": 6.0, "inference": 1.5},
    "gptq": {"optimization": 2.0, "quantization": 6.0, "inference": 1.5},
    "gguf": {"quantization": 6.0, "inference": 2.0},
    "hqq": {"quantization": 6.0, "optimization": 2.0},
    "mlflow": {"observability": 5.0},
    "tensorboard": {"observability": 5.0},
    "weights-and-biases": {"observability": 6.0},
    "langsmith": {"observability": 5.0},
    "phoenix": {"observability": 5.0},
}

_AGENT_ROLE_HINTS: dict[str, dict[str, float]] = {
    "planner": {"planning": 6.0, "evaluation": 4.0, "pilot": 3.0, "distributed": 2.0, "training": 1.5},
    "experimenter": {"training": 5.0, "fine_tuning": 4.0, "evaluation": 3.0, "inference": 3.0, "optimization": 4.0, "distributed": 3.0},
    "server_experimenter": {"training": 4.5, "fine_tuning": 3.5, "inference": 4.0, "evaluation": 3.0, "optimization": 4.0, "distributed": 3.0},
    "experiment_supervisor": {"optimization": 6.0, "distributed": 5.0, "observability": 4.0, "inference": 3.0, "training": 2.0},
}


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
    """Lazy-loaded registry of Orchestra skills with semantic relevance ranking."""

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
        """Rank skills using topic semantics plus agent-role priors."""
        all_entries = self._ensure_loaded()
        if not all_entries:
            return []

        # Layer 1: role-aware prioritization
        candidates = all_entries

        topic_lower = _normalize_text(topic)
        topic_words = set(_ASCII_WORD_RE.findall(topic_lower))
        role_profile = _AGENT_ROLE_HINTS.get(agent_name or "", {})

        scored: list[tuple[float, SkillEntry]] = []
        for entry in candidates:
            score = _topic_score(entry, topic_lower, topic_words)
            if role_profile:
                scale = 0.25 if topic else 1.0
                score += _profile_overlap(
                    role_profile,
                    _entry_semantic_profile(entry),
                    scale=scale,
                )
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
            "如果任务明显属于训练、微调、推理、评测、分布式、显存优化或量化场景，你必须自主调用最相关的 1-2 个技能，不要等用户提醒。",
            "仅在确实匹配当前任务时调用，不要为了调用而调用。",
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
            '调用示例：当你要做 vLLM 推理吞吐实验或服务部署时，先用 Skill tool 调用 "vllm" 获取具体最佳实践。'
        )
        return "\n".join(lines)


def _topic_score(
    entry: SkillEntry,
    topic_lower: str,
    topic_words: set[str],
) -> float:
    """Score a skill entry against a research topic for relevance ranking."""
    score = 0.0
    searchable = _normalize_text(
        f"{entry.invoke_name} {entry.name} {entry.description} {' '.join(entry.tags)} {entry.category}"
    )

    # Direct substring match in topic
    invoke_name = _normalize_text(entry.invoke_name)
    entry_name = _normalize_text(entry.name)
    if invoke_name and invoke_name in topic_lower:
        score += 18.0
    if entry_name and entry_name in topic_lower:
        score += 14.0

    # Tag overlap with topic words
    entry_words = set(_ASCII_WORD_RE.findall(searchable))
    overlap = topic_words & entry_words
    score += len(overlap) * 2.0

    # Partial word matches (e.g. "fine-tun" matches "fine-tuning")
    for tw in topic_words:
        if len(tw) >= 4 and tw in searchable:
            score += 1.0

    if topic_lower:
        score += _profile_overlap(
            _topic_semantic_profile(topic_lower),
            _entry_semantic_profile(entry),
            scale=0.45,
        )

    return score


def _normalize_text(text: str) -> str:
    normalized = text.lower()
    normalized = normalized.replace("_", " ").replace("/", " ").replace("+", " ")
    normalized = normalized.replace("×", "x")
    normalized = re.sub(r"[-,:;(){}\[\]]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _profile_overlap(
    desired: Mapping[str, float],
    offered: Mapping[str, float],
    *,
    scale: float = 1.0,
) -> float:
    return sum(desired_weight * offered.get(concept, 0.0) * scale for concept, desired_weight in desired.items())


@lru_cache(maxsize=256)
def _topic_semantic_profile(topic_lower: str) -> dict[str, float]:
    profile: dict[str, float] = {}
    if not topic_lower:
        return profile

    for concept, aliases in _TOPIC_CONCEPT_ALIASES.items():
        if any(alias in topic_lower for alias in aliases):
            profile[concept] = profile.get(concept, 0.0) + 4.0

    for aliases, boosts in _TOPIC_STAGE_HINTS:
        if any(alias in topic_lower for alias in aliases):
            for concept, weight in boosts.items():
                profile[concept] = profile.get(concept, 0.0) + weight

    return profile


@lru_cache(maxsize=512)
def _entry_semantic_profile(entry: SkillEntry) -> dict[str, float]:
    searchable = _normalize_text(
        f"{entry.invoke_name} {entry.name} {entry.description} {' '.join(entry.tags)} {entry.category}"
    )
    profile: dict[str, float] = {}

    for concept, aliases in _TOPIC_CONCEPT_ALIASES.items():
        if any(alias in searchable for alias in aliases):
            profile[concept] = max(profile.get(concept, 0.0), 3.0)

    category_key = entry.category.split("/")[0]
    for concept, weight in _ENTRY_CATEGORY_CONCEPTS.get(category_key, {}).items():
        profile[concept] = max(profile.get(concept, 0.0), weight)

    for concept, weight in _ENTRY_INVOKE_CONCEPTS.get(entry.invoke_name, {}).items():
        profile[concept] = max(profile.get(concept, 0.0), weight)

    return profile


# Module-level singleton for convenience
_registry: SkillRegistry | None = None


def get_registry(skills_dir: Path | str | None = None) -> SkillRegistry:
    """Get or create the module-level skill registry singleton."""
    global _registry
    resolved = Path(skills_dir).expanduser() if skills_dir else _DEFAULT_SKILLS_DIR
    if _registry is None or _registry.skills_dir != resolved:
        _registry = SkillRegistry(skills_dir=resolved)
    return _registry
