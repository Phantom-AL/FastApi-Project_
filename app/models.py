from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Date, Numeric, func

from app.database import Base


class Users(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    login = Column(String, unique=True)
    registration_date = Column(DateTime, default=func.now())


class Credits(Base):
    __tablename__ = "credits"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    issuance_date = Column(DateTime, index=True)
    return_date = Column(DateTime)
    actual_return_date = Column(DateTime)
    body = Column(Numeric(10, 2))
    percent = Column(Numeric(10, 2))


class Dictionary(Base):
    __tablename__ = "dictionaries"

    id = Column(Integer, primary_key=True)
    name = Column(String, index=True)


class Payments(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    credit_id = Column(Integer, ForeignKey('credits.id'))
    payment_date = Column(DateTime, index=True)
    type_id = Column(Integer, ForeignKey('dictionaries.id'))
    sum = Column(Numeric(10, 2))


class Plans(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True, index=True)
    period = Column(Date, index=True)
    sum = Column(Numeric(10, 2))
    category_id = Column(Integer, ForeignKey('dictionaries.id'), index=True)
