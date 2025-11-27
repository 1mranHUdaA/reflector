from sqlalchemy import Column, Integer, String, Text, DateTime, func
from db import Base

class Scan(Base):
    __tablename__ = "scans"

    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String(255), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="pending")
    parameters = Column(Text)
    hidden_params = Column(Text)
    xss_urls = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
