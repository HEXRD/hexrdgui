from abc import ABC, ABCMeta

from PySide6.QtCore import QObject

QObjectMeta = type(QObject)


class _ABCQObjectMeta(QObjectMeta, ABCMeta):  # type: ignore[misc,valid-type]
    pass


class ABCQObject(QObject, ABC, metaclass=_ABCQObjectMeta):
    pass
