from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet
import aiohttp
from dotenv import load_dotenv

if TYPE_CHECKING:
    from sqlalchemy.orm.scoping import ScopedSession

load_dotenv()  # take environment variables from .env


RABBIT_MQ_URL = os.getenv("RABBIT_MQ_URL", "amqp://guest:guest@localhost/")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///../bot/database.sqlite3")
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://admin:admin@localhost:27017")

BASEDIR = os.path.dirname(os.path.abspath(__file__))
STUDENT_FILE_JSON_MASK = '{id}.json'
REQUESTS_TIMEOUT = aiohttp.ClientTimeout(total=30)
ORIOKS_REQUESTS_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
    'Accept-Encoding': 'gzip, deflate',
    'Accept-Language': 'ru-RU,ru;q=0.9',
    'User-Agent': 'orioks_monitoring/2.0 (Linux; aiohttp)',
}

ORIOKS_PAGE_URLS = {
    'login': 'https://orioks.miet.ru/user/login',
    'masks': {
        'news': 'https://orioks.miet.ru/main/view-news?id={id}',
        'homeworks': 'https://orioks.miet.ru/student/homework/view?id_thread={id}',
        'requests': {
            'questionnaire': 'https://orioks.miet.ru/request/questionnaire/view?id_thread={id}',  # not sure
            'doc': 'https://orioks.miet.ru/request/doc/view?id_thread={id}',  # not sure
            'reference': 'https://orioks.miet.ru/request/reference/view?id_thread={id}',
        },
    },
    'notify': {
        'marks': 'https://orioks.miet.ru/student/student',
        'news': 'https://orioks.miet.ru',
        'homeworks': 'https://orioks.miet.ru/student/homework/list',
        'requests': {
            'questionnaire': 'https://orioks.miet.ru/request/questionnaire/list?AnketaTreadForm[status]=1,2,4,6,3,5,7&AnketaTreadForm[accept]=-1',
            'doc': 'https://orioks.miet.ru/request/doc/list?DocThreadForm[status]=1,2,4,6,3,5,7&DocThreadForm[type]=0',
            'reference': 'https://orioks.miet.ru/request/reference/list?ReferenceThreadForm[status]=1,2,4,6,3,5,7',
        },
    },
}

ORIOKS_SECONDS_BETWEEN_REQUESTS = 1.5
ORIOKS_REQUESTS_SEMAPHORE_VALUE = 1
ORIOKS_LOGIN_QUEUE_SEMAPHORE_VALUE = 1
ORIOKS_MAX_FAILED_REQUESTS = 50


def initialize_database() -> ScopedSession:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import scoped_session, sessionmaker

    engine = create_engine(DATABASE_URL)
    return scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s - %(module)s - %(funcName)s - %(lineno)d: %(message)s",
    datefmt='%H:%M:%S %d.%m.%Y',
)

db_session = initialize_database()

FERNET_KEY_FOR_COOKIES = bytes(
    os.getenv("FERNET_KEY_FOR_COOKIES", "my32lengthsupersecretnooneknows1"), "utf-8"
)
FERNET_CIPHER_SUITE = Fernet(FERNET_KEY_FOR_COOKIES)


LOGIN_LOGOUT_SERVICE_TOKEN = os.getenv("LOGIN_LOGOUT_SERVICE_TOKEN", "SecretToken")
LOGIN_LOGOUT_SERVICE_HEADER_NAME = os.getenv(
    "LOGIN_LOGOUT_SERVICE_HEADER_NAME", "X-Auth-Token"
)
LOGIN_LOGOUT_SERVICE_URL_FOR_LOGOUT = os.getenv(
    'LOGIN_LOGOUT_SERVICE_URL_FOR_LOGOUT',
    "http://127.0.0.1:8000/user/{user_telegram_id}/logout",
)
assert (
    "{user_telegram_id}" in LOGIN_LOGOUT_SERVICE_URL_FOR_LOGOUT
), "LOGIN_LOGOUT_SERVICE_URL_FOR_LOGOUT must contain {user_telegram_id}"
