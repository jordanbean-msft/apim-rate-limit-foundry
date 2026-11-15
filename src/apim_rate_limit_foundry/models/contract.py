from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    """Reject unknown JSON fields rather than silently accepting misspelled settings."""

    model_config = ConfigDict(extra="forbid")
