from sqlalchemy import Column, Integer, String, Text, DateTime, func, UniqueConstraint
from db import Base

class Scan(Base):
    __tablename__ = "scans"

    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String(255), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="pending")
    parameters = Column(Text)        # names from parameter.sh
    hidden_params = Column(Text)     # names from hidden.py
    xss_urls = Column(Text)          # reflected URLs from xsslection.py
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("domain", name="uq_scan_domain_once"),
    )
