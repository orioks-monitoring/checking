import logging
import os

import re

import msgpack
from aiohttp import ClientResponseError
from bs4 import BeautifulSoup

from app.config import ORIOKS_PAGE_URLS, BASEDIR, STUDENT_FILE_JSON_MASK
from app.exceptions import OrioksParseDataException
from app.helpers import (
    RequestHelper,
    CommonHelper,
    MongoContextManager,
    MessageToAdminsHelper,
)
from app.queue.Producer import Producer
import aiogram.utils.markdown as md
from typing import NamedTuple

from app.queue.Producer import Priority
from message_models.models import NewChangeMessage, ToAdminsMessage


class NewsObject(NamedTuple):
    headline_news: str
    url: str
    id: int


class ActualNews(NamedTuple):
    latest_id: int
    student_actual_news: set[int]
    last_new: NewsObject


def _get_student_actual_news(raw_html: str) -> set[int]:
    def __get_int_from_line(news_line: str) -> int:
        return int(re.findall(r'\d+$', news_line)[0])

    bs_content = BeautifulSoup(raw_html, "html.parser")
    news_raw = bs_content.find(id='news')
    if news_raw is None:
        raise OrioksParseDataException
    news_id = set(
        __get_int_from_line(x['href'])
        for x in news_raw.select('#news tr:not(:first-child) a')
    )
    return news_id


async def get_news_object_by_news_id(news_id: int, user_telegram_id: int) -> NewsObject:
    raw_html = await RequestHelper.get_request(
        event_type='news-individual',
        user_telegram_id=user_telegram_id,
        news_id=news_id,
    )
    bs_content = BeautifulSoup(raw_html, "html.parser")
    well_raw = bs_content.find_all('div', {'class': 'well'})[0]
    return NewsObject(
        headline_news=_find_in_str_with_beginning_and_ending(
            string_to_find=well_raw.text,
            beginning='Заголовок:',
            ending='Тело новости:',
        ),
        url=ORIOKS_PAGE_URLS['masks']['news'].format(id=news_id),
        id=news_id,
    )


async def get_orioks_news(user_telegram_id: int) -> ActualNews:
    raw_html = await RequestHelper.get_request(
        event_type='news', user_telegram_id=user_telegram_id
    )
    student_actual_news = _get_student_actual_news(raw_html)
    latest_id = max(student_actual_news)
    return ActualNews(
        latest_id=latest_id,
        student_actual_news=student_actual_news,
        last_new=await get_news_object_by_news_id(
            news_id=latest_id,
            user_telegram_id=user_telegram_id,
        ),
    )


def _find_in_str_with_beginning_and_ending(
    string_to_find: str, beginning: str, ending: str
) -> str:
    regex_result = re.findall(rf'{beginning}[\S\s]+{ending}', string_to_find)[0]
    return str(regex_result.replace(beginning, '').replace(ending, '').strip())


def transform_news_to_msg(news_obj: NewsObject) -> str:
    return str(
        md.text(
            md.text(md.text('📰'), md.hbold(news_obj.headline_news), sep=' '),
            md.text(),
            md.text(
                md.text('Опубликована новость, подробности по ссылке:'),
                md.text(news_obj.url),
                sep=' ',
            ),
            sep='\n',
        )
    )


async def get_current_new_info(
    user_telegram_id: int,
) -> ActualNews:
    try:
        last_news_ids: ActualNews = await get_orioks_news(user_telegram_id)
    except OrioksParseDataException as exception:
        logging.info(
            '(NEWS) [%s] exception: utils.exceptions.OrioksCantParseData',
            user_telegram_id,
        )
        raise exception
    except ClientResponseError as exception:
        if 400 <= exception.status < 500:
            logging.info(
                '(NEWS) [%s] exception: aiohttp.ClientResponseError status in [400, 500). Raising OrioksCantParseData',
                user_telegram_id,
            )
            raise OrioksParseDataException from exception
        raise exception

    return last_news_ids


async def user_news_check_from_news_id(
    user_telegram_id: int,
    current_news: ActualNews,
) -> None:
    user_filter = {'id': user_telegram_id}
    mongo_context = MongoContextManager(
        database='tracking_data',
        collection='news',
    )

    async with mongo_context as mongo:
        existing_document = await mongo.find_one(user_filter)
        if existing_document is None:
            await mongo.insert_one(
                {'id': user_telegram_id, 'last_id': current_news.latest_id}
            )
            return None
    old_json = existing_document
    if current_news.latest_id == old_json['last_id']:
        return None
    if old_json['last_id'] > current_news.latest_id:
        await MessageToAdminsHelper.send(
            f'[{user_telegram_id}] - old_json["last_id"] > last_news_id["last_id"]'
        )
        raise Exception(
            f'[{user_telegram_id}] - old_json["last_id"] > last_news_id["last_id"]'
        )
    difference = current_news.latest_id - old_json['last_id']
    for news_id in range(old_json['last_id'] + 1, old_json['last_id'] + difference + 1):
        if news_id not in current_news.student_actual_news:
            logging.info(
                'Новость с id %s существует, но не показывается в таблице на главной странице',
                news_id,
            )
            continue
        if news_id == current_news.latest_id:
            news_obj = current_news.last_new
        else:
            try:
                news_obj = await get_news_object_by_news_id(
                    news_id=news_id, user_telegram_id=user_telegram_id
                )
            except IndexError:
                continue  # id новостей могут идти не по порядку, поэтому надо игнорировать IndexError

        msg = NewChangeMessage(
            title_text=news_obj.headline_news,
            side_text='Опубликована новость',
            url=news_obj.url,
            caption=transform_news_to_msg(news_obj=news_obj),
            user_telegram_id=user_telegram_id,
        )
        serialized_data = msgpack.packb(msg.model_dump())
        await Producer.send(serialized_data, queue_name="notifier")

        async with mongo_context as mongo:
            await mongo.update_one(user_filter, {'last_id': news_id})
    async with mongo_context as mongo:
        await mongo.update_one(user_filter, {'last_id': current_news.latest_id})
