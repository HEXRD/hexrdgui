import math

from PySide6.QtCore import QObject
from PySide6.QtGui import QValidator

from hexrdgui.scientificspinbox import FloatValidator, ScientificDoubleSpinBox


def test_scientific_spinbox_text_handling(qtbot):
    # FloatValidator stays a plain helper: a parentless QObject per spin box
    # (hundreds per MainWindow) was where the CI segfaults kept landing.
    assert not issubclass(FloatValidator, QObject)

    sb = ScientificDoubleSpinBox()
    qtbot.addWidget(sb)

    State = QValidator.State
    for text, state in [
        ('1.5e-3', State.Acceptable),
        ('-inf', State.Acceptable),
        ('nan', State.Acceptable),
        ('', State.Intermediate),
        ('1e', State.Intermediate),
        ('1x', State.Invalid),
    ]:
        assert sb.validate(text, len(text)) == state, text

    assert sb.valueFromText('2.5e3') == 2500
    assert sb.valueFromText('-i') == -math.inf
    assert math.isnan(sb.valueFromText('na'))
    assert sb.textFromValue(1.5e-12) == '1.5e-12'
