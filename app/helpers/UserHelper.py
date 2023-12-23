import logging

from aiogram.utils import markdown

from app import config
from app.exceptions import DatabaseException
from app.models.users import UserStatus, UserNotifySettings

from aiohttp import ClientSession


class UserHelper:
    @staticmethod
    def __get_user_by_telegram_id(user_telegram_id: int) -> UserStatus:
        user = UserStatus.find_one(user_telegram_id=user_telegram_id)
        if user is None:
            raise DatabaseException(
                f'User with telegram id {user_telegram_id} not found in database'
            )

        return user

    @staticmethod
    def get_user_settings_by_telegram_id(
        user_telegram_id: int,
    ) -> UserNotifySettings:
        user_notify_settings = UserNotifySettings.find_one(
            user_telegram_id=user_telegram_id
        )
        if user_notify_settings is None:
            raise DatabaseException(
                f'Settings of user with telegram id {user_telegram_id} not found in database'
            )

        return user_notify_settings

    @staticmethod
    def create_user_if_not_exist(user_telegram_id: int) -> None:
        existed_user = UserStatus.find_one(user_telegram_id=user_telegram_id)
        if existed_user is None:
            user = UserStatus()
            user.fill(user_telegram_id=user_telegram_id)
            user.save()

        existed_user_settings = UserNotifySettings.find_one(
            user_telegram_id=user_telegram_id
        )
        if existed_user_settings is None:
            user_settings = UserNotifySettings()
            user_settings.fill(user_telegram_id=user_telegram_id)
            user_settings.save()

    @staticmethod
    def is_user_agreement_accepted(user_telegram_id: int) -> bool:
        user = UserHelper.__get_user_by_telegram_id(user_telegram_id=user_telegram_id)
        return user.agreement_accepted

    @staticmethod
    def accept_user_agreement(user_telegram_id: int) -> None:
        user = UserHelper.__get_user_by_telegram_id(user_telegram_id=user_telegram_id)
        user.agreement_accepted = True
        user.save()

    @staticmethod
    def is_user_orioks_authenticated(user_telegram_id: int) -> bool:
        user = UserHelper.__get_user_by_telegram_id(user_telegram_id=user_telegram_id)
        return user.authenticated

    @staticmethod
    def get_login_attempt_count(user_telegram_id: int) -> int:
        user = UserHelper.__get_user_by_telegram_id(user_telegram_id=user_telegram_id)
        return user.login_attempt_count

    @staticmethod
    def increment_login_attempt_count(user_telegram_id: int) -> None:
        user = UserHelper.__get_user_by_telegram_id(user_telegram_id=user_telegram_id)
        user.login_attempt_count += 1
        user.save()

    @staticmethod
    def update_authorization_status(
        user_telegram_id: int, is_authenticated: bool
    ) -> None:
        user = UserHelper.__get_user_by_telegram_id(user_telegram_id=user_telegram_id)
        user.authenticated = is_authenticated
        user.save()

    @staticmethod
    def reset_notification_settings(user_telegram_id: int) -> None:
        user_settings = UserHelper.get_user_settings_by_telegram_id(
            user_telegram_id=user_telegram_id
        )
        user_settings.fill(user_telegram_id=user_telegram_id)
        user_settings.save()

    @staticmethod
    def update_notification_settings(user_telegram_id: int, setting_name: str) -> None:
        user_settings = UserHelper.get_user_settings_by_telegram_id(
            user_telegram_id=user_telegram_id
        )
        if getattr(user_settings, setting_name) is None:
            raise DatabaseException(
                f'Setting with name {setting_name} for user with id {user_telegram_id} not found'
            )

        setattr(
            user_settings,
            setting_name,
            not bool(getattr(user_settings, setting_name)),
        )
        user_settings.save()

    @staticmethod
    def get_users_with_enabled_news_subscription():
        users = UserNotifySettings.query.filter_by(news=True)
        return users

    @staticmethod
    async def increment_failed_request_count(user_telegram_id: int) -> None:
        user = UserHelper.__get_user_by_telegram_id(user_telegram_id=user_telegram_id)
        user.failed_request_count += 1
        if user.failed_request_count > config.ORIOKS_MAX_FAILED_REQUESTS:
            from app.helpers import TelegramMessageHelper

            logging.info("Sending http request to logout")
            async with ClientSession(
                timeout=config.REQUESTS_TIMEOUT,
                headers={
                    config.LOGIN_LOGOUT_SERVICE_HEADER_NAME: config.LOGIN_LOGOUT_SERVICE_TOKEN
                },
            ) as http_session:
                async with http_session.post(
                    config.LOGIN_LOGOUT_SERVICE_URL_FOR_LOGOUT.format(
                        user_telegram_id=user_telegram_id
                    ),
                ) as service_response:
                    service_response.raise_for_status()
            logging.info("Successfully sent request to logout")
            #

            await TelegramMessageHelper.text_message_to_user(
                user_telegram_id=user_telegram_id,
                message=markdown.text(
                    markdown.hbold('Ваш аккаунт был деавторизирован.'),
                    markdown.text('🔧 Ошибки при получении данных с сервера ОРИОКС.'),
                    markdown.text('Пожалуйста, авторизуйтесь заново: /login'),
                    markdown.text(),
                    markdown.text(
                        'Связаться с поддержкой Бота: @orioks_monitoring_support_bot'
                    ),
                    sep='\n',
                ),
            )
        user.save()

    @staticmethod
    def reset_failed_request_count(user_telegram_id: int) -> None:
        user = UserHelper.__get_user_by_telegram_id(user_telegram_id=user_telegram_id)
        user.failed_request_count = 0
        user.save()
