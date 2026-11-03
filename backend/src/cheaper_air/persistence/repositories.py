from datetime import datetime
from sqlalchemy import JSON, DateTime, String, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from cheaper_air.domain.models import SearchResult


class Base(DeclarativeBase):
    pass


class SearchRow(Base):
    __tablename__ = "searches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class BookingQuoteRow(Base):
    __tablename__ = 'booking_quotes'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class SearchRepository:
    def __init__(self, url: str):
        self.engine = create_engine(url, pool_pre_ping=True)

    def initialize(self):
        Base.metadata.create_all(self.engine)

    def ready(self):
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def save(self, result: SearchResult):
        with Session(self.engine) as session, session.begin():
            session.add(SearchRow(id=str(result.search_id), created_at=result.created_at, payload=result.model_dump(mode="json")))

    def get(self, search_id: str):
        with Session(self.engine) as session:
            row = session.get(SearchRow, search_id)
            return SearchResult.model_validate(row.payload) if row else None

    def list(self, limit: int, cursor: str | None):
        with Session(self.engine) as session:
            query = select(SearchRow).order_by(SearchRow.created_at.desc(), SearchRow.id.desc())
            if cursor:
                anchor = session.get(SearchRow, cursor)
                if anchor is None:
                    raise ValueError("Unknown cursor")
                query = query.where((SearchRow.created_at < anchor.created_at) | ((SearchRow.created_at == anchor.created_at) & (SearchRow.id < anchor.id)))
            rows = list(session.scalars(query.limit(limit + 1)))
            return {"items": [r.payload for r in rows[:limit]], "next_cursor": rows[limit-1].id if len(rows) > limit else None}


    def save_quote(self, quote_id: str, payload: dict):
        with Session(self.engine) as session, session.begin():
            session.add(BookingQuoteRow(id=quote_id,payload=payload))

    def get_quote(self, quote_id: str):
        with Session(self.engine) as session:
            row=session.get(BookingQuoteRow,quote_id)
            return row.payload if row else None
