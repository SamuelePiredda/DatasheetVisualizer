#!/usr/bin/env python3
# datasheet_qtpdf_dark.py
# PDF viewer based on PyQt6 + QtPdf
#
# VERSION 5: DARK MODE EDITION
# - Dark Backgrounds (#2b2b2b)
# - Light Text (#e0e0e0)
# - Custom Dark Scrollbars
# - Retains compact layout and optimizations from V4

import sys
import os
import json
from pathlib import Path
from time import monotonic
from tkinter import E

from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QScrollArea

# Try to import QtPdf
try:
    from PyQt6.QtPdf import QPdfDocument
    from PyQt6.QtPdfWidgets import QPdfView
except ImportError:
    QPdfDocument = None
    QPdfView = None

# --- CONFIGURATION ---
APP_NAME = "DatasheetVisualizer"
CONFIG_DIR = Path(QtCore.QStandardPaths.writableLocation(
    QtCore.QStandardPaths.StandardLocation.AppConfigLocation
)) / APP_NAME
CONFIG_PATH = CONFIG_DIR / "datasheet_config.json"
NOTES_KEY = "notes"
LOAD_TIMEOUT_S = 10.0
POLL_INTERVAL_MS = 100

# --- DARK & MODERN STYLESHEET ---
STYLESHEET = """
QMainWindow, QDialog {
    background-color: #2b2b2b; /* Grigio Scuro Sfondo */
    color: #e0e0e0; /* Testo Chiaro */
}

QWidget {
    font-family: "Segoe UI", "Roboto", "Helvetica Neue", sans-serif;
    font-size: 12px;
    color: #e0e0e0;
}

/* --- BOTTONI --- */
QPushButton {
    background-color: #0078d4; /* Blu Microsoft */
    color: white;
    border: 1px solid #0078d4;
    border-radius: 4px;
    padding: 4px 12px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #298ce1;
    border-color: #298ce1;
}
QPushButton:pressed {
    background-color: #005a9e;
    border-color: #005a9e;
    padding-top: 5px;
    padding-bottom: 3px;
}
QPushButton:disabled {
    background-color: #3a3a3a;
    color: #777;
    border: 1px solid #3a3a3a;
}

/* --- INPUT & SPINBOX --- */
QLineEdit, QSpinBox {
    background-color: #1e1e1e; /* Nero/Grigio profondo */
    border: 1px solid #3e3e3e;
    border-radius: 3px;
    padding: 3px 5px;
    color: white;
}
QLineEdit:focus, QSpinBox:focus {
    border: 1px solid #0078d4;
    background-color: #252525;
}

/* --- LISTE E ALBERI --- */
QTreeView, QListWidget {
    background-color: #1e1e1e;
    border: 1px solid #3e3e3e;
    border-radius: 4px;
    padding: 2px;
    outline: none;
}
QTreeView::item, QListWidget::item {
    padding: 3px;
    border-radius: 2px;
    color: #cccccc;
}
QTreeView::item:hover, QListWidget::item:hover {
    background-color: #333333;
}
QTreeView::item:selected, QListWidget::item:selected {
    background-color: #004c87; /* Blu scuro per selezione */
    color: #ffffff;
    border: none;
}

/* --- SPLITTER --- */
QSplitter::handle {
    background-color: #3e3e3e;
    width: 1px;
}
QSplitter::handle:hover {
    background-color: #0078d4;
    width: 3px;
}

/* --- SCROLLBARS (Dark Style) --- */
QScrollBar:vertical {
    border: none;
    background: #e1e1e1;
    width: 15px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #555;
    min-height: 20px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #777;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* --- STATUS BAR --- */
QStatusBar {
    background-color: #1e1e1e;
    border-top: 1px solid #3e3e3e;
    color: #999;
}
QQLabel {
    color: #e0e0e0;
}
"""

def ensure_config_dir():
    if not CONFIG_DIR.exists():
        try: CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        except: pass

def load_config():
    ensure_config_dir()
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except: pass
    return {}

def save_config(cfg):
    ensure_config_dir()
    try: CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except: pass

class NoteDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, text="", page=1, max_page=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Note")
        self.setFixedWidth(350)
        self._result = None
        self.max_page = max_page or 99999
        self.setModal(True)
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)
        
        lbl_text = QtWidgets.QLabel("Note content:")
        lbl_text.setStyleSheet("font-weight: bold; color: #e0e0e0;")
        layout.addWidget(lbl_text)
        
        self.text_edit = QtWidgets.QLineEdit(text)
        self.text_edit.setPlaceholderText("Enter note text...")
        layout.addWidget(self.text_edit)
        
        h_page = QtWidgets.QHBoxLayout()
        lbl_page = QtWidgets.QLabel("Page:")
        lbl_page.setStyleSheet("color: #cccccc;")
        self.spin = QtWidgets.QSpinBox()
        self.spin.setMinimum(1)
        self.spin.setMaximum(self.max_page)
        self.spin.setValue(page)
        self.spin.setFixedWidth(80)
        
        h_page.addWidget(lbl_page)
        h_page.addWidget(self.spin)
        h_page.addStretch()
        layout.addLayout(h_page)
        
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        # Stilizzazione bottoni dialog interni
        for btn in buttons.buttons():
            btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        text = self.text_edit.text().strip()
        page = max(1, min(self.spin.value(), self.max_page))
        self._result = {"text": text, "page": page}
        super().accept()

    def result(self):
        return self._result

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        if QPdfDocument is None or QPdfView is None:
            QtWidgets.QMessageBox.critical(None, "Error", "PyQt6 PDF module missing.")
            sys.exit(1)

        self.setWindowTitle("Datasheet Explorer")
        self.setWindowIcon(QIcon("icon.ico"))
        self.resize(1100, 750)

        try:
            if getattr(sys, "frozen", False):
                icon_path = Path(sys._MEIPASS) / "icon.ico"
            else:
                icon_path = Path(__file__).resolve().parent / "icon.ico"
            if icon_path.exists():
                self.setWindowIcon(QtGui.QIcon(str(icon_path)))
        except: pass

        self.cfg = load_config()
        self.notes_store = self.cfg.get(NOTES_KEY, {})
        self.root_folder = self.cfg.get("root_folder", "")
        
        if self.root_folder and not os.path.isdir(self.root_folder):
            self.root_folder = ""
        if not self.root_folder:
            candidate = os.path.join(os.getcwd(), "data")
            if os.path.isdir(candidate):
                self.root_folder = os.path.abspath(candidate)
                self.cfg["root_folder"] = self.root_folder
                save_config(self.cfg)

        self.pdf_doc = None
        self.pdf_view = None
        self.current_pdf_path = None
        self._pending_doc = None
        self._pending_path = None
        self._pending_start = 0.0

        # --- MAIN LAYOUT ---
        main_widget = QtWidgets.QWidget()
        main_layout = QtWidgets.QHBoxLayout(main_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        self.setCentralWidget(main_widget)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setHandleWidth(5)
        main_layout.addWidget(splitter)

        # --- LEFT PANEL ---
        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 5, 0)
        left_layout.setSpacing(6)

        # Toolbar
        toolbar = QtWidgets.QHBoxLayout()
        btn_root = QtWidgets.QPushButton("Root Folder")
        btn_root.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        btn_root.clicked.connect(self.select_root)
        toolbar.addWidget(btn_root)

        btn_show = QtWidgets.QPushButton("Explorer")
        btn_show.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        btn_show.clicked.connect(self.show_root_in_file_manager)
        toolbar.addWidget(btn_show)


        btn_openpdf = QtWidgets.QPushButton("Open")
        btn_openpdf.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        btn_openpdf.clicked.connect(self.open_pdf_outside)
        toolbar.addWidget(btn_openpdf)
        left_layout.addLayout(toolbar)

        # Tree View
        self.fs_model = QtGui.QFileSystemModel()
        self.fs_model.setFilter(QtCore.QDir.Filter.NoDotAndDotDot | QtCore.QDir.Filter.AllDirs | QtCore.QDir.Filter.Files)
        self.fs_model.setNameFilters(["*.pdf"])
        self.fs_model.setNameFilterDisables(False)

        self.tree = QtWidgets.QTreeView()
        self.tree.setModel(self.fs_model)
        self.tree.setHeaderHidden(False)
        self.tree.setColumnHidden(1, True)
        self.tree.setColumnHidden(2, True)
        self.tree.setColumnHidden(3, True)
        self.tree.clicked.connect(self.on_tree_clicked)
        
        # STRETCH: 80% Tree
        left_layout.addWidget(self.tree, stretch=4)

        # Notes Label
        lbl_notes = QtWidgets.QLabel("NOTES:")
        # Adjusted color for Dark Mode
        lbl_notes.setStyleSheet("color: #aaaaaa; font-weight: bold; font-size: 11px; margin-top: 5px;")
        left_layout.addWidget(lbl_notes)

        self.notes_list = QtWidgets.QListWidget()
        self.notes_list.setAlternatingRowColors(False) # Disable alternating for cleaner dark look
        self.notes_list.itemClicked.connect(self.on_note_clicked)
        
        # STRETCH: 20% Notes
        left_layout.addWidget(self.notes_list, stretch=1)
        
        # Notes Buttons
        btns = QtWidgets.QWidget()
        btns_h = QtWidgets.QHBoxLayout(btns)
        btns_h.setContentsMargins(0,0,0,0)
        btns_h.setSpacing(5)
        
        btn_add = QtWidgets.QPushButton("Add")
        btn_add.clicked.connect(self.add_note)
        btn_add.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

        
        btn_edit = QtWidgets.QPushButton("Edit")
        btn_edit.clicked.connect(self.edit_note)
        btn_edit.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        
        btn_del = QtWidgets.QPushButton("Del")
        btn_del.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        # Darker red for dark mode
        btn_del.setStyleSheet("background-color: #a93226; border-color: #a93226; color: white;")
        btn_del.clicked.connect(self.remove_note)
        
        btns_h.addWidget(btn_add, 2)
        btns_h.addWidget(btn_edit, 1)
        btns_h.addWidget(btn_del, 1)
        left_layout.addWidget(btns, stretch=0)

        splitter.addWidget(left_widget)

        # --- RIGHT PANEL ---
        right_widget = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0,0,0,0)
        
        # PDF Container Background (Dark Grey for "Empty" space)
        pdf_container = QtWidgets.QWidget()
        pdf_container.setStyleSheet("background-color: #333333;") 
        pdf_layout = QtWidgets.QVBoxLayout(pdf_container)
        pdf_layout.setContentsMargins(0,0,0,0)

        try:
            self.pdf_view = QPdfView(self)
            # Ensure the PDF View widget itself doesn't have a white border
            self.pdf_view.setStyleSheet("border: none; background-color: #525659;")


        except:
            self.pdf_view = QtWidgets.QWidget(self)
            
        pdf_layout.addWidget(self.pdf_view)
        right_layout.addWidget(pdf_container)
        
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(1, 3)

        # Status Bar
        self.status = self.statusBar()
        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setStyleSheet("padding: 0 10px; color: #999;")
        self.status.addWidget(self.status_label)

        # --- CORREZIONE: Usa QtGui.QShortcut invece di QtWidgets.QShortcut ---
        self.zoom_in_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl++"), self)
        self.zoom_in_shortcut.activated.connect(self.zoom_in)

        self.zoom_out_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+-"), self)
        self.zoom_out_shortcut.activated.connect(self.zoom_out)
        # ---------------------------------------------

        self._load_timer = QtCore.QTimer(self)
        self._load_timer.setInterval(POLL_INTERVAL_MS)
        self._load_timer.timeout.connect(self._poll_load_status)

        try:
            vsb = self.pdf_view.verticalScrollBar()
            if vsb: vsb.valueChanged.connect(self.update_status_page)
        except: pass

        if self.root_folder and os.path.isdir(self.root_folder):
            self._set_tree_root(self.root_folder)
        else:
            self.status_label.setText("Welcome. Select a root folder.")


    def select_root(self):
        start_dir = self.root_folder or str(Path.home())
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Root", start_dir)
        if folder:
            self.root_folder = os.path.abspath(folder)
            self.cfg["root_folder"] = self.root_folder
            save_config(self.cfg)
            self._set_tree_root(self.root_folder)

    def open_pdf_outside(self):
        if not self.current_pdf_path or not self.pdf_doc: return
        try:
            os.startfile(self.current_pdf_path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Could not open file: {e}")

# --- FUNZIONALITÀ ZOOM ---
    def zoom_in(self):
        if not self.pdf_view or self.pdf_doc is None: return
        
        # 1. Sblocca lo zoom automatico (FitToWidth) passando a Custom
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
        
        # 2. Calcola e applica il nuovo zoom
        current_zoom = self.pdf_view.zoomFactor()
        new_zoom = current_zoom * 1.25
        self.pdf_view.setZoomFactor(new_zoom)

    def zoom_out(self):
        if not self.pdf_view or self.pdf_doc is None: return
        
        # 1. Sblocca lo zoom automatico
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
        
        # 2. Calcola e applica il nuovo zoom
        current_zoom = self.pdf_view.zoomFactor()
        new_zoom = current_zoom / 1.25
        
        if new_zoom < 0.1:
            new_zoom = 0.1
        self.pdf_view.setZoomFactor(new_zoom)
    # -------------------------------


    def _set_tree_root(self, path):
        root_idx = self.fs_model.setRootPath(path)
        self.tree.setRootIndex(root_idx)

    def on_tree_clicked(self, index: QtCore.QModelIndex):
        path = self.fs_model.filePath(index)
        if path and os.path.isfile(path) and path.lower().endswith(".pdf"):
            self.open_pdf(path)

    def show_root_in_file_manager(self):
        target = self.root_folder if (self.root_folder and os.path.isdir(self.root_folder)) else os.getcwd()
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(target))

    def open_pdf(self, path: str):
        abs_path = os.path.abspath(path)
        self._load_timer.stop()
        if self._pending_doc:
            try: self._pending_doc.deleteLater()
            except: pass
            self._pending_doc = None

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        self.status_label.setText(f"Loading: {os.path.basename(abs_path)}...")

        new_doc = QPdfDocument(self)
        self._pending_doc = new_doc
        self._pending_path = abs_path
        self._pending_start = monotonic()

        try:
            status = new_doc.load(abs_path)
        except Exception as e:
            self._reset_ui_cursor()
            QtWidgets.QMessageBox.critical(self, "Error", f"Load failed: {e}")
            return

        if status == QPdfDocument.Status.Ready:
            self._finalize_new_doc(new_doc, abs_path)
        else:
            self._load_timer.start()

    def _poll_load_status(self):
        doc = self._pending_doc
        if not doc:
            self._load_timer.stop()
            self._reset_ui_cursor()
            return
        status = doc.status()
        if status == QPdfDocument.Status.Ready:
            self._load_timer.stop()
            self._finalize_new_doc(doc, self._pending_path)
        elif status == QPdfDocument.Status.Error:
            self._load_timer.stop()
            self._reset_ui_cursor()
            self._pending_doc = None
        elif monotonic() - self._pending_start > LOAD_TIMEOUT_S:
            self._load_timer.stop()
            self._reset_ui_cursor()
            doc.deleteLater()
            self._pending_doc = None

    def _finalize_new_doc(self, new_doc, abs_path):
        old_doc = self.pdf_doc
        self.pdf_doc = new_doc
        self.pdf_view.setDocument(self.pdf_doc)
        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.pdf_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.pdf_view.verticalScrollBar().setStyleSheet("background-color: #e1e1e1;")

        if old_doc: old_doc.deleteLater()
        self.current_pdf_path = abs_path
        self._pending_doc = None
        self._reset_ui_cursor()
        self.status_label.setText(f"Opened: {os.path.basename(abs_path)}")
        self.load_notes_for_current_pdf()
        self.update_status_page()

    def _reset_ui_cursor(self):
        QtWidgets.QApplication.restoreOverrideCursor()

    def update_status_page(self):
        if not self.pdf_doc or self.pdf_doc.pageCount() == 0: return
        total = self.pdf_doc.pageCount()
        try:
            vsb = self.pdf_view.verticalScrollBar()
            if vsb and vsb.maximum() > 0:
                current = int((vsb.value() / vsb.maximum()) * total) + 1
            else: current = 1
        except: current = 1
        self.status_label.setText(f"Page {min(max(1, current), total)} / {total} — {os.path.basename(self.current_pdf_path or '')}")

    def _get_store_key(self, path):
        if not path or not self.root_folder: return path
        try: return os.path.relpath(path, self.root_folder)
        except ValueError: return path

    def load_notes_for_current_pdf(self):
        self.notes_list.clear()
        if not self.current_pdf_path: return
        key = self._get_store_key(self.current_pdf_path)
        notes = self.notes_store.get(key) or self.notes_store.get(self.current_pdf_path, [])
        for n in notes:
            self.notes_list.addItem(f"[P.{n['page']}] {n['text']}")

    def _save_notes_store(self):
        self.cfg[NOTES_KEY] = self.notes_store
        save_config(self.cfg)

    def add_note(self):
        if not self.current_pdf_path or not self.pdf_doc: return
        dlg = NoteDialog(self, text="", page=1, max_page=self.pdf_doc.pageCount())
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            res = dlg.result()
            if res:
                key = self._get_store_key(self.current_pdf_path)
                self.notes_store.setdefault(key, []).append(res)
                self._save_notes_store()
                self.load_notes_for_current_pdf()

    def edit_note(self):
        if not self.current_pdf_path: return
        row = self.notes_list.currentRow()
        if row < 0: return
        key = self._get_store_key(self.current_pdf_path)
        if key not in self.notes_store and self.current_pdf_path in self.notes_store: key = self.current_pdf_path
        current_notes = self.notes_store.get(key, [])
        if row >= len(current_notes): return
        note_data = current_notes[row]
        dlg = NoteDialog(self, text=note_data["text"], page=note_data["page"], max_page=(self.pdf_doc.pageCount() if self.pdf_doc else 9999))
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            res = dlg.result()
            if res:
                self.notes_store[key][row] = res
                self._save_notes_store()
                self.load_notes_for_current_pdf()

    def remove_note(self):
        if not self.current_pdf_path: return
        row = self.notes_list.currentRow()
        if row < 0: return
        key = self._get_store_key(self.current_pdf_path)
        if key not in self.notes_store and self.current_pdf_path in self.notes_store: key = self.current_pdf_path
        if key in self.notes_store:
            self.notes_store[key].pop(row)
            if not self.notes_store[key]: del self.notes_store[key]
            self._save_notes_store()
            self.load_notes_for_current_pdf()

    def on_note_clicked(self, item):
        if not self.current_pdf_path or not self.pdf_doc: return
        row = self.notes_list.row(item)
        key = self._get_store_key(self.current_pdf_path)
        if key not in self.notes_store and self.current_pdf_path in self.notes_store: key = self.current_pdf_path
        notes = self.notes_store.get(key, [])
        if 0 <= row < len(notes):
            page = notes[row]["page"]
            total = self.pdf_doc.pageCount()
            if total > 0:
                vsb = self.pdf_view.verticalScrollBar()
                if vsb: vsb.setValue(int(((page - 1) / total) * vsb.maximum()))

def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion") # Fusion è un ottimo punto di partenza per il theming manuale
    app.setStyleSheet(STYLESHEET)
    win = MainWindow()
    win.showMaximized()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()