from typing import cast

import msgpack

from app.queue.Producer import Priority, Producer
from message_models.models import ToAdminsMessage


class MessageToAdminsHelper:
    @staticmethod
    async def send(message: str) -> None:
        msg = ToAdminsMessage(message=message)
        serialized_data = msgpack.packb(msg.model_dump())
        serialized_data = cast(bytes, serialized_data)
        await Producer.send(
            serialized_data, queue_name="notifier", priority=Priority.HIGHEST
        )
