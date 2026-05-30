from __future__ import annotations

import contextlib
import io
import os
import threading
from pathlib import Path
from typing import TextIO


BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEEPSEEK_AGENT_PREPROMPT_FILE = BASE_DIR / "config" / "deepseek_agent_preprompt.md"
OPENINTERPRETER_OUTPUT_CHARS = 50_000
OPENINTERPRETER_DEFAULT_TIMEOUT_SECONDS = 300
OPENINTERPRETER_DEEPSEEK_V4_MODEL = os.getenv(
    "OPENINTERPRETER_DEEPSEEK_V4_MODEL",
    "openai/deepseek-chat",
)
OPENINTERPRETER_DEEPSEEK_API_BASE = os.getenv(
    "OPENINTERPRETER_DEEPSEEK_API_BASE",
    "https://api.deepseek.com/v1",
)
OPENINTERPRETER_OLLAMA_MODEL = os.getenv(
    "OPENINTERPRETER_OLLAMA_MODEL",
    "ollama/qwen3.5:35b-a3b-coding-nvfp4",
)
OPENINTERPRETER_OLLAMA_API_BASE = os.getenv(
    "OPENINTERPRETER_OLLAMA_API_BASE",
    "http://localhost:11434",
)
SUPPORTED_AGENT_PROVIDERS = {"deepseek", "ollama"}
OPENINTERPRETER_RUN_LOCK = threading.Lock()


class TeeCapture(io.StringIO):
    def __init__(self, target: TextIO | None = None):
        super().__init__()
        self.target = target

    def write(self, value: str) -> int:
        written = super().write(value)
        if self.target is not None:
            self.target.write(value)
            self.target.flush()
        return written

    def flush(self) -> None:
        super().flush()
        if self.target is not None:
            self.target.flush()


def openinterpreter_chunk_text(chunk: dict) -> str:
    content = chunk.get("content")
    if content in (None, ""):
        return ""
    if chunk.get("format") == "active_line":
        return ""
    if chunk.get("type") in {"confirmation", "review"}:
        return ""
    if chunk.get("start") or chunk.get("end"):
        return ""
    return str(content)


def load_deepseek_agent_preprompt() -> str:
    try:
        return DEEPSEEK_AGENT_PREPROMPT_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def normalize_agent_provider(provider: str | None) -> str:
    selected = (provider or "deepseek").strip().lower()
    if selected not in SUPPORTED_AGENT_PROVIDERS:
        raise ValueError(f"provider must be one of: {', '.join(sorted(SUPPORTED_AGENT_PROVIDERS))}")
    return selected


def openinterpreter_defaults_for_provider(provider: str | None) -> tuple[str, str]:
    selected = normalize_agent_provider(provider)
    if selected == "ollama":
        return OPENINTERPRETER_OLLAMA_MODEL, OPENINTERPRETER_OLLAMA_API_BASE
    return OPENINTERPRETER_DEEPSEEK_V4_MODEL, OPENINTERPRETER_DEEPSEEK_API_BASE


def compose_deepseek_agent_prompt(prompt: str) -> str:
    preprompt = load_deepseek_agent_preprompt()
    user_prompt = prompt.strip()
    if not preprompt:
        return user_prompt
    return preprompt + "\n\n## Mission utilisateur\n\n" + user_prompt


def clamp_openinterpreter_timeout(timeout_seconds: int | None, hard_timeout_seconds: int = 3600) -> int:
    if timeout_seconds is None:
        timeout_seconds = OPENINTERPRETER_DEFAULT_TIMEOUT_SECONDS
    return max(1, min(int(timeout_seconds), int(hard_timeout_seconds)))


def resolve_openinterpreter_api_key(api_key: str | None = None, provider: str | None = None) -> str | None:
    selected_provider = normalize_agent_provider(provider)
    if selected_provider == "ollama":
        return api_key
    return (
        api_key
        or os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("OPENAI_ADMIN_KEY")
    )


def run_openinterpreter_chat(
    prompt: str,
    model: str,
    api_base: str,
    api_key: str | None,
    auto_run: bool,
    llm_supports_functions: bool,
    context_window: int,
    max_tokens: int,
    cwd: Path,
    stdout_target: TextIO | None = None,
    stderr_target: TextIO | None = None,
    provider: str = "deepseek",
) -> dict:
    try:
        from interpreter import interpreter
    except ImportError as exc:
        raise RuntimeError(
            "OpenInterpreter is not installed in the gateway Python environment. "
            "Install it in the same venv that runs src/mcp_gateway.py."
        ) from exc

    selected_provider = normalize_agent_provider(provider)
    selected_api_key = resolve_openinterpreter_api_key(api_key, selected_provider)
    interpreter.llm.model = model
    interpreter.llm.api_base = api_base
    interpreter.llm.api_key = selected_api_key
    interpreter.auto_run = auto_run
    interpreter.disable_telemetry = True
    interpreter.llm.context_window = int(context_window)
    interpreter.llm.max_tokens = int(max_tokens)

    if hasattr(interpreter.llm, "supports_functions"):
        interpreter.llm.supports_functions = llm_supports_functions

    stdout = TeeCapture(stdout_target)
    stderr = TeeCapture(stderr_target)

    with OPENINTERPRETER_RUN_LOCK:
        previous_cwd = Path.cwd()
        previous_openai_api_key = os.environ.get("OPENAI_API_KEY")
        previous_deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY")
        os.chdir(cwd)
        try:
            if selected_api_key:
                os.environ["OPENAI_API_KEY"] = selected_api_key
                if selected_provider == "deepseek":
                    os.environ["DEEPSEEK_API_KEY"] = selected_api_key

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                for chunk in interpreter.chat(prompt, display=False, stream=True):
                    text = openinterpreter_chunk_text(chunk)
                    if text:
                        print(text, end="")
                chat_result = interpreter.messages[interpreter.last_messages_count :]
        finally:
            if previous_openai_api_key is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = previous_openai_api_key

            if previous_deepseek_api_key is None:
                os.environ.pop("DEEPSEEK_API_KEY", None)
            else:
                os.environ["DEEPSEEK_API_KEY"] = previous_deepseek_api_key

            os.chdir(previous_cwd)

    return {
        "stdout": stdout.getvalue(),
        "stderr": stderr.getvalue(),
        "chat_result": chat_result,
    }
