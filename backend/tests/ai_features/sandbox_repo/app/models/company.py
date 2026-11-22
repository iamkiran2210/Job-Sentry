from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class Company(BaseModel):
    __tablename__ = "companies"
    name: Mapped[str] = mapped_column(String(255), nullable=False)
