"""Base Pydantic models for ArangoDB documents."""

from pydantic import BaseModel, ConfigDict, Field


class ArangoDocument(BaseModel):
    """Base Pydantic model for ArangoDB documents."""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        extra="ignore",
    )

    id: str | None = Field(default=None, alias="_id")
    key: str | None = Field(default=None, alias="_key")
    rev: str | None = Field(default=None, alias="_rev")


class ArangoEdge(ArangoDocument):
    """Base Pydantic model for ArangoDB edge documents."""

    from_id: str = Field(..., alias="_from")
    to_id: str = Field(..., alias="_to")
