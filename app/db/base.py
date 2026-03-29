from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


import app.models  # noqa: E402,F401
