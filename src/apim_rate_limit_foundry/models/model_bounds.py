from apim_rate_limit_foundry.models.contract import Contract


class ModelBounds(Contract):
    """Token ceilings pinned at admission for out-of-bounds flags and upper-bound charges."""

    max_input_tokens: int
    max_output_tokens: int
