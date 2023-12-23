import asyncio
from typing import NoReturn

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorClientSession
from pymongo.results import InsertOneResult, DeleteResult

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

    async def insert_one(self, document: dict) -> InsertOneResult:
        result: InsertOneResult = await self.collection.insert_one(document)
        return result

    async def find_many(
        self, filter_by_dict: dict, *, length: int | None = None
    ) -> list[dict]:
        cursor = self.collection.find(filter_by_dict)
        return await cursor.to_list(length=length)

    async def find_one(self, filter_by_dict: dict) -> dict | None:
        return await self.collection.find_one(filter_by_dict)

    async def delete_one(self, filter_by_dict: dict) -> DeleteResult:
        return await self.collection.delete_one(filter_by_dict)

    async def update_one(self, filter_by_dict: dict, update_by_dict: dict) -> None:
        await self.collection.update_one(filter_by_dict, {"$set": update_by_dict})


class MongoContextManager:
    def __init__(
        self,
        database: str,
        collection: str,
        url: str = MONGODB_URL,
    ) -> None:
        self.database = database
        self.collection = collection
        self.url = url
        self.client = None
        self.session = None

    async def __aenter__(self) -> MongoHelper:
        self.client = AsyncIOMotorClient(self.url)
        self.session = await self.client.start_session()
        return MongoHelper(self.client, self.session, self.database, self.collection)

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.session.end_session()
        self.client.close()

    def __enter__(self) -> NoReturn:
        raise NotImplementedError(
            "Use 'async with' instead of 'with' for asynchronous context management"
        )


if __name__ == "__main__":

    async def main():
        async with MongoContextManager("pymongo_test", "posts") as mongo:
            result = await mongo.insert_one({"some": "data"})
            print(f"insert: {result=}")

            result = await mongo.find_many({})
            print(f"find: {result=}")

    asyncio.run(main())
