import json
import os
from dataclasses import dataclass

import msgpack
from aiohttp import ClientResponseError
from bs4 import BeautifulSoup
import logging

from app.config import STUDENT_FILE_JSON_MASK, BASEDIR, ORIOKS_PAGE_URLS
from app.exceptions import OrioksParseDataException, FileCompareException
from app.helpers import (
    CommonHelper,
    RequestHelper,
    MongoContextManager,
    MessageToAdminsHelper,
)
from app.queue.Producer import Producer
from app.marks.compares import (
    file_compares,
    get_discipline_objs_from_diff,
)

from app.queue.Producer import Priority
from message_models.models import MarkChangeMessage, ToAdminsMessage


@dataclass
class DisciplineBall:
    current: float = 0
    might_be: float = 0


def _iterate_forang_version_with_list(forang: dict) -> list:
    json_to_save = []
    for discipline in forang['dises']:
        discipline_ball = DisciplineBall()
        one_discipline = []
        for mark in discipline['segments'][0]['allKms']:
            alias = mark['sh']
            if (
                mark['sh'] in ('-', None, ' ', '')
                and mark['id'] == discipline['segments'][0]['allKms'][-1]['id']
            ):
                alias = discipline['formControl'][
                    'name'
                ]  # issue 19: если нет алиаса на последнем КМ

            current_grade = mark['grade']['b']
            max_grade = mark['max_ball']

            one_discipline.append(
                {
                    'alias': alias,
                    'current_grade': current_grade,
                    'max_grade': max_grade,
                }
            )
            discipline_ball.current += (
                current_grade
                if CommonHelper.is_correct_convert_to_float(current_grade)
                else 0
            )
            discipline_ball.might_be += (
                max_grade
                if CommonHelper.is_correct_convert_to_float(max_grade)
                and current_grade != '-'
                else 0
            )
        json_to_save.append(
            {
                'subject': discipline['name'],
                'tasks': one_discipline,
                'ball': {
                    'current': round(discipline_ball.current, 2),
                    'might_be': round(discipline_ball.might_be, 2),
                },
            }
        )
    return json_to_save


def _iterate_forang_version_with_keys(forang: dict) -> list:
    json_to_save = []
    for discipline_index in forang['dises'].keys():
        discipline_ball = DisciplineBall()
        one_discipline = []
        for mark in forang['dises'][discipline_index]['segments'][0]['allKms']:
            alias = mark['sh']  # issue 19: если нет алиаса на последнем КМ
            if (
                mark['sh'] in ('-', None, ' ', '')
                and mark['id']
                == forang['dises'][discipline_index]['segments'][0]['allKms'][-1]['id']
            ):
                alias = forang['dises'][discipline_index]['formControl']['name']

            current_grade = mark['grade']['b']
            max_grade = mark['max_ball']

            one_discipline.append(
                {
                    'alias': alias,
                    'current_grade': current_grade,
                    'max_grade': max_grade,
                }
            )
            discipline_ball.current += (
                current_grade
                if CommonHelper.is_correct_convert_to_float(current_grade)
                else 0
            )
            discipline_ball.might_be += (
                max_grade
                if CommonHelper.is_correct_convert_to_float(max_grade)
                and current_grade != '-'
                else 0
            )
        json_to_save.append(
            {
                'subject': forang['dises'][discipline_index]['name'],
                'tasks': one_discipline,
                'ball': {
                    'current': round(discipline_ball.current, 2),
                    'might_be': round(discipline_ball.might_be, 2),
                },
            }
        )
    return json_to_save


def _get_orioks_forang(raw_html: str):
    """return: [{'subject': s, 'tasks': [t], 'ball': {'current': c, 'might_be': m}, ...]"""
    bs_content = BeautifulSoup(raw_html, "html.parser")
    try:
        forang_raw = bs_content.find(id='forang').text
    except AttributeError as exception:
        raise OrioksParseDataException from exception
    forang = json.loads(forang_raw)

    if len(forang) == 0:
        raise OrioksParseDataException

    try:
        json_to_save = _iterate_forang_version_with_list(forang=forang)
    except TypeError:
        json_to_save = _iterate_forang_version_with_keys(forang=forang)

    return json_to_save


async def get_orioks_marks(user_telegram_id: int):
    raw_html = await RequestHelper.get_request(
        event_type='marks', user_telegram_id=user_telegram_id
    )
    return _get_orioks_forang(raw_html)


async def user_marks_check(user_telegram_id: int) -> None:
    student_filter = {'id': user_telegram_id}

    mongo_context = MongoContextManager(
        database='tracking_data',
        collection='marks',
    )

    try:
        detailed_info = await get_orioks_marks(user_telegram_id)
    except FileNotFoundError as exception:
        await MessageToAdminsHelper.send(f'FileNotFoundError - {user_telegram_id}')
        raise FileNotFoundError(
            f'FileNotFoundError - {user_telegram_id}'
        ) from exception
    except OrioksParseDataException as exception:
        logging.info(
            '(MARKS) [%s] exception: utils.exceptions.OrioksCantParseData',
            user_telegram_id,
        )
        async with mongo_context as mongo:
            await mongo.delete_one(student_filter)
        raise exception
    except ClientResponseError as exception:
        if 400 <= exception.status < 500:
            logging.info(
                '(MARKS) [%s] exception: aiohttp.ClientResponseError status in [400, 500). Raising OrioksCantParseData',
                user_telegram_id,
            )
            async with mongo_context as mongo:
                await mongo.delete_one(student_filter)
            raise OrioksParseDataException from exception
        raise exception

    async with mongo_context as mongo:
        existing_document = await mongo.find_one(student_filter)

        if existing_document is None:
            await mongo.insert_one({'id': user_telegram_id, 'data': detailed_info})
            return None

        old_json = existing_document['data']

        try:
            diffs = file_compares(old_file=old_json, new_file=detailed_info)
        except FileCompareException as exception:
            await mongo.update_one(student_filter, {'data': detailed_info})
            raise exception

        if len(diffs) > 0:
            for discipline_obj in get_discipline_objs_from_diff(diffs=diffs):
                msg = MarkChangeMessage(
                    title_text=discipline_obj.title_text,
                    mark_change_text=discipline_obj.mark_change_text,
                    current_grade=discipline_obj.current_grade,
                    max_grade=discipline_obj.max_grade,
                    caption=discipline_obj.caption,
                    side_text='Изменён балл за контрольное мероприятие',
                    user_telegram_id=user_telegram_id,
                )
                serialized_data = msgpack.packb(msg.model_dump())
                await Producer.send(serialized_data, queue_name="notifier")

            await mongo.update_one(student_filter, {'data': detailed_info})
