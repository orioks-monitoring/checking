import asyncio

from aio_pika import connect_robust
from aio_pika.patterns import RPC

from app.config import RABBIT_MQ_URL


class RPCQueueClient:
    """
    RPC client for queue. It is used to send RPC requests to queue.

    Usage:
        async with RPCQueueClient() as rpc:
            result = await rpc.call("make_orioks_request", kwargs=dict(
                task_info=OrioksRequestMessage(
                    user_telegram_id=1522960798,
                    event_type="marks",
                )
            ))
            print(result)
    """

    def __init__(self, timeout=10):
        self.timeout = timeout
        self.connection = None
        self.channel = None
        self.rpc = None

    async def __aenter__(self):
        self.connection = await connect_robust(
            RABBIT_MQ_URL,
            client_properties={"connection_name": "caller"},
        )

        await self.connection.__aenter__()

        self.channel = await self.connection.channel()
        self.rpc = await RPC.create(self.channel)

        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.connection.__aexit__(exc_type, exc, tb)

    async def call(self, method_name: str, kwargs: dict):
        result = await asyncio.wait_for(
            self.rpc.call(method_name, kwargs=kwargs), timeout=self.timeout
        )
        return result
