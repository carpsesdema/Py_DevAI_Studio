import logging
from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QFont, QColor
from PyQt6.QtCore import QRegularExpression, Qt

from utils import constants

logger = logging.getLogger(constants.APP_NAME)


def format_rule(pattern_str: str, color_hex: str, weight: QFont.Weight = QFont.Weight.Normal, italic: bool = False) -> \
tuple[QRegularExpression, QTextCharFormat]:
    try:
        color = QColor(color_hex)
        if not color.isValid():
            logger.warning(
                f"SyntaxHighlighter: Invalid color hex '{color_hex}' for pattern '{pattern_str}'. Using black.")
            color = QColor(Qt.GlobalColor.black)
    except Exception:
        logger.warning(f"SyntaxHighlighter: Could not parse color hex '{color_hex}'. Using black.")
        color = QColor(Qt.GlobalColor.black)

    char_format = QTextCharFormat()
    char_format.setForeground(color)
    char_format.setFontWeight(weight)
    char_format.setFontItalic(italic)

    try:
        regex = QRegularExpression(pattern_str)
        if not regex.isValid():
            logger.error(
                f"SyntaxHighlighter: Invalid QRegularExpression pattern: {pattern_str}. Rule will be ineffective.")
            # Return a non-matching regex to prevent crashes, but log error
            regex = QRegularExpression("(?!)")  # Negative lookahead, never matches
    except Exception as e:
        logger.error(
            f"SyntaxHighlighter: QRegularExpression compilation error for '{pattern_str}': {e}. Rule will be ineffective.")
        regex = QRegularExpression("(?!)")

    return regex, char_format


class PythonSyntaxHighlighter(QSyntaxHighlighter):
    KEYWORD_COLOR = "#C586C0"  # Magenta-ish (VSCode Python Keyword)
    OPERATOR_COLOR = "#D4D4D4"  # Default text color, operators stand out by context
    BRACE_COLOR = "#D4D4D4"
    DEF_CLASS_COLOR = "#4EC9B0"  # Teal (VSCode Function/Class Name)
    STRING_COLOR = "#CE9178"  # Orange-ish (VSCode String)
    COMMENT_COLOR = "#6A9955"  # Green (VSCode Comment)
    NUMBER_COLOR = "#B5CEA8"  # Light Green/Olive (VSCode Number)
    DECORATOR_COLOR = "#DCDCAA"  # Khaki/Yellow (VSCode Decorator)
    SELF_BUILTIN_COLOR = "#4EC9B0"  # Same as Def/Class for self, similar to builtins

    STYLES = {
        'keywords': format_rule(
            r'\b(and|as|assert|async|await|break|class|continue|def|del|elif|else|except|finally|for|from|global|if|import|in|is|lambda|nonlocal|not|or|pass|raise|return|try|while|with|yield|True|False|None)\b',
            KEYWORD_COLOR, QFont.Weight.Bold
        ),
        'operators': format_rule(
            r'(=|==|!=|<=|>=|<|>|\+=|-=|\*=|/=|%=|//=|&=|\|=|\^=|>>=|<<=|\*\*=|->|\+|\-|\*|/|%|//|&|\||\^|~|<<|>>|\*\*)',
            OPERATOR_COLOR
        ),
        'braces': format_rule(
            r'(\(|\)|\[|\]|\{|\}|:|,|\.)',
            BRACE_COLOR
        ),
        'decorator': format_rule(
            r'@([a-zA-Z_][a-zA-Z0-9_]*)', DECORATOR_COLOR
        ),
        'def_class_names': format_rule(
            r'\b(def|class)\s+([a-zA-Z_][a-zA-Z0-9_]*)',
            DEF_CLASS_COLOR, QFont.Weight.Bold
        ),
        'self_builtins': format_rule(
            r'\b(self|super|cls|int|str|float|list|dict|tuple|set|bool|Exception|object|print|len|range|type|id|abs|all|any|bin|callable|chr|complex|delattr|dir|divmod|enumerate|eval|filter|format|getattr|hasattr|hash|hex|input|isinstance|issubclass|iter|map|max|min|next|oct|open|ord|pow|property|repr|reversed|round|setattr|slice|sorted|sum|vars|zip|__import__|__name__|__main__|__init__|__str__|__repr__|__call__|__len__|__getitem__|__setitem__|__delitem__|__iter__|__next__|__contains__|__eq__|__ne__|__lt__|__le__|__gt__|__ge__|__add__|__sub__|__mul__|__truediv__|__floordiv__|__mod__|__pow__|__and__|__or__|__xor__|__lshift__|__rshift__|__enter__|__exit__|__new__|__del__|__getattr__|__setattr__|__getattribute__|__class__)\b',
            SELF_BUILTIN_COLOR, QFont.Weight.Normal
        ),
        'numbers': format_rule(
            r'\b([0-9]+[lL]?|[0-9]+\.[0-9]*(e[-+]?[0-9]+)?|\.[0-9]+(e[-+]?[0-9]+)?|0[xX][0-9a-fA-F]+[lL]?|0[oO][0-7]+[lL]?|0[bB][01]+[lL]?)\b',
            NUMBER_COLOR
        ),
        'comments': format_rule(r'#[^\n]*', COMMENT_COLOR, QFont.Weight.Normal, True),
    }

    def __init__(self, parent_document):
        super().__init__(parent_document)

        self.tri_single_quote_delim = QRegularExpression(r"'''")
        self.tri_double_quote_delim = QRegularExpression(r'"""')
        self.single_quote_delim = QRegularExpression(r"(?<!\\)'")  # Negative lookbehind for escaped quote
        self.double_quote_delim = QRegularExpression(r'(?<!\\)"')  # Negative lookbehind for escaped quote

        self.string_format = QTextCharFormat()
        self.string_format.setForeground(QColor(self.STRING_COLOR))

        self.highlighting_rules = []
        for name, (pattern, style_format) in self.STYLES.items():
            self.highlighting_rules.append((pattern, style_format))
            if name == 'def_class_names':  # Special handling for def/class names
                self.def_class_name_format = style_format

    def highlightBlock(self, text: str) -> None:
        for pattern, style_format in self.highlighting_rules:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                start = match.capturedStart()
                length = match.capturedLength()

                # Special handling for 'def' and 'class' to color only the name
                if pattern.pattern() == self.STYLES['def_class_names'][0].pattern():
                    name_start = match.capturedStart(2)  # Group 2 is the name
                    name_length = match.capturedLength(2)
                    if name_start >= 0 and name_length > 0:
                        self.setFormat(name_start, name_length, self.def_class_name_format)
                else:
                    self.setFormat(start, length, style_format)

        self.setCurrentBlockState(0)  # Default state

        # Multi-line strings
        # Order matters: triple quotes first, then single quotes
        in_multiline_state = self.apply_multiline_string_highlight(text, self.tri_double_quote_delim, 1,
                                                                   self.string_format)
        if not in_multiline_state:
            in_multiline_state = self.apply_multiline_string_highlight(text, self.tri_single_quote_delim, 2,
                                                                       self.string_format)

        # Single-line strings (only if not inside a multi-line string from previous block)
        if self.previousBlockState() == 0:  # Not in multi-line from before
            self.apply_single_line_string_highlight(text, self.double_quote_delim, self.string_format)
            self.apply_single_line_string_highlight(text, self.single_quote_delim, self.string_format)

    def apply_multiline_string_highlight(self, text: str, delimiter: QRegularExpression, in_state: int,
                                         style: QTextCharFormat) -> bool:
        start_index = 0
        add = 0

        if self.previousBlockState() == in_state:
            start_index = 0
            add = 0
            self.setCurrentBlockState(in_state)
        else:
            start_match = delimiter.match(text)
            if not start_match.hasMatch():
                return False
            start_index = start_match.capturedStart()
            add = start_match.capturedLength()

        end_match = delimiter.match(text, start_index + add)
        if end_match.hasMatch():
            end_index = end_match.capturedStart()
            length = (end_index - start_index) + end_match.capturedLength()
            self.setCurrentBlockState(0)
        else:
            self.setCurrentBlockState(in_state)
            length = len(text) - start_index

        self.setFormat(start_index, length, style)
        return self.currentBlockState() == in_state

    def apply_single_line_string_highlight(self, text: str, delimiter: QRegularExpression,
                                           style: QTextCharFormat) -> None:
        match_iterator = delimiter.globalMatch(text)
        start_index = -1

        while match_iterator.hasNext():
            match = match_iterator.next()
            if start_index == -1:  # Start of a new string
                start_index = match.capturedStart()
            else:  # End of the string
                length = match.capturedEnd() - start_index
                self.setFormat(start_index, length, style)
                start_index = -1  # Reset for next potential string

        if start_index != -1:  # Unclosed string, highlight to end of line
            self.setFormat(start_index, len(text) - start_index, style)