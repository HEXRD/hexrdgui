from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSize, Qt
from PySide6.QtGui import QFontMetrics, QPainter, QTextDocument
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget


class HtmlDelegate(QStyledItemDelegate):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Store the custom stylesheet.
        self._stylesheet = ''
        self._document_margin = 4.0

    def set_stylesheet(self, css_string: str) -> None:
        """Sets the custom CSS stylesheet to be used for all items."""
        self._stylesheet = css_string

    def _add_stylesheet(self, html_content: str) -> str:
        return (
            '<html>'
            f'<head><style>{self._stylesheet}</style></head>'
            f'<body>{html_content}</body>'
            '</html>'
        )

    def _get_display_string(
        self, index: QModelIndex | QPersistentModelIndex
    ) -> str | None:
        data = index.data(Qt.ItemDataRole.DisplayRole)
        if data is not None and not isinstance(data, str):
            # Ensure it is a string
            data = str(data)
        return data

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        data = self._get_display_string(index)
        if not data:
            return

        # Use a temporary QTextDocument to get the plain text from the HTML.
        temp_doc = QTextDocument()
        temp_doc.setHtml(data)
        plain_text = temp_doc.toPlainText()

        # Check if the plain text needs to be truncated with an ellipsis.
        font_metrics = QFontMetrics(option.font)  # type: ignore[attr-defined]
        text_width = font_metrics.horizontalAdvance(plain_text)

        # Allow for a small margin.
        available_width = option.rect.width() - 4  # type: ignore[attr-defined]

        # If text is too long, elide it.
        if text_width > available_width:
            elided_text = font_metrics.elidedText(
                plain_text, Qt.TextElideMode.ElideRight, available_width
            )
            # Re-wrap the elided text in a simple HTML structure to preserve
            # formatting.
            html_content = f'<span>{elided_text}</span>'
        else:
            # If it fits, use the original HTML content.
            html_content = data

        # Use a QTextDocument to handle the HTML rendering.
        full_html = self._add_stylesheet(html_content)
        doc = QTextDocument()
        doc.setHtml(full_html)
        doc.setDefaultFont(option.font)  # type: ignore[attr-defined]
        doc.setDocumentMargin(self._document_margin)

        # Draw the text document.
        painter.save()
        painter.setClipRect(option.rect)  # type: ignore[attr-defined]

        # Handle item selection state
        if option.state & QStyle.StateFlag.State_Selected:  # type: ignore[attr-defined]
            painter.fillRect(option.rect, option.palette.highlight())  # type: ignore[attr-defined]

        # Move the painter to the correct position for the text document.
        painter.translate(option.rect.x(), option.rect.y())  # type: ignore[attr-defined]

        # Align the text within the item.
        # text_option = doc.defaultTextOption()
        # text_option.setWrapMode(QTextOption.WordWrap)
        # doc.setDefaultTextOption(text_option)

        doc.drawContents(
            painter,
            option.rect.translated(-option.rect.x(), -option.rect.y()),  # type: ignore[attr-defined]
        )
        painter.restore()

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        data = self._get_display_string(index)
        if not data:
            return QSize(0, 0)

        doc = QTextDocument()
        doc.setHtml(self._add_stylesheet(data))
        doc.setDefaultFont(option.font)  # type: ignore[attr-defined]
        doc.setDocumentMargin(self._document_margin)

        return QSize(int(doc.idealWidth()), int(doc.size().height()))


def _stacked_notation_table_stylesheet() -> str:
    return """
        .stacked-notation-table {
            border-collapse: collapse;
            vertical-align: middle;
        }
        .stacked-notation-table .sup {
            vertical-align: top;
            font-size: small;
        }
        .stacked-notation-table .sub {
            vertical-align: bottom;
            font-size: small;
        }
    """


def aligned_sub_sup_html(base: str, sup: str, sub: str) -> str:
    # This automatically generates HTML to align superscripts
    # and subscripts on top of one another.
    # Unlike a bunch of other methods for doing this, this
    # specific method is actually acceptable to Qt's limited
    # css support.
    return f"""
        <style>
            {_stacked_notation_table_stylesheet()}
        </style>
        <table class="stacked-notation-table">
            <tr>
                <td rowspan="2">{base}</td>
                <td class="sup">{sup}</td>
            </tr>
            <tr>
                <td class="sub">{sub}</td>
            </tr>
        </table>
    """
