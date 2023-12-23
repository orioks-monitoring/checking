import asyncio
import logging

from aiohttp import ClientResponse
from aiohttp.typedefs import StrOrURL

from app.config import ORIOKS_SECONDS_BETWEEN_REQUESTS, ORIOKS_REQUESTS_SEMAPHORE_VALUE
from app.exceptions import ClientResponseErrorParamsException
from app.helpers import AdminHelper
from app.queue.rpc import RPCQueueClient
from message_models.models import OrioksRequestMessage


class RequestHelper:
    @staticmethod
    async def my_raise_for_status(
        response: ClientResponse,
        user_telegram_id: int | None = None,
        raw_html: str | None = None,
    ) -> None:
        if response.status >= 400:
            raise ClientResponseErrorParamsException(
                response.request_info,
                response.history,
                user_telegram_id=user_telegram_id,
                raw_html=raw_html if response.status >= 500 else None,
                status=response.status,
                message=response.reason,
                headers=response.headers,
            )

    _sem = asyncio.Semaphore(ORIOKS_REQUESTS_SEMAPHORE_VALUE)

    @staticmethod
    async def get_request(event_type: str, user_telegram_id: int, **kwargs) -> str:
        async with RPCQueueClient(timeout=10) as rpc_client:
            # TODO: is db.user_status.get_user_orioks_authenticated_status(user_telegram_id=user_telegram_id)
            #       else safe delete all user's file
            #       Обработать случай, когда пользователь к моменту достижения своей очереди разлогинился
            # TODO: is db.notify_settings.get_user_notify_settings_to_dict(user_telegram_id=user_telegram_id)
            #       else safe delete non-enabled categories
            logging.info("[%s] RPC call: %s", user_telegram_id, event_type)

            result = await rpc_client.call(
                "make_orioks_request",
                kwargs=dict(
                    task_info=OrioksRequestMessage(
                        user_telegram_id=user_telegram_id,
                        event_type=event_type,
                        **kwargs,
                    )
                ),
            )
            AdminHelper.increase_scheduled_requests()
            return result
