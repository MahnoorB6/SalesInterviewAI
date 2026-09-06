from sqlalchemy import Column, Integer, Float, Text, String, ForeignKey
from sqlalchemy.orm import relationship

from app.database.database import Base


class Evaluation(Base):
    __tablename__ = "evaluations"

    id = Column(Integer, primary_key=True, index=True)

    interview_id = Column(
        Integer,
        ForeignKey("interviews.id"),
        nullable=False,
        unique=True,
    )

    communication = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    sales_knowledge = Column(Float, nullable=True)
    lead_qualification = Column(Float, nullable=True)
    objection_handling = Column(Float, nullable=True)
    persuasion = Column(Float, nullable=True)
    closing_ability = Column(Float, nullable=True)

    overall_score = Column(Float, nullable=True)

    recommendation = Column(String(100), nullable=True)

    strengths = Column(Text, nullable=True)
    weaknesses = Column(Text, nullable=True)

    interview = relationship("Interview", backref="evaluation")