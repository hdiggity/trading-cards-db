from typing import Optional

from pydantic import Field
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, func

# fields shared between models and Pydantic
shared_card_field_specs = [
    ("name", str, lambda: Column(String, nullable=False), ...),
    (
        "sport",
        Optional[str],
        lambda: Column(String, default="baseball"),
        Field(default="baseball"),
    ),
    ("brand", Optional[str], lambda: Column(String), None),
    ("number", Optional[str], lambda: Column(String), None),
    ("copyright_year", Optional[str], lambda: Column(String), None),
    ("team", Optional[str], lambda: Column(String), None),
    ("card_set", Optional[str], lambda: Column(String), None),
    ("condition", Optional[str], lambda: Column(String), None),
    ("is_player", Optional[bool], lambda: Column(Boolean, default=True), True),
    ("features", Optional[str], lambda: Column(String), "none"),
    ("value_estimate", Optional[str], lambda: Column(String), None),
    ("notes", Optional[str], lambda: Column(String), None),
]

# fields used only by SQLAlchemy models (not Pydantic Create)
db_only_field_specs = [
    (
        "quantity",
        int,
        lambda: Column(Integer, default=1),
        1,
    ),
    (
        "date_added",
        str,
        lambda: Column(DateTime, server_default=func.now()),
        None,
    ),
    (
        "last_updated",
        Optional[str],
        lambda: Column(DateTime, onupdate=func.now()),
        None,
    ),
]

# build SQLAlchemy column dict for use in models
sqlalchemy_card_columns = {
    name: factory()
    for name, _, factory, _ in shared_card_field_specs + db_only_field_specs
}

# pydantic annotations and defaults (only shared fields)
pydantic_annotations = {
    name: typ for name, typ, _, _ in shared_card_field_specs
}
pydantic_defaults = {
    name: default for name, _, _, default in shared_card_field_specs
}

# full annotations/defaults for CardRead (shared + db-only)
pydantic_read_annotations = {
    name: typ for name, typ, _, _ in shared_card_field_specs + db_only_field_specs
}
pydantic_read_defaults = {
    name: default for name, _, _, default in shared_card_field_specs + db_only_field_specs
}