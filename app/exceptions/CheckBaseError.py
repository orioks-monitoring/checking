from abc import ABCMeta


class CheckBaseError(Exception, metaclass=ABCMeta):
    """Абстрактное исключение, наследники которого возникают при ошибках во время проверки."""
