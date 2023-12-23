import logging
import os

import re

import msgpack
from aiohttp import ClientResponseError
from bs4 import BeautifulSoup

from app.config import ORIOKS_PAGE_URLS
from app.exceptions import OrioksParseDataException, FileCompareException
from app.helpers import (
    CommonHelper,
    RequestHelper,
    MongoContextManager,
)
from app.queue.Producer import Producer
import aiogram.utils.markdown as md

from message_models.models import RequestChangeMessage


def _orioks_parse_requests(raw_html: str, section: str) -> dict[str, dict]:
    new_messages_td_list_index = 7
    if section == 'questionnaire':
        new_messages_td_list_index = 6
    bs_content = BeautifulSoup(raw_html, "html.parser")
    if bs_content.select_one('.table.table-condensed.table-thread') is None:
        raise OrioksParseDataException
    table_raw = bs_content.select(
        '.table.table-condensed.table-thread tr:not(:first-child)'
    )
    requests = dict()
    for tr in table_raw:
        _thread_id = str(
            re.findall(r'\d+$', tr.find_all('td')[2].select_one('a')['href'])[0]
        )
        requests[_thread_id] = {
            'status': tr.find_all('td')[1].text,
            'new_messages': int(
                tr.find_all('td')[new_messages_td_list_index].select_one('b').text
            ),
            'about': {
                'name': tr.find_all('td')[3].text,
                'url': ORIOKS_PAGE_URLS['masks']['requests'][section].format(
                    id=_thread_id
                ),
            },
        }
    return requests


async def get_orioks_requests(section: str, user_telegram_id: int) -> dict[str, dict]:
    raw_html = await RequestHelper.get_request(
        event_type=f'requests-{section}',
        user_telegram_id=user_telegram_id,
    )
    return _orioks_parse_requests(raw_html=raw_html, section=section)


async def get_requests_to_msg(diffs: list) -> str:
    message = ''
    for diff in diffs:
        if diff['type'] == 'new_status':
            message += md.text(
                md.text(
                    md.text('📄'),
                    md.text('Новые изменения по заявке'),
                    md.hbold(f"«{diff['about']['name']}»"),
                    sep=' ',
                ),
                md.text(
                    md.text('Статус заявки изменён на:'),
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
                    md.text('📄'),
                    md.text('Новые изменения по заявке'),
                    md.hbold(f"«{diff['about']['name']}»"),
                    sep=' ',
                ),
                md.text(
                    md.text('Получено личное сообщение.'),
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
            new_dict[thread_id_old]['new_messages']
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


async def _user_requests_check_with_subsection(
    user_telegram_id: int, section: str
) -> None:
    mongo_context = MongoContextManager(
        database='tracking_data',
        collection='requests',
    )

    requests_filter = {'id': user_telegram_id, 'section': section}

    try:
        requests_dict = await get_orioks_requests(
            section=section, user_telegram_id=user_telegram_id
        )
    except OrioksParseDataException as exception:
        logging.info(
            '(REQUESTS) [%s] exception: utils.exceptions.OrioksCantParseData',
            user_telegram_id,
        )
        async with mongo_context as mongo:
            await mongo.delete_one(requests_filter)
        raise exception
    except ClientResponseError as exception:
        if 400 <= exception.status < 500:
            logging.info(
                '(REQUESTS) [%s] exception: aiohttp.ClientResponseError status in [400, 500). Raising OrioksCantParseData',
                user_telegram_id,
            )
            async with mongo_context as mongo:
                await mongo.delete_one(requests_filter)
            raise OrioksParseDataException from exception
        raise exception

    async with mongo_context as mongo:
        existing_document = await mongo.find_one(requests_filter)

        if existing_document is None:
            await mongo.insert_one(
                {'id': user_telegram_id, 'section': section, 'data': requests_dict}
            )
            return None

    old_dict = existing_document['data']
    try:
        diffs = compare(old_dict=old_dict, new_dict=requests_dict)
    except FileCompareException as exception:
        await mongo.update_one(requests_filter, {'data': requests_dict})
        raise exception

    if len(diffs) > 0:
        msg = RequestChangeMessage(
            user_telegram_id=user_telegram_id,
            message=await get_requests_to_msg(diffs=diffs),
        )
        serialized_data = msgpack.packb(msg.model_dump())
        await Producer.send(serialized_data, queue_name="notifier")

    async with mongo_context as mongo:
        await mongo.update_one(requests_filter, {'data': requests_dict})


async def user_requests_check(user_telegram_id: int) -> None:
    for section in ('questionnaire', 'doc', 'reference'):
        await _user_requests_check_with_subsection(
            user_telegram_id=user_telegram_id, section=section
        )
