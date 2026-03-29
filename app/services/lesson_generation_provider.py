from dataclasses import dataclass, field
from typing import Protocol, Any


@dataclass(slots=True)
class PromptBundle:
    system_prompt: str
    user_prompt: str
    metadata: dict[str, Any] = field(default_factory=dict)


class LessonGenerationProvider(Protocol):
    provider_name: str

    def generate(self, prompt: PromptBundle) -> str:
        ...
