from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.bootstrap import ensure_schema
from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.services.order_manager import OrderManager
from app.services.repository import Repository
from app.services.telegram_message_store import TelegramMessageStore
from app.services.telegram_notifier import TelegramNotifier
from app.services.telegram_runtime import TelegramRuntime

settings = get_settings()
ensure_schema()
Base.metadata.create_all(bind=engine)
templates = Jinja2Templates(directory="templates")

notifier = TelegramNotifier(settings)
message_store = TelegramMessageStore(settings.telegram_message_store_path)
order_manager = OrderManager(settings, notifier, message_store)
telegram_runtime = TelegramRuntime(settings, order_manager, notifier)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await telegram_runtime.start()
    yield
    await telegram_runtime.stop()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    repo = Repository(db)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "summary": repo.summary(),
            "signals": repo.list_signals(20),
            "orders": repo.list_orders(20),
            "message_summary": message_store.summary(),
            "messages": message_store.list_messages(50),
            "web_base_url": settings.web_base_url,
        },
    )


@app.get("/api/summary", response_class=JSONResponse)
def api_summary(db: Session = Depends(get_db)):
    return Repository(db).summary()


@app.get("/api/signals", response_class=JSONResponse)
def api_signals(db: Session = Depends(get_db)):
    signals = Repository(db).list_signals(100)
    return [
        {
            "id": item.id,
            "symbol": item.symbol,
            "side": item.side,
            "entry_price": item.entry_price,
            "stop_loss": item.stop_loss,
            "tp1": item.tp1,
            "tp2": item.tp2,
            "quantity": item.quantity,
            "margin_usdt": item.margin_usdt,
            "leverage": item.leverage,
            "stop_loss_pct": item.stop_loss_pct,
            "estimated_sl_loss_pct": item.estimated_sl_loss_pct,
            "status": item.status,
            "ai_approved": item.ai_approved,
            "ai_confidence": item.ai_confidence,
            "ai_reason": item.ai_reason,
            "created_at": item.created_at.isoformat(),
        }
        for item in signals
    ]


@app.get("/api/orders", response_class=JSONResponse)
def api_orders(db: Session = Depends(get_db)):
    orders = Repository(db).list_orders(100)
    return [
        {
            "id": item.id,
            "signal_id": item.signal_id,
            "role": item.role,
            "side": item.side,
            "qty": item.qty,
            "price": item.price,
            "status": item.status,
            "bybit_order_id": item.bybit_order_id,
            "created_at": item.created_at.isoformat(),
        }
        for item in orders
    ]


@app.get("/api/messages", response_class=JSONResponse)
def api_messages():
    return {
        "summary": message_store.summary(),
        "messages": message_store.list_messages(100),
    }


@app.get("/health", response_class=JSONResponse)
def health():
    return {"status": "ok"}
