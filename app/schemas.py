# app/schemas.py

from pydantic import BaseModel

from app.fields import (
    pydantic_annotations,
    pydantic_defaults,
    pydantic_read_annotations,
    pydantic_read_defaults,
)


class CardBase(BaseModel):
    name: str

    __annotations__ = {"name": str, **pydantic_annotations}
    vars().update(pydantic_defaults)


class CardCreate(CardBase):
    pass


class CardRead(CardBase):
    id: int

    __annotations__ = {**CardBase.__annotations__, **pydantic_read_annotations}
    vars().update(pydantic_read_defaults)

    class Config:
        from_attributes = True
