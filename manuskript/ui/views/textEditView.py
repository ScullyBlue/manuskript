#!/usr/bin/env python
# --!-- coding: utf8 --!--
import re

from PyQt5.QtCore import QTimer, QModelIndex, Qt, QEvent, pyqtSignal, QRegExp
from PyQt5.QtGui import QTextBlockFormat, QTextCharFormat, QFont, QColor, QIcon, QMouseEvent, QTextCursor
from PyQt5.QtWidgets import QWidget, QTextEdit, qApp, QAction, QMenu

from manuskript import settings
from manuskript.enums import Outline
from manuskript.functions import AUC, themeIcon
from manuskript.functions import toString
from manuskript.models.outlineModel import outlineModel
from manuskript.ui.editors.MDFunctions import MDFormatSelection
from manuskript.ui.editors.MMDHighlighter import MMDHighlighter
from manuskript.ui.editors.basicHighlighter import basicHighlighter
from manuskript.ui.editors.textFormat import textFormat

try:
    import enchant
except ImportError:
    enchant = None


class textEditView(QTextEdit):
    def __init__(self, parent=None, index=None, html=None, spellcheck=True, highlighting=False, dict="",
                 autoResize=False):
        QTextEdit.__init__(self, parent)
        self._column = Outline.text.value
        self._index = None
        self._indexes = None
        self._model = None
        self._placeholderText = self.placeholderText()
        self._updating = False
        self._item = None
        self._highlighting = highlighting
        self._textFormat = "text"
        self.setAcceptRichText(False)
        # When setting up a theme, this becomes true.
        self._fromTheme = False

        self.spellcheck = spellcheck
        self.currentDict = dict if dict else settings.dict
        self.highlighter = None
        self.setAutoResize(autoResize)
        self._defaultBlockFormat = QTextBlockFormat()
        self._defaultCharFormat = QTextCharFormat()
        self.highlightWord = ""
        self.highligtCS = False
        self.defaultFontPointSize = qApp.font().pointSize()
        self._dict = None
        # self.document().contentsChanged.connect(self.submit, AUC)

        # Submit text changed only after 500ms without modifications
        self.updateTimer = QTimer()
        self.updateTimer.setInterval(500)
        self.updateTimer.setSingleShot(True)
        self.updateTimer.timeout.connect(self.submit)
        # self.updateTimer.timeout.connect(lambda: print("Timeout"))

        self.updateTimer.stop()
        self.document().contentsChanged.connect(self.updateTimer.start, AUC)
        # self.document().contentsChanged.connect(lambda: print("Document changed"))

        # self.document().contentsChanged.connect(lambda: print(self.objectName(), "Contents changed"))

        self.setEnabled(False)

        if index:
            self.setCurrentModelIndex(index)

        elif html:
            self.document().setHtml(html)
            self.setReadOnly(True)

        # Spellchecking
        if enchant and self.spellcheck:
            try:
                self._dict = enchant.Dict(self.currentDict if self.currentDict else enchant.get_default_language())
            except enchant.errors.DictNotFoundError:
                self.spellcheck = False

        else:
            self.spellcheck = False

        if self._highlighting and not self.highlighter:
            self.highlighter = basicHighlighter(self)
            self.highlighter.setDefaultBlockFormat(self._defaultBlockFormat)

    def setModel(self, model):
        self._model = model
        try:
            self._model.dataChanged.connect(self.update, AUC)
        except TypeError:
            pass
        try:
            self._model.rowsAboutToBeRemoved.connect(self.rowsAboutToBeRemoved, AUC)
        except TypeError:
            pass

    def setColumn(self, col):
        self._column = col

    def setHighlighting(self, val):
        self._highlighting = val

    def setDefaultBlockFormat(self, bf):
        self._defaultBlockFormat = bf
        if self.highlighter:
            self.highlighter.setDefaultBlockFormat(bf)

    def setCurrentModelIndex(self, index):
        self._indexes = None
        if index.isValid():
            self.setEnabled(True)
            if index.column() != self._column:
                index = index.sibling(index.row(), self._column)
            self._index = index

            self.setPlaceholderText(self._placeholderText)

            if not self._model:
                self.setModel(index.model())

            self.setupEditorForIndex(self._index)
            self.loadFontSettings()
            self.updateText()

        else:
            self._index = QModelIndex()

            self.setPlainText("")
            self.setEnabled(False)

    def setCurrentModelIndexes(self, indexes):
        self._index = None
        self._indexes = []

        for i in indexes:
            if i.isValid():
                self.setEnabled(True)
                if i.column() != self._column:
                    i = i.sibling(i.row(), self._column)
                self._indexes.append(i)

                if not self._model:
                    self.setModel(i.model())

        self.updateText()

    def setupEditorForIndex(self, index):
        # In which model are we editing?
        if type(index.model()) != outlineModel:
            self._textFormat = "text"
            return

        # what type of text are we editing?
        if self._column not in [Outline.text.value, Outline.notes.value]:
            self._textFormat = "text"

        else:
            self._textFormat = "md"

        # Setting highlighter
        if self._highlighting:
            item = index.internalPointer()
            if self._column in [Outline.text.value, Outline.notes.value]:
                self.highlighter = MMDHighlighter(self)
            else:
                self.highlighter = basicHighlighter(self)

            self.highlighter.setDefaultBlockFormat(self._defaultBlockFormat)

    def loadFontSettings(self):
        if self._fromTheme or \
                not self._index or \
                    type(self._index.model()) != outlineModel or \
                    self._column != Outline.text.value:
            return

        opt = settings.textEditor
        f = QFont()
        f.fromString(opt["font"])
        # self.setFont(f)
        self.setStyleSheet("""QTextEdit{{
            background: {bg};
            color: {foreground};
            font-family: {ff};
            font-size: {fs};
            margin: {mTB}px {mLR}px;
            {maxWidth}
            }}
            """.format(
                bg=opt["background"],
                foreground=opt["fontColor"],
                ff=f.family(),
                fs="{}pt".format(str(f.pointSize())),
                mTB = opt["marginsTB"],
                mLR = opt["marginsLR"],
                maxWidth = "max-width: {}px;".format(opt["maxWidth"]) if opt["maxWidth"] else "",
                )
            )

        # We set the parent background to the editor's background in case
        # there are margins. We check that the parent class is a QWidget because
        # if textEditView is used in fullScreenEditor, then we don't want to
        # set the background.
        if self.parent().__class__ == QWidget:
            self.parent().setStyleSheet("""
                QWidget#{name}{{
                    background: {bg};
                }}""".format(
                    # We style by name, otherwise all heriting widgets get the same
                    # colored background, for example context menu.
                    name=self.parent().objectName(),
                    bg=opt["background"],
                ))

        cf = QTextCharFormat()
        # cf.setFont(f)
        # cf.setForeground(QColor(opt["fontColor"]))

        self.setCursorWidth(opt["cursorWidth"])

        bf = QTextBlockFormat()
        bf.setLineHeight(opt["lineSpacing"], bf.ProportionalHeight)
        bf.setTextIndent(opt["tabWidth"] * 1 if opt["indent"] else 0)
        bf.setTopMargin(opt["spacingAbove"])
        bf.setBottomMargin(opt["spacingBelow"])
        bf.setAlignment(Qt.AlignLeft if opt["textAlignment"] == 0 else
                        Qt.AlignCenter if opt["textAlignment"] == 1 else
                        Qt.AlignRight if opt["textAlignment"] == 2 else
                        Qt.AlignJustify)

        self._defaultCharFormat = cf
        self._defaultBlockFormat = bf

        if self.highlighter:
            self.highlighter.setMisspelledColor(QColor(opt["misspelled"]))
            self.highlighter.setDefaultCharFormat(self._defaultCharFormat)
            self.highlighter.setDefaultBlockFormat(self._defaultBlockFormat)

    def update(self, topLeft, bottomRight):
        if self._updating:
            return

        elif self._index and self._index.isValid():
            if topLeft.parent() != self._index.parent():
                return

                # print("Model changed: ({}:{}), ({}:{}/{}), ({}:{}) for {} of {}".format(
                # topLeft.row(), topLeft.column(),
                # self._index.row(), self._index.row(), self._column,
                # bottomRight.row(), bottomRight.column(),
                # self.objectName(), self.parent().objectName()))

            if topLeft.row() <= self._index.row() <= bottomRight.row():
                if topLeft.column() <= self._column <= bottomRight.column():
                    self.updateText()

        elif self._indexes:
            update = False
            for i in self._indexes:
                if topLeft.row() <= i.row() <= bottomRight.row():
                    update = True
            if update:
                self.updateText()

    def rowsAboutToBeRemoved(self, parent, first, last):
        if self._index:
            if self._index.parent() == parent and \
                                    first <= self._index.row() <= last:
                self._index = None
                self.setEnabled(False)
                # FIXME: self._indexes

    def disconnectDocument(self):
        try:
            self.document().contentsChanged.disconnect(self.updateTimer.start)
        except:
            pass

    def reconnectDocument(self):
        self.document().contentsChanged.connect(self.updateTimer.start, AUC)

    def updateText(self):
        if self._updating:
            return
        # print("Updating", self.objectName())
        self._updating = True
        if self._index:
            self.disconnectDocument()
            if self.toPlainText() != toString(self._model.data(self._index)):
                # print("    Updating plaintext")
                self.document().setPlainText(toString(self._model.data(self._index)))
            self.reconnectDocument()

        elif self._indexes:
            self.disconnectDocument()
            t = []
            same = True
            for i in self._indexes:
                item = i.internalPointer()
                t.append(toString(item.data(self._column)))

            for t2 in t[1:]:
                if t2 != t[0]:
                    same = False
                    break

            if same:
                self.document().setPlainText(t[0])
            else:
                self.document().setPlainText("")

                if not self._placeholderText:
                    self._placeholderText = self.placeholderText()

                self.setPlaceholderText(self.tr("Various"))
            self.reconnectDocument()
        self._updating = False

    def submit(self):
        self.updateTimer.stop()
        if self._updating:
            return
        # print("Submitting", self.objectName())
        if self._index and self._index.isValid():
            # item = self._index.internalPointer()
            if self.toPlainText() != self._model.data(self._index):
                # print("    Submitting plain text")
                self._updating = True
                self._model.setData(self._index, self.toPlainText())
                self._updating = False

        elif self._indexes:
            self._updating = True
            for i in self._indexes:
                item = i.internalPointer()
                if self.toPlainText() != toString(item.data(self._column)):
                    print("Submitting many indexes")
                    self._model.setData(i, self.toPlainText())
            self._updating = False

    def keyPressEvent(self, event):
        QTextEdit.keyPressEvent(self, event)
        if event.key() == Qt.Key_Space:
            self.submit()

    # -----------------------------------------------------------------------------------------------------
    # Resize stuff

    def resizeEvent(self, e):
        QTextEdit.resizeEvent(self, e)
        if self._autoResize:
            self.sizeChange()

    def sizeChange(self):
        docHeight = self.document().size().height()
        if self.heightMin <= docHeight <= self.heightMax:
            self.setMinimumHeight(docHeight)

    def setAutoResize(self, val):
        self._autoResize = val
        if self._autoResize:
            self.document().contentsChanged.connect(self.sizeChange)
            self.heightMin = 0
            self.heightMax = 65000
            self.sizeChange()

        ###############################################################################
        # SPELLCHECKING
        ###############################################################################
        # Based on http://john.nachtimwald.com/2009/08/22/qplaintextedit-with-in-line-spell-check/

    def setDict(self, d):
        self.currentDict = d
        self._dict = enchant.Dict(d)
        if self.highlighter:
            self.highlighter.rehighlight()

    def toggleSpellcheck(self, v):
        self.spellcheck = v
        if enchant and self.spellcheck and not self._dict:
            if self.currentDict:
                self._dict = enchant.Dict(self.currentDict)
            elif enchant.dict_exists(enchant.get_default_language()):
                self._dict = enchant.Dict(enchant.get_default_language())
            else:
                self.spellcheck = False

        if self.highlighter:
            self.highlighter.rehighlight()
        else:
            self.spellcheck = False

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            # Rewrite the mouse event to a left button event so the cursor is
            # moved to the location of the pointer.
            event = QMouseEvent(QEvent.MouseButtonPress, event.pos(),
                                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        QTextEdit.mousePressEvent(self, event)

    class SpellAction(QAction):
        """A special QAction that returns the text in a signal. Used for spellckech."""

        correct = pyqtSignal(str)

        def __init__(self, *args):
            QAction.__init__(self, *args)

            self.triggered.connect(lambda x: self.correct.emit(
                    str(self.text())))

    def contextMenuEvent(self, event):
        # Based on http://john.nachtimwald.com/2009/08/22/qplaintextedit-with-in-line-spell-check/
        popup_menu = self.createStandardContextMenu()
        popup_menu.exec_(event.globalPos())

    def createStandardContextMenu(self):
        popup_menu = QTextEdit.createStandardContextMenu(self)

        if not self.spellcheck:
            return popup_menu

        # Select the word under the cursor.
        # But only if there is no selection (otherwise it's impossible to select more text to copy/cut)
        cursor = self.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.WordUnderCursor)
            self.setTextCursor(cursor)

        # Check if the selected word is misspelled and offer spelling
        # suggestions if it is.
        if cursor.hasSelection():
            text = str(cursor.selectedText())
            valid = self._dict.check(text)
            selectedWord = cursor.selectedText()
            if not valid:
                spell_menu = QMenu(self.tr('Spelling Suggestions'), self)
                spell_menu.setIcon(themeIcon("spelling"))
                for word in self._dict.suggest(text):
                    action = self.SpellAction(word, spell_menu)
                    action.correct.connect(self.correctWord)
                    spell_menu.addAction(action)
                # Only add the spelling suggests to the menu if there are
                # suggestions.
                if len(spell_menu.actions()) != 0:
                    popup_menu.insertSeparator(popup_menu.actions()[0])
                    # Adds: add to dictionary
                    addAction = QAction(self.tr("&Add to dictionary"), popup_menu)
                    addAction.setIcon(QIcon.fromTheme("list-add"))
                    addAction.triggered.connect(self.addWordToDict)
                    addAction.setData(selectedWord)
                    popup_menu.insertAction(popup_menu.actions()[0], addAction)
                    # Adds: suggestions
                    popup_menu.insertMenu(popup_menu.actions()[0], spell_menu)
                    # popup_menu.insertSeparator(popup_menu.actions()[0])

            # If word was added to custom dict, give the possibility to remove it
            elif valid and self._dict.is_added(selectedWord):
                popup_menu.insertSeparator(popup_menu.actions()[0])
                # Adds: remove from dictionary
                rmAction = QAction(self.tr("&Remove from custom dictionary"), popup_menu)
                rmAction.setIcon(QIcon.fromTheme("list-remove"))
                rmAction.triggered.connect(self.rmWordFromDict)
                rmAction.setData(selectedWord)
                popup_menu.insertAction(popup_menu.actions()[0], rmAction)

        return popup_menu

    def correctWord(self, word):
        """
        Replaces the selected text with word.
        """
        cursor = self.textCursor()
        cursor.beginEditBlock()

        cursor.removeSelectedText()
        cursor.insertText(word)

        cursor.endEditBlock()

    def addWordToDict(self):
        word = self.sender().data()
        self._dict.add(word)
        self.highlighter.rehighlight()

    def rmWordFromDict(self):
        word = self.sender().data()
        self._dict.remove(word)
        self.highlighter.rehighlight()

    ###############################################################################
    # FORMATTING
    ###############################################################################

    def focusOutEvent(self, event):
        """Submit changes just before focusing out."""
        QTextEdit.focusOutEvent(self, event)
        self.submit()

    def focusInEvent(self, event):
        """Finds textFormatter and attach them to that view."""
        QTextEdit.focusInEvent(self, event)

        p = self.parent()
        while p.parent():
            p = p.parent()

        if self._index:
            for tF in p.findChildren(textFormat, QRegExp(".*"), Qt.FindChildrenRecursively):
                tF.updateFromIndex(self._index)
                tF.setTextEdit(self)

    def applyFormat(self, _format):

        if self._textFormat == "md":

            if _format == "Bold":
                MDFormatSelection(self, 0)
            elif _format == "Italic":
                MDFormatSelection(self, 1)
            elif _format == "Code":
                MDFormatSelection(self, 2)
            elif _format == "Clear":
                MDFormatSelection(self)
