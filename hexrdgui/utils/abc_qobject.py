from abc import ABC, ABCMeta

from PySide6.QtCore import QObject

QObjectMeta = type(QObject)


class _ABCQObjectMeta(QObjectMeta, ABCMeta):
    pass


class ABCQObject(QObject, ABC, metaclass=_ABCQObjectMeta):
    pass
