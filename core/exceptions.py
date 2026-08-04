class PipelineError(Exception):
    """Base exception for the MLR pipeline."""
    pass

class GenerationError(PipelineError):
    """Raised when the LLM fails to generate a draft."""
    pass

class ValidationError(PipelineError):
    """Raised when parsing or structuring data fails."""
    pass

class ResolutionError(PipelineError):
    """Raised when regulatory rules cannot be resolved."""
    pass

class ComplianceError(PipelineError):
    """Raised when the grading process fails."""
    pass
