import os
import shutil
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from .models import Base, Game, Possession
from .services.video import extract_frames_for_range, get_video_duration, frames_to_base64
from .services.ai import analyze_possession

DATA_DIR = os.environ.get("BASKETBALL_DATA_DIR", os.path.expanduser("~/.basketball_coach_data"))
DB_PATH = os.path.join(DATA_DIR, "db.sqlite3")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    # migrate: add home_players column if missing (safe no-op on re-runs)
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE games ADD COLUMN home_players TEXT DEFAULT '[]'"))
            conn.commit()
        except Exception:
            pass
    yield


app = FastAPI(title="篮球回合分析", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Pages ────────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/game/{game_id}")
def game_page(game_id: int):
    return FileResponse(str(STATIC_DIR / "game.html"))


# ── Video streaming ───────────────────────────────────────────────────────────

@app.get("/api/games/{game_id}/video")
def stream_video(game_id: int):
    db = SessionLocal()
    try:
        game = db.query(Game).filter(Game.id == game_id).first()
        if not game or not game.video_path or not os.path.exists(game.video_path):
            raise HTTPException(404, "视频不存在")
        return FileResponse(game.video_path, media_type="video/mp4")
    finally:
        db.close()


# ── Games ────────────────────────────────────────────────────────────────────

class GameCreate(BaseModel):
    title: str
    opponent: Optional[str] = ""
    game_date: Optional[str] = None


class RosterUpdate(BaseModel):
    players: list[str]


@app.get("/api/games")
def list_games():
    db = SessionLocal()
    try:
        games = db.query(Game).order_by(Game.created_at.desc()).all()
        return [_game_summary(g) for g in games]
    finally:
        db.close()


@app.post("/api/games")
def create_game(data: GameCreate):
    db = SessionLocal()
    try:
        gdate = datetime.utcnow()
        if data.game_date:
            try:
                gdate = datetime.fromisoformat(data.game_date)
            except Exception:
                pass
        game = Game(title=data.title, opponent=data.opponent or "", game_date=gdate)
        db.add(game)
        db.commit()
        db.refresh(game)
        return _game_summary(game)
    finally:
        db.close()


@app.get("/api/games/{game_id}")
def get_game(game_id: int):
    db = SessionLocal()
    try:
        game = db.query(Game).filter(Game.id == game_id).first()
        if not game:
            raise HTTPException(404, "比赛不存在")
        result = _game_summary(game)
        result["possessions"] = [_possession_out(p) for p in game.possessions]
        return result
    finally:
        db.close()


@app.put("/api/games/{game_id}/roster")
def update_roster(game_id: int, data: RosterUpdate):
    db = SessionLocal()
    try:
        game = db.query(Game).filter(Game.id == game_id).first()
        if not game:
            raise HTTPException(404, "比赛不存在")
        game.home_players = data.players
        db.commit()
        return {"players": game.home_players}
    finally:
        db.close()


@app.post("/api/games/{game_id}/video")
async def upload_video(game_id: int, file: UploadFile = File(...)):
    db = SessionLocal()
    try:
        game = db.query(Game).filter(Game.id == game_id).first()
        if not game:
            raise HTTPException(404, "比赛不存在")
        video_dir = os.path.join(UPLOADS_DIR, f"game_{game_id}")
        os.makedirs(video_dir, exist_ok=True)
        video_path = os.path.join(video_dir, "video.mp4")
        content = await file.read()
        with open(video_path, "wb") as f:
            f.write(content)
        game.video_path = video_path
        db.commit()
        duration = get_video_duration(video_path)
        return {"status": "ok", "duration": duration}
    finally:
        db.close()


# ── Possessions ───────────────────────────────────────────────────────────────

class PossessionCreate(BaseModel):
    start_time: float
    end_time: float
    players: list[str] = []
    description: str = ""
    # AI-determined fields default to empty; AI fills them in after analysis
    title: str = ""
    team: str = "我方"
    phase: str = ""
    result: str = ""


class PossessionUpdate(BaseModel):
    title: Optional[str] = None
    team: Optional[str] = None
    phase: Optional[str] = None
    result: Optional[str] = None
    players: Optional[list[str]] = None
    description: Optional[str] = None


@app.get("/api/games/{game_id}/possessions")
def list_possessions(game_id: int):
    db = SessionLocal()
    try:
        game = db.query(Game).filter(Game.id == game_id).first()
        if not game:
            raise HTTPException(404, "比赛不存在")
        return [_possession_out(p) for p in game.possessions]
    finally:
        db.close()


@app.post("/api/games/{game_id}/possessions")
def create_possession(game_id: int, data: PossessionCreate):
    db = SessionLocal()
    try:
        game = db.query(Game).filter(Game.id == game_id).first()
        if not game:
            raise HTTPException(404, "比赛不存在")
        if data.end_time <= data.start_time:
            raise HTTPException(400, "结束时间必须大于开始时间")
        p = Possession(
            game_id=game_id,
            title=data.title,
            start_time=data.start_time,
            end_time=data.end_time,
            team=data.team,
            phase=data.phase or "offense",
            result=data.result,
            players=data.players,
            description=data.description,
            analysis_status="pending",
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        return _possession_out(p)
    finally:
        db.close()


@app.put("/api/games/{game_id}/possessions/{possession_id}")
def update_possession(game_id: int, possession_id: int, data: PossessionUpdate):
    db = SessionLocal()
    try:
        p = db.query(Possession).filter(
            Possession.id == possession_id, Possession.game_id == game_id
        ).first()
        if not p:
            raise HTTPException(404, "回合不存在")
        for field, val in data.model_dump(exclude_none=True).items():
            setattr(p, field, val)
        db.commit()
        db.refresh(p)
        return _possession_out(p)
    finally:
        db.close()


@app.delete("/api/games/{game_id}/possessions/{possession_id}")
def delete_possession(game_id: int, possession_id: int):
    db = SessionLocal()
    try:
        p = db.query(Possession).filter(
            Possession.id == possession_id, Possession.game_id == game_id
        ).first()
        if not p:
            raise HTTPException(404, "回合不存在")
        frames_dir = os.path.join(UPLOADS_DIR, f"game_{game_id}", f"possession_{possession_id}")
        if os.path.exists(frames_dir):
            shutil.rmtree(frames_dir, ignore_errors=True)
        db.delete(p)
        db.commit()
        return {"status": "deleted"}
    finally:
        db.close()


# ── Possession Analysis ───────────────────────────────────────────────────────

def _do_analyze_possession(possession_id: int):
    db = SessionLocal()
    try:
        p = db.query(Possession).filter(Possession.id == possession_id).first()
        if not p:
            return
        game = p.game
        if not game.video_path or not os.path.exists(game.video_path):
            p.analysis_status = "error"
            p.analysis_error = "视频文件不存在"
            db.commit()
            return

        frames_dir = os.path.join(UPLOADS_DIR, f"game_{game.id}", f"possession_{possession_id}")
        frames = extract_frames_for_range(
            game.video_path, p.start_time, p.end_time, frames_dir, fps=1.0
        )
        b64_frames = frames_to_base64(frames)

        result = analyze_possession(
            frame_b64_list=b64_frames,
            phase=p.phase,
            team=p.team,
            players=list(p.players or []),
            description=p.description or "",
            start_time=p.start_time,
            end_time=p.end_time,
        )

        # Apply AI-determined metadata back to the possession
        if result.get("auto_title"):
            p.title = result["auto_title"]
        if result.get("phase") and result["phase"] in (
            "offense", "defense", "transition_offense", "transition_defense"
        ):
            p.phase = result["phase"]
        if result.get("result"):
            p.result = result["result"]

        p.analysis = result
        p.analysis_status = "done"
        p.analysis_error = None
        db.commit()

    except Exception as e:
        try:
            p = db.query(Possession).filter(Possession.id == possession_id).first()
            if p:
                p.analysis_status = "error"
                p.analysis_error = str(e)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@app.post("/api/games/{game_id}/possessions/{possession_id}/analyze")
def trigger_possession_analysis(game_id: int, possession_id: int,
                                 background_tasks: BackgroundTasks):
    db = SessionLocal()
    try:
        p = db.query(Possession).filter(
            Possession.id == possession_id, Possession.game_id == game_id
        ).first()
        if not p:
            raise HTTPException(404, "回合不存在")
        if p.analysis_status == "analyzing":
            raise HTTPException(400, "分析进行中")
        p.analysis_status = "analyzing"
        p.analysis_error = None
        db.commit()
        background_tasks.add_task(_do_analyze_possession, possession_id)
        return {"status": "started"}
    finally:
        db.close()


@app.get("/api/games/{game_id}/possessions/{possession_id}")
def get_possession(game_id: int, possession_id: int):
    db = SessionLocal()
    try:
        p = db.query(Possession).filter(
            Possession.id == possession_id, Possession.game_id == game_id
        ).first()
        if not p:
            raise HTTPException(404, "回合不存在")
        return _possession_out(p)
    finally:
        db.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _game_summary(g: Game) -> dict:
    possession_count = len(g.possessions) if g.possessions is not None else 0
    return {
        "id": g.id,
        "title": g.title,
        "opponent": g.opponent,
        "game_date": g.game_date.isoformat() if g.game_date else None,
        "has_video": bool(g.video_path),
        "home_players": g.home_players or [],
        "possession_count": possession_count,
        "created_at": g.created_at.isoformat() if g.created_at else None,
    }


def _possession_out(p: Possession) -> dict:
    return {
        "id": p.id,
        "game_id": p.game_id,
        "title": p.title,
        "start_time": p.start_time,
        "end_time": p.end_time,
        "team": p.team,
        "phase": p.phase,
        "result": p.result,
        "players": p.players or [],
        "description": p.description,
        "analysis": p.analysis,
        "analysis_status": p.analysis_status,
        "analysis_error": p.analysis_error,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def start():
    import uvicorn
    host = os.environ.get("BASKETBALL_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("BASKETBALL_PORT", "8080")))
    uvicorn.run("basketball_coach.main:app", host=host, port=port, reload=False)
