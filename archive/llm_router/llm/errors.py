from __future__ import annotations


class LLMConfigError(Exception):
    """
    Configuration is missing, invalid, or internally inconsistent --
    e.g. a required API key env var isn't set, llm_config.yaml has an
    unrecognized key (a likely typo) or an invalid task->provider value,
    or cloud is requested while llm.cloud.enabled is false.

    Distinct from LLMUnavailableError: this means the setup is wrong,
    not that a reachable service failed at call time.
    """


class LLMUnavailableError(Exception):
    """
    A configured provider could not be reached or returned an unusable
    response -- e.g. Ollama isn't running, a network timeout, the cloud
    API returned an error, or a response came back empty.
    """

    def __init__(self, provider: str, message: str, cause: Exception | None = None):
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
        self.cause = cause


class LLMBudgetExceededError(Exception):
    """
    A configured call budget (llm.cloud.max_calls_per_process) has been
    exhausted. Deliberately a distinct type from LLMUnavailableError --
    this is a crude, intentional cost guard tripping, not a service
    failure, though router.py treats both the same way for fallback
    purposes (see router.py's docstring).
    """
