import logging
import random
from asyncio import TimeoutError, sleep
from typing import Coroutine, NoReturn, Sequence

from prometheus_client import start_http_server

from app.exceptions import (
    CheckBaseError,
    ClientResponseErrorParamsError,
    OrioksParseDataError,
)
from app.helpers import (
    MessageToAdminsHelper,
    MongoContextManager,
    UserHelper,
)
from app.homeworks.get_orioks_homeworks import user_homeworks_check
from app.logging import setup_logging
from app.marks.get_orioks_marks import user_marks_check
from app.models.users import UserNotifySettings, UserStatus
from app.news.get_orioks_news import (
    get_current_new_info,
    user_news_check_from_news_id,
)
from app.requests.get_orioks_requests import user_requests_check

logger = logging.getLogger(__name__)


async def _delete_users_tracking_data_in_notify_settings_off(
    user_telegram_id: int, user_notify_settings: UserNotifySettings
) -> None:
    tracking_data_collections = ("marks", "news", "homeworks", "requests")
    for collection_name in tracking_data_collections:
        if not getattr(user_notify_settings, collection_name):
            async with MongoContextManager(
                database="tracking_data", collection=collection_name
            ) as mongo:
                await mongo.delete_one({"id": user_telegram_id})


async def make_one_user_check(user_telegram_id: int) -> None:
    user_notify_settings = UserHelper.get_user_settings_by_telegram_id(
        user_telegram_id=user_telegram_id
    )
    try:
        if user_notify_settings.marks:
            await user_marks_check(user_telegram_id=user_telegram_id)
        if user_notify_settings.homeworks:
            await user_homeworks_check(user_telegram_id=user_telegram_id)
        if user_notify_settings.requests:
            await user_requests_check(user_telegram_id=user_telegram_id)
    except CheckBaseError:
        await UserHelper.increment_failed_request_count(user_telegram_id)
    except TimeoutError:
        logging.error("RPC: Сервер ОРИОКС не отвечает")
    else:
        UserHelper.reset_failed_request_count(user_telegram_id)
    #

    await _delete_users_tracking_data_in_notify_settings_off(
        user_telegram_id=user_telegram_id,
        user_notify_settings=user_notify_settings,
    )


async def make_all_users_news_check(
    tries_counter: int = 0,
) -> list[Coroutine]:
    tasks = []
    users_to_check_news = UserHelper.get_users_with_enabled_news_subscription()
    users_to_check_news = [user.user_telegram_id for user in users_to_check_news]
    if len(users_to_check_news) == 0:
        return []
    picked_user_to_check_news = random.choice(list(users_to_check_news))
    if tries_counter > 10:
        return []
    try:
        current_news = await get_current_new_info(
            user_telegram_id=picked_user_to_check_news
        )
    except OrioksParseDataError:
        await UserHelper.increment_failed_request_count(picked_user_to_check_news)
        return await make_all_users_news_check(tries_counter=tries_counter + 1)

    for user_telegram_id in users_to_check_news:
        tasks.append(
            user_news_check_from_news_id(
                user_telegram_id=user_telegram_id,
                current_news=current_news,
            )
        )
    return tasks


async def run_requests(tasks: Sequence[Coroutine]) -> None:
    logging.info("Начало обработки %s запросов", len(tasks))
    try:
        for task in tasks:
            await task
    # except asyncio.TimeoutError:
    #     logging.error("Сервер ОРИОКС не отвечает")
    # except FileNotFoundError:
    # logging.error()
    except ClientResponseErrorParamsError as exception:
        if exception.status == 504:
            logging.error(
                "Вероятно, на сервере ОРИОКС проводятся технические работы: %s",
                exception,
            )
        else:
            logging.exception("Ошибка в запросах ОРИОКС!\n %s", exception)
            await MessageToAdminsHelper.send(
                f"Ошибка в запросах ОРИОКС!\n{exception}, {exception.raw_html}"
            )

    except Exception as exception:
        logging.exception("Ошибка в запросах ОРИОКС!\n %s", exception)
        await MessageToAdminsHelper.send(
            f"Ошибка в запросах ОРИОКС!\n{repr(exception)}"
        )


async def do_checks():
    logging.info("checks loop started")

    authenticated_users = UserStatus.query.filter_by(authenticated=True)
    users_telegram_ids = set(user.user_telegram_id for user in authenticated_users)
    tasks: list[Coroutine] = await make_all_users_news_check()
    for user_telegram_id in users_telegram_ids:
        tasks.append(make_one_user_check(user_telegram_id=user_telegram_id))

    await run_requests(tasks)
    logging.info("checks loop ended")


async def endless_loop() -> NoReturn:
    while True:
        await do_checks()
        await sleep(1)


async def on_startup() -> NoReturn:
    setup_logging()
    logger.info("Starting metrics server...")
    start_http_server(port=8880)
    logger.info("Metrics server started.")

    await MessageToAdminsHelper.send("Checking запущен")
    try:
        await endless_loop()
    finally:
        await MessageToAdminsHelper.send("Checking остановлен")
