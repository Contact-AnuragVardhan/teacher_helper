from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ModelProfile:
    provider: str
    api_mode: str

    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_output_tokens: Optional[int] = None

    reasoning_effort: Optional[str] = None
    text_verbosity: Optional[str] = None


EXACT_MODEL_PROFILES: dict[str, ModelProfile] = {
    "gpt-5.4": ModelProfile(
        provider="openai",
        api_mode="responses",
        temperature=0.2,
        top_p=1.0,
        max_output_tokens=1000,
        reasoning_effort="none",
        text_verbosity="low",
    ),
    "gpt-5.4-mini": ModelProfile(
        provider="openai",
        api_mode="responses",
        temperature=0.2,
        top_p=1.0,
        max_output_tokens=900,
        reasoning_effort="none",
        text_verbosity="low",
    ),
    "gpt-5.4-nano": ModelProfile(
        provider="openai",
        api_mode="responses",
        temperature=0.2,
        top_p=1.0,
        max_output_tokens=800,
        reasoning_effort="none",
        text_verbosity="low",
    ),
    "gpt-4o-mini": ModelProfile(
        provider="openai",
        api_mode="chat_completions",
        temperature=0.2,
        top_p=1.0,
        max_output_tokens=900,
    ),

    
    "gemini-2.5-flash": ModelProfile(
        provider="google",
        api_mode="generate_content",
        temperature=0.2,
        top_p=0.95,
        max_output_tokens=900,
    ),
    "gemini-2.5-pro": ModelProfile(
        provider="google",
        api_mode="generate_content",
        temperature=0.2,
        top_p=0.95,
        max_output_tokens=1000,
    ),
}


PREFIX_MODEL_PROFILES: tuple[tuple[str, ModelProfile], ...] = (
    (
        "gpt-5.4-mini-",
        ModelProfile(
            provider="openai",
            api_mode="responses",
            temperature=0.2,
            top_p=1.0,
            max_output_tokens=900,
            reasoning_effort="none",
            text_verbosity="low",
        ),
    ),
    (
        "gpt-5.4-",
        ModelProfile(
            provider="openai",
            api_mode="responses",
            temperature=0.2,
            top_p=1.0,
            max_output_tokens=1000,
            reasoning_effort="none",
            text_verbosity="low",
        ),
    ),
    (
        "gpt-4o-",
        ModelProfile(
            provider="openai",
            api_mode="chat_completions",
            temperature=0.2,
            top_p=1.0,
            max_output_tokens=900,
        ),
    ),
    (
        "gemini-",
        ModelProfile(
            provider="google",
            api_mode="generate_content",
            temperature=0.2,
            top_p=0.95,
            max_output_tokens=900,
        ),
    ),
)


def resolve_model_profile(model_name: str) -> ModelProfile:
    model_name = (model_name or "").strip()
    if not model_name:
        raise ValueError("Model name cannot be empty.")

    exact = EXACT_MODEL_PROFILES.get(model_name)
    if exact:
        return exact

    for prefix, profile in PREFIX_MODEL_PROFILES:
        if model_name.startswith(prefix):
            return profile

    if model_name.startswith("gpt-"):
        return ModelProfile(
            provider="openai",
            api_mode="responses",
            temperature=0.2,
            top_p=1.0,
            max_output_tokens=900,
            reasoning_effort="none" if model_name.startswith("gpt-5") else None,
            text_verbosity="low" if model_name.startswith("gpt-5") else None,
        )

    raise ValueError(f"No model profile registered for model '{model_name}'.")