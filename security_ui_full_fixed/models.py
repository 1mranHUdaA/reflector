
from sqlalchemy import Column, Integer, String, Text, DateTime, func
from .database import Base

class Scan(Base):
    __tablename__ = "scans"
    id = Column(Integer, primary_key=True)
    domain = Column(String)
    status = Column(String, default="pending")
    parameters = Column(Text)
    hidden_params = Column(Text)
    xss_urls = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
