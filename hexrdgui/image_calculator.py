import numpy as np


def add(img1: np.ndarray, img2: np.ndarray) -> np.ndarray:
    return img1 + img2


def subtract(img1: np.ndarray, img2: np.ndarray) -> np.ndarray:
    return img1 - img2


def multiply(img1: np.ndarray, img2: np.ndarray) -> np.ndarray:
    return img1 * img2


def divide(img1: np.ndarray, img2: np.ndarray) -> np.ndarray:
    return img1 / img2


def and_op(img1: np.ndarray, img2: np.ndarray) -> np.ndarray:
    return np.logical_and(img1, img2)


def or_op(img1: np.ndarray, img2: np.ndarray) -> np.ndarray:
    return np.logical_or(img1, img2)


def xor(img1: np.ndarray, img2: np.ndarray) -> np.ndarray:
    return np.logical_xor(img1, img2)


def min(img1: np.ndarray, img2: np.ndarray) -> np.ndarray:
    return np.minimum(img1, img2)


def max(img1: np.ndarray, img2: np.ndarray) -> np.ndarray:
    return np.maximum(img1, img2)


def average(img1: np.ndarray, img2: np.ndarray) -> np.ndarray:
    return (img1 + img2) / 2


def difference(img1: np.ndarray, img2: np.ndarray) -> np.ndarray:
    return np.abs(img1 - img2)


def copy_op(img1: np.ndarray, img2: np.ndarray) -> np.ndarray:
    return np.copy(img2)


IMAGE_CALCULATOR_OPERATIONS = {
    'Add': add,
    'Subtract': subtract,
    'Multiply': multiply,
    'Divide': divide,
    'AND': and_op,
    'OR': or_op,
    'XOR': xor,
    'Min': min,
    'Max': max,
    'Average': average,
    'Difference': difference,
    'Copy': copy_op,
}
