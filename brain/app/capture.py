"""Frictionless capture — file a one-liner to the DB. Reused by /capture and Telegram."""
from app.db.models import Capture
from app.db.session import get_session


async def create_capture(text: str, source: str = "api") -> int:
    """Store a captured note and return its id."""
    async with get_session() as session:
        capture = Capture(text=text.strip(), source=source)
        session.add(capture)
        await session.commit()
        await session.refresh(capture)
        return capture.id
