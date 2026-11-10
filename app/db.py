from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from app.config import settings


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Anime(Base):
    __tablename__ = 'anime'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Jellyfin stable ID
    title: Mapped[str] = mapped_column(String(500))
    source_title: Mapped[str] = mapped_column(String(500), default='')
    overview: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    premiere: Mapped[str | None] = mapped_column(String(32))
    anidb_id: Mapped[int | None] = mapped_column(Integer, index=True)
    anilist_id: Mapped[int | None] = mapped_column(Integer, index=True)
    provider_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    match_status: Mapped[str] = mapped_column(String(30), default='unmatched')
    match_confidence: Mapped[float | None] = mapped_column(Float)
    match_candidates: Mapped[list] = mapped_column(JSON, default=list)
    total_episodes: Mapped[int | None] = mapped_column(Integer)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    dubbed_count: Mapped[int] = mapped_column(Integer, default=0)
    audio_languages: Mapped[list] = mapped_column(JSON, default=list)
    subtitle_languages: Mapped[list] = mapped_column(JSON, default=list)
    release_groups: Mapped[list] = mapped_column(JSON, default=list)
    studios: Mapped[list] = mapped_column(JSON, default=list)
    relations: Mapped[list] = mapped_column(JSON, default=list)
    cover_url: Mapped[str | None] = mapped_column(Text)
    personal_rating: Mapped[float | None] = mapped_column(Float)
    personal_review: Mapped[str] = mapped_column(Text, default='')
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    episodes: Mapped[list['Episode']] = relationship(back_populates='anime', cascade='all,delete-orphan')


class Episode(Base):
    __tablename__ = 'episodes'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    anime_id: Mapped[str] = mapped_column(ForeignKey('anime.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(500), default='')
    season: Mapped[int | None] = mapped_column(Integer)
    number: Mapped[int | None] = mapped_column(Integer)
    path: Mapped[str | None] = mapped_column(Text)
    audio_languages: Mapped[list] = mapped_column(JSON, default=list)
    subtitle_languages: Mapped[list] = mapped_column(JSON, default=list)
    release_group: Mapped[str | None] = mapped_column(String(200))
    anime: Mapped[Anime] = relationship(back_populates='episodes')


class Sidecar(Base):
    __tablename__ = 'sidecars'
    relative_path: Mapped[str] = mapped_column(Text, primary_key=True)
    release: Mapped[str] = mapped_column(String(500), index=True)
    language_hint: Mapped[str | None] = mapped_column(String(30))
    episode_hint: Mapped[int | None] = mapped_column(Integer)
    extension: Mapped[str] = mapped_column(String(20))
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class State(Base):
    __tablename__ = 'state'
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default='')


engine = create_engine(settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as session:
        yield session


def put_state(db, key, value):
    entry = db.get(State, key)
    if entry is None:
        db.add(State(key=key, value=str(value)))
    else:
        entry.value = str(value)


def read_state(db, key, default=''):
    entry = db.get(State, key)
    return entry.value if entry else default
