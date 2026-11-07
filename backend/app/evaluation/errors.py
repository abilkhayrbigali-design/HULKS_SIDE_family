"""Safe failures shared by the provider, pipeline and persisted worker."""

MESSAGES = {
    "AI_NOT_CONFIGURED": "AI API key is not configured.",
    "AI_INVALID_SNAPSHOT": "Evaluation snapshots are invalid.",
    "AI_INVALID_RESPONSE": "AI returned an invalid evaluation. Please retry or request review.",
    "AI_TIMEOUT": "AI request timed out. Please retry.",
    "AI_RATE_LIMITED": "AI request limit was reached. Please retry later.",
    "AI_UNAVAILABLE": "AI service is temporarily unavailable. Please retry later.",
    "AI_AUTHENTICATION_FAILED": "AI credentials or model access are not valid.",
    "AI_REQUEST_REJECTED": "AI service rejected the evaluation request.",
    "AI_REFUSED": "AI declined to evaluate this dialogue. Manual review is required.",
    "AI_INCOMPLETE": "AI did not finish the evaluation. Please retry or request review.",
}


class EvaluationError(Exception):
    """Contains fixed public text only, never a model response or HTTP exception."""

    def __init__(self, code: str, *, retryable: bool = False, provenance: dict | None = None):
        # Reject accidental use of user-controlled error text at the public boundary.
        if code not in MESSAGES:
            raise ValueError("Unknown evaluation error code")
        self.code = code
        self.safe_message = MESSAGES[code]
        self.message = self.safe_message
        self.retryable = retryable
        self.provenance = provenance
        super().__init__(self.safe_message)
