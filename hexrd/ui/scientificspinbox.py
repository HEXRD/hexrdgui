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


class ScientificDoubleSpinBox(QDoubleSpinBox):

    @staticmethod
    def format_float(value):
        """Modified form of the 'g' format specifier."""

        string = '{:.10g}'.format(value).replace('e+', 'e')
        string = re.sub('e(-?)0*(\d+)', r'e\1\2', string)

        return string

    def __init__(self, *args, **kwargs):
        super(ScientificDoubleSpinBox, self).__init__(*args, **kwargs)
        self.setMinimum(-math.inf)
        self.setMaximum(math.inf)
        self.validator = FloatValidator()
        self.setDecimals(1000)

    def validate(self, text, position):
        return self.validator.validate(text, position)

    def fixup(self, text):
        return self.validator.fixup(text)

    def valueFromText(self, text):
        return float(self.fixup(text))

    def textFromValue(self, value):
        return ScientificDoubleSpinBox.format_float(value)

    def stepBy(self, steps):
        text = self.cleanText()
        groups = FLOAT_REGEX.search(text).groups()
        decimal = float(groups[1])
        decimal += steps
        new_string = '{:.10g}'.format(decimal) + (groups[3] if groups[3] else '')

        # Set the value so that signals get emitted properly
        self.setValue(self.valueFromText(new_string))

        # Select the text just like a regular spin box would...
        self.selectAll()
