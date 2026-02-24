from typing import Any

from PySide6.QtCore import QObject


class Singleton(type):

    _instance = None

    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        if cls._instance is None:
            cls._instance = super().__call__(*args, **kwargs)

        return cls._instance


# This metaclass must inherit from `type(QObject)` for classes that use
# it to inherit from QObject.
class QSingleton(type(QObject)):  # type: ignore[misc]

    _instances: dict[str, Any] = {}

    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)

        return cls._instances[cls]
