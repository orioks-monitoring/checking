import logging
import os

import re

import msgpack
from aiohttp import ClientResponseError
from bs4 import BeautifulSoup

from app.config import ORIOKS_PAGE_URLS, BASEDIR, STUDENT_FILE_JSON_MASK
from app.exceptions import OrioksParseDataException, FileCompareException
from app.helpers import (
    CommonHelper,
    RequestHelper,
    MongoContextManager,
)
from app.queue.Producer import Producer
import aiogram.utils.markdown as md

from message_models.models import HomeworkChangeMessage


def _orioks_parse_homeworks(raw_html: str) -> dict[str, dict]:
    bs_content = BeautifulSoup(raw_html, "html.parser")
    if bs_content.select_one('.table.table-condensed.table-thread') is None:
        raise OrioksParseDataException
    table_raw = bs_content.select(
        '.table.table-condensed.table-thread tr:not(:first-child)'
    )
    homeworks = dict()
    for tr in table_raw:
        _thread_id = str(
            re.findall(r'\d+$', tr.find_all('td')[2].select_one('a')['href'])[0]
        )
        homeworks[_thread_id] = {
            'status': tr.find_all('td')[1].text,
            'new_messages': int(tr.find_all('td')[8].select_one('b').text),
            'about': {
                'discipline': tr.find_all('td')[3].text,
                'task': tr.find_all('td')[4].text,
                'url': ORIOKS_PAGE_URLS['masks']['homeworks'].format(id=_thread_id),
            },
        }
    return homeworks


async def get_orioks_homeworks(user_telegram_id: int) -> dict[str, dict]:
    raw_html = await RequestHelper.get_request(
        event_type='homeworks', user_telegram_id=user_telegram_id
    )
    return _orioks_parse_homeworks(raw_html)


async def get_homeworks_to_msg(diffs: list) -> str:
    message = ''
    for diff in diffs:
        if diff['type'] == 'new_status':
            message += md.text(
                md.text(
                    md.text('📝'),
                    md.hbold(diff['about']['task']),
                    md.text('по'),
                    md.text(f"«{diff['about']['discipline']}»"),
                    sep=' ',
                ),
                md.text(
                    md.text('Cтатус домашнего задания изменён на:'),
                    md.hcode(diff['current_status']),
                    sep=' ',
                ),
                md.text(),
                md.text(
                    md.text('Подробности по ссылке:'),
                    md.text(diff['about']['url']),
                    sep=' ',
                ),
                sep='\n',
            )
        elif diff['type'] == 'new_message':
            message += md.text(
                md.text(
                    md.text('📝'),
                    md.hbold(diff['about']['task']),
                    md.text('по'),
                    md.text(f"«{diff['about']['discipline']}»"),
                    sep=' ',
                ),
                md.text(
                    md.text('Получено личное сообщение от преподавателя.'),
                    md.text(
                        md.text('Количество новых сообщений:'),
                        md.hcode(diff['current_messages']),
                        sep=' ',
                    ),
                    sep=' ',
                ),
                md.text(),
                md.text(
                    md.text('Подробности по ссылке:'),
                    md.text(diff['about']['url']),
                    sep=' ',
                ),
                sep='\n',
            )
        message += '\n' * 3
    return message


def compare(old_dict: dict[str, dict], new_dict: dict[str, dict]) -> list:
    diffs = []
    for thread_id_old in old_dict:
        try:
            _ = new_dict[thread_id_old]
        except KeyError as exception:
            raise FileCompareException from exception

        if old_dict[thread_id_old]['status'] != new_dict[thread_id_old]['status']:
            diffs.append(
                {
                    'type': 'new_status',  # or `new_message`
                    'current_status': new_dict[thread_id_old]['status'],
                    'about': new_dict[thread_id_old]['about'],
                }
            )
        elif (
            old_dict[thread_id_old]['new_messages']
            > old_dict[thread_id_old]['new_messages']
        ):
            diffs.append(
                {
                    'type': 'new_message',  # or `new_status`
                    'current_messages': new_dict[thread_id_old]['new_messages'],
                    'about': new_dict[thread_id_old]['about'],
                }
            )
    return diffs


async def user_homeworks_check(user_telegram_id: int) -> None:
    mongo_context = MongoContextManager(
        database="tracking_data",
        collection="homeworks",
    )

    homeworks_filter = {'id': user_telegram_id}

    try:
        homeworks_dict = await get_orioks_homeworks(user_telegram_id)
    except OrioksParseDataException as exception:
        logging.info(
            '(HOMEWORKS) [%s] exception: utils.exceptions.OrioksCantParseData',
            user_telegram_id,
        )
        async with mongo_context as mongo:
            await mongo.delete_one(homeworks_filter)
        raise exception
    except ClientResponseError as exception:
        if 400 <= exception.status < 500:
            logging.info(
                '(HOMEWORKS) [%s] exception: aiohttp.ClientResponseError status in [400, 500). Raising OrioksCantParseData',
                user_telegram_id,
            )
            async with mongo_context as mongo:
                await mongo.delete_one(homeworks_filter)
            raise OrioksParseDataException from exception
        raise exception

    async with mongo_context as mongo:
        existing_document = await mongo.find_one(homeworks_filter)

        if existing_document is None:
            await mongo.insert_one({'id': user_telegram_id, 'data': homeworks_dict})
            return None

        old_dict = existing_document['data']

        try:
            diffs = compare(old_dict=old_dict, new_dict=homeworks_dict)
        except FileCompareException as exception:
            await mongo.update_one(homeworks_filter, {'data': homeworks_dict})
            raise exception

        if len(diffs) > 0:
            msg = HomeworkChangeMessage(
                user_telegram_id=user_telegram_id,
                message=await get_homeworks_to_msg(diffs=diffs),
            )
            serialized_data = msgpack.packb(msg.model_dump())
            await Producer.send(serialized_data, queue_name="notifier")

        await mongo.update_one(homeworks_filter, {'data': homeworks_dict})
