from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Game(Base):
    __tablename__ = "games"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    opponent = Column(String(100), default="")
    game_date = Column(DateTime, default=datetime.utcnow)
    video_path = Column(String(500))
    home_players = Column(JSON, default=list)      # ["小宇", "小杰"]
    created_at = Column(DateTime, default=datetime.utcnow)

    possessions = relationship("Possession", back_populates="game",
                               cascade="all, delete-orphan",
                               order_by="Possession.start_time")


class Possession(Base):
    __tablename__ = "possessions"

    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)

    title = Column(String(200), default="")
    start_time = Column(Float, nullable=False)   # seconds
    end_time = Column(Float, nullable=False)     # seconds
    team = Column(String(50), default="我方")    # 我方 / 对方
    phase = Column(String(50), default="offense")
    # offense / defense / transition_offense / transition_defense
    result = Column(String(100), default="")
    players = Column(JSON, default=list)         # ["小宇", "小杰"]
    description = Column(Text, default="")       # coach notes

    analysis = Column(JSON)                      # AI result
    analysis_status = Column(String(20), default="pending")
    # pending / analyzing / done / error
    analysis_error = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)

    game = relationship("Game", back_populates="possessions")
