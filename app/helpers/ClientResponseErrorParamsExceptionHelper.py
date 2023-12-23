import secrets
from pathlib import Path

import msgpack

from app.exceptions import ClientResponseErrorParamsException
from app.helpers import CommonHelper, MessageToAdminsHelper
from app.queue.Producer import Producer, Priority
from message_models.models import ToAdminsMessage


class ClientResponseErrorParamsExceptionHelper:
    @staticmethod
    async def check(exception: ClientResponseErrorParamsException) -> None:
        await MessageToAdminsHelper.send(
            f'Ошибка в запросах ОРИОКС!\n{exception}, {exception.raw_html}'
        )
