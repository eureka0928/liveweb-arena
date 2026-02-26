"""Validators framework for answer validation

This module provides:
- Base classes for question templates and validators
- Generic validators (numeric, exact match, boolean, etc.)
- LLM-based validator for flexible answer comparison

Plugin-specific templates should be defined in their respective plugin directories:
    plugins/weather/templates/ - Weather-specific templates
    plugins/stock/templates/ - Stock-specific templates
"""

from .base import (
    QuestionTemplate,
    Variable,
    VariableType,
    Validator,
    ValidationResult,
    GeneratedQuestion,
)
from .validators import (
    NumericToleranceValidator,
    ExactMatchValidator,
    BooleanValidator,
    ContainsValidator,
)
from .llm_validator import (
    LLMValidator,
    LLMValidationResult,
    validate_answers_with_llm,
)

__all__ = [
    # Base classes
    "QuestionTemplate",
    "Variable",
    "VariableType",
    "Validator",
    "ValidationResult",
    "GeneratedQuestion",
    # Generic validators
    "NumericToleranceValidator",
    "ExactMatchValidator",
    "BooleanValidator",
    "ContainsValidator",
    # LLM-based validator
    "LLMValidator",
    "LLMValidationResult",
    "validate_answers_with_llm",
]
