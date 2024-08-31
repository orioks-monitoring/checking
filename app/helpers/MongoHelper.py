import asyncio
from types import TracebackType
from typing import Any, Mapping, NoReturn, cast

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorClientSession
from pymongo.results import DeleteResult, InsertOneResult

from app.config import MONGODB_URL


class MongoHelper:
    def __init__(
        self,
        client: AsyncIOMotorClient,
        session: AsyncIOMotorClientSession,
        database: str,
        collection: str,
    ) -> None:
        self.client = client
        self.session = session
        self.database = self.client.get_database(database)
        self.collection = self.database.get_collection(collection)

    async def insert_one(self, document: Mapping[str, Any]) -> InsertOneResult:
        result = await self.collection.insert_one(document, session=self.session)
        return cast(InsertOneResult, result)

    async def find_many(
        self, filter_by_dict: Mapping[str, Any], *, length: int | None = None
    ) -> list[dict[str, Any]]:
        cursor = self.collection.find(filter_by_dict, session=self.session)
        return await cursor.to_list(length=length)

    async def find_one(
        self, filter_by_dict: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        return await self.collection.find_one(filter_by_dict, session=self.session)

    async def delete_one(self, filter_by_dict: Mapping[str, Any]) -> DeleteResult:
        return await self.collection.delete_one(filter_by_dict, session=self.session)

    async def update_one(
        self, filter_by_dict: Mapping[str, Any], update_by_dict: Mapping[str, Any]
    ) -> None:
        await self.collection.update_one(
            filter_by_dict, {"$set": update_by_dict}, session=self.session
        )


class MongoContextManager:
    def __init__(
        self,
        database: str,
        collection: str,
        in_transaction: bool = True,
        url: str = MONGODB_URL,
    ) -> None:
        self.database = database
        self.collection = collection
        self.url = url
        self.client = None
        self.session = None
        self.in_transaction = in_transaction

    async def __aenter__(self) -> MongoHelper:
        self.client = AsyncIOMotorClient(self.url)
        self.session = await self.client.start_session()

        if self.in_transaction:
            self._transaction_context = self.session.start_transaction()
            await self._transaction_context.__aenter__()

        return MongoHelper(self.client, self.session, self.database, self.collection)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        assert self.session is not None

        if self.in_transaction:
            await self._transaction_context.__aexit__(exc_type, exc_val, exc_tb)

        await self.session.end_session()
        self.client.close()

    def __enter__(self) -> NoReturn:
        raise NotImplementedError(
            "Use 'async with' instead of 'with' for asynchronous context management"
        )


if __name__ == "__main__":

    async def main():
        async with MongoContextManager("pymongo_test", "posts") as mongo:
            # await mongo.delete_one({})

            result = await mongo.find_many({})
            print(f"find: {result=}")

            # result = await mongo.insert_one({"test": "hello - 1"})
            # print(f"insert: {result=}")
            # raise ZeroDivisionError

    asyncio.run(main())
