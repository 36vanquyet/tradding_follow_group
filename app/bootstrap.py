from sqlalchemy import inspect, text

from app.database import engine


def ensure_schema() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("trade_signals"):
        return

    existing = {column["name"] for column in inspector.get_columns("trade_signals")}
    required = {
        "margin_usdt": "ALTER TABLE trade_signals ADD COLUMN margin_usdt FLOAT DEFAULT 0.0",
        "leverage": "ALTER TABLE trade_signals ADD COLUMN leverage INTEGER DEFAULT 1",
        "stop_loss_pct": "ALTER TABLE trade_signals ADD COLUMN stop_loss_pct FLOAT DEFAULT 0.0",
        "estimated_sl_loss_pct": "ALTER TABLE trade_signals ADD COLUMN estimated_sl_loss_pct FLOAT DEFAULT 0.0",
    }

    with engine.begin() as conn:
        for column, sql in required.items():
            if column not in existing:
                conn.execute(text(sql))
