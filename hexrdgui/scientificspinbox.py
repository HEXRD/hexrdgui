from functools import wraps
import re
import math

from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QDoubleSpinBox
#
# Derived from https://gist.github.com/jdreaver/0be2e44981159d0854f5
#

FLOAT_REGEX = re.compile(r'(([+-]?\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?)')

# "i" and "in" are both interpreted as "inf"
INFINITE_REGEX = re.compile(r'^([+-]?)(i(?:n|nf)?)$')

# "n" and "na" are both interpreted as "nan"
NAN_REGEX = re.compile(r'^(n(?:a|an)?)$')


class FloatValidator(QValidator):

    @staticmethod
    def valid_float_string(string):
        match = FLOAT_REGEX.search(string)
        if match:
            return match.group(0) == string

        special_regexes = (INFINITE_REGEX, NAN_REGEX)
        return any(x.search(string) is not None for x in special_regexes)

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

        if match := INFINITE_REGEX.search(text):
            return match.group(1) + 'inf'

        if NAN_REGEX.search(text):
            return 'nan'

        return ''


def clean_text(func):
    """Clean text for ScientificDoubleSpinBox functions

    This removes the prefix, suffix, and leading/trailing white space.
    """
    @wraps(func)
    def wrapped(self, text, *args, **kwargs):
        text = text.removeprefix(self.prefix())
        text = text.removesuffix(self.suffix())
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
        super().__init__(*args, **kwargs)
        self.validator = FloatValidator()
        self.setDecimals(1000)
        self.reset_range()

    def reset_range(self):
        self.setRange(-math.inf, math.inf)

    @clean_text
    def validate(self, text, position):
        return self.validator.validate(text, position)

    @clean_text
    def fixup(self, original_text):
        text = self.validator.fixup(original_text)
        if text == 'nan':
            self.is_nan = True
            # Don't auto-fill the text
            self.lineEdit().setText(original_text)
        elif self.is_nan and text:
            self.is_nan = False
            # Don't auto-fill the text
            self.lineEdit().setText(original_text)
        return text

    @clean_text
    def valueFromText(self, text):
        return float(self.fixup(text))

    def textFromValue(self, value):
        return ScientificDoubleSpinBox.format_float(value)

    def stepBy(self, steps):
        text = self.cleanText()
        if any(x.search(text) for x in (INFINITE_REGEX, NAN_REGEX)):
            # We cannot step
            return

        new_value = self.value() + self.singleStep() * steps
        self.setValue(new_value)

        # Select the text just like a regular spin box would...
        self.selectAll()

    def setValue(self, v):
        self.is_nan = math.isnan(v)
        super().setValue(v)

    @property
    def is_nan(self):
        return math.isnan(super().value())

    @is_nan.setter
    def is_nan(self, b):
        if self.is_nan == b:
            # Unchanged
            return

        if b:
            # Setting the min or max to nan forces the min, max, and
            # value to all be nan.
            self.setMaximum(math.nan)
        else:
            # Reset the range so we can have values that are not nan
            self.reset_range()
