from datetime import datetime
from zoneinfo import ZoneInfo
import msgpack

from app.queue.Producer import Priority, Producer
from message_models.models import ToAdminsMessage


def _get_current_time() -> str:
    return datetime.now(ZoneInfo("Europe/Moscow")).strftime('%d.%m.%Y %H:%M:%S')


class MessageToAdminsHelper:
    @staticmethod
    async def send(message: str) -> None:
        msg = ToAdminsMessage(message=f"{message}\n<i>({_get_current_time()})</i>")
        serialized_data = msgpack.packb(msg.model_dump())
        await Producer.send(
            serialized_data, queue_name="notifier", priority=Priority.HIGHEST
        )
