import os
import pathlib
import traceback
from typing import Union

from app import config


class CommonHelper:
    @staticmethod
    def is_correct_convert_to_float(x) -> bool:
        try:
            float(x)
            return True
        except ValueError:
            return False
