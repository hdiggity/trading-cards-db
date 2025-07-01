from sqlalchemy import Column, DateTime, Integer, String, Text, func
from sqlalchemy.ext.declarative import declarative_base

from app.fields import sqlalchemy_card_columns

Base = declarative_base()


class Card(Base):
    __tablename__ = "cards"

    id = Column(Integer, primary_key=True, index=True)

    # inject all fields (shared + db-only)
    locals().update(sqlalchemy_card_columns)


class LearningData(Base):
    __tablename__ = "learning_data"

    id = Column(Integer, primary_key=True, index=True)
    image_filename = Column(String, nullable=False)
    field_name = Column(String, nullable=False)
    ai_original_value = Column(Text)
    user_corrected_value = Column(Text)
    # 'field_change', 'value_change', 'format_change'
    correction_type = Column(String)
    context_data = Column(Text)  # JSON string with additional context
    timestamp = Column(DateTime, server_default=func.now())

    def __repr__(self):
        return f"<LearningData(field={self.field_name}, correction={self.correction_type})>"
