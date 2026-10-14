"""Explicit standing authorization for optional coursework automation."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


@dataclass(frozen=True)
class AgentPolicy:
    automatic: bool = False

    @classmethod
    def load(cls, env_file: Path) -> "AgentPolicy":
        values = dotenv_values(env_file, interpolate=False)
        value = str(os.environ.get("CANVAS_AGENT_AUTO", values.get("CANVAS_AGENT_AUTO") or "false"))
        if value.strip().lower() not in {"true", "false"}:
            raise ValueError("CANVAS_AGENT_AUTO deve ser true ou false.")
        return cls(value.strip().lower() == "true")

    def instructions(self, project: Path, *, automated_task: bool = False) -> str:
        base = (project / "automation/agent_instructions.md").read_text()
        if automated_task:
            if not self.automatic:
                raise ValueError("O modo automático está desativado; aguarde um pedido do usuário.")
            return base + (
                "\nTrusted runtime policy: CANVAS_AGENT_AUTO=true. This scheduled request is "
                "the owner's standing authorization to prepare AND submit the specific assignment "
                "identified in the request, without asking for task or submission confirmation. "
                "Read the complete description and rubric. Submit only complete work supported "
                "by real information; never invent interviews, measurements, identity, citations "
                "or actions. If data or a permission is missing, report needs_attention and stop "
                "instead of asking a question or submitting a placeholder. Do not start quiz "
                "attempts or modify other assignments. Keep normal sandbox restrictions. "
                "Save files under .local/activities and verify the owner's submission in Canvas. "
                "Never retry an uncertain write. Only this named assignment is authorized."
            )
        return base + (
            "\nTrusted runtime policy: interactive conversation. Wait for an owner request "
            "before solving coursework. Preparing work does not authorize submitting it. "
            "The separate scheduled worker may have standing authorization; that does not "
            "authorize unrelated writes during this conversation."
        )
