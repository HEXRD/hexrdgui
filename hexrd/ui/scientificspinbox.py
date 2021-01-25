from functools import wraps
import re
import math

from PySide2.QtGui import QValidator
from PySide2.QtWidgets import QDoubleSpinBox
#
# Derived from https://gist.github.com/jdreaver/0be2e44981159d0854f5
#

FLOAT_REGEX = re.compile(r'(([+-]?\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?)')

# "i" and "in" are both interpreted as "inf"
INFINITE_REGEX = re.compile(r'^([+-]?)(i(?:n|nf)?)$')


class FloatValidator(QValidator):

    @staticmethod
    def valid_float_string(string):
        match = FLOAT_REGEX.search(string)
        if match:
            return match.group(0) == string

        return INFINITE_REGEX.search(string) is not None

    def validate(self, string, position):
        if FloatValidator.valid_float_string(string):
            return self.State.Acceptable

        if string == "" or string[position-1] in 'e.-+':
            return self.State.Intermediate

        return self.State.Invalid

    def fixup(self, text):
        match = FLOAT_REGEX.search(text)
        if match:
            return match.group(0)

        match = INFINITE_REGEX.search(text)
        return match.group(1) + 'inf' if match else ''


def clean_text(func):
    """Clean text for ScientificDoubleSpinBox functions

    This removes the prefix, suffix, and leading/trailing white space.
    """
    @wraps(func)
    def wrapped(self, text, *args, **kwargs):
        text = remove_prefix(text, self.prefix())
        text = remove_suffix(text, self.suffix())
        text = text.strip()
        return func(self, text, *args, **kwargs)
    return wrapped


class ScientificDoubleSpinBox(QDoubleSpinBox):

    @staticmethod
    def format_float(value):
        """Modified form of the 'g' format specifier."""

        string = '{:.10g}'.format(value).replace('e+', 'e')
        string = re.sub(r'e(-?)0*(\d+)', r'e\1\2', string)

        return string

    def __init__(self, *args, **kwargs):
        super(ScientificDoubleSpinBox, self).__init__(*args, **kwargs)
        self.setMinimum(-math.inf)
        self.setMaximum(math.inf)
        self.validator = FloatValidator()
        self.setDecimals(1000)

    @clean_text
    def validate(self, text, position):
        return self.validator.validate(text, position)

    @clean_text
    def fixup(self, text):
        return self.validator.fixup(text)

    @clean_text
    def valueFromText(self, text):
        return float(self.fixup(text))

    def textFromValue(self, value):
        return ScientificDoubleSpinBox.format_float(value)

    def stepBy(self, steps):
        text = self.cleanText()
        groups = FLOAT_REGEX.search(text).groups()
        decimal = float(groups[1])
        decimal += steps
        new_string = f'{decimal:.10g}' + (groups[3] if groups[3] else '')

        # Set the value so that signals get emitted properly
        self.setValue(self.valueFromText(new_string))

        # Select the text just like a regular spin box would...
        self.selectAll()


def remove_prefix(text, prefix):
    # This can be replaced with str.removeprefix() in python >=3.9
    if prefix and text.startswith(prefix):
        return text[len(prefix):]
    return text


def remove_suffix(text, suffix):
    # This can be replaced with str.removesuffix() in python >=3.9
    if suffix and text.endswith(suffix):
        return text[:-len(suffix)]
    return text
