from aiogram import F, Router
from aiogram.types import Message

from app.services.lead_service import LeadService

router = Router(name="monitoring")


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_monitored_message(message: Message, lead_service: LeadService) -> None:
    await lead_service.process_message(message)
