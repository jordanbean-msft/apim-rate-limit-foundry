from pydantic import BaseModel


class DeletedRecord(BaseModel):
    """Acknowledgement that a configuration record was tombstoned."""

    deleted: str
