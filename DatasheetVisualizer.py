#!/usr/bin/env python3
# datasheet_visualizer_v5_2_2.py
# VERSION 5.2.2: FIX SCROLLBAR VISIBILITY
# - Fixed: Vertical Scrollbar was hidden by conflicting inline stylesheet.
# - Fixed: Scrollbar policy set to "AlwaysOn" at startup.
# - Base: v5.2 (Native QtPdf, No Search, Compact, Dark Mode).

import sys
import os
import json
from pathlib import Path
from time import monotonic

from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtCore import Qt

# Try to import QtPdf
try:
    from PyQt6.QtPdf import QPdfDocument
    from PyQt6.QtPdfWidgets import QPdfView
except ImportError:
    QPdfDocument = None
    QPdfView = None
    print("CRITICAL: PyQt6-QtPdf not found. Install with: pip install PyQt6-QtPdf")

# --- CONFIGURATION ---
APP_NAME = "DatasheetVisualizer"
CONFIG_DIR = Path(QtCore.QStandardPaths.writableLocation(
    QtCore.QStandardPaths.StandardLocation.AppConfigLocation
)) / APP_NAME
CONFIG_PATH = CONFIG_DIR / "datasheet_config.json"
NOTES_KEY = "notes"
LOAD_TIMEOUT_S = 10.0
POLL_INTERVAL_MS = 100

# --- STYLESHEET (Dark & Clean) ---
STYLESHEET = """
QMainWindow, QDialog { background-color: #2b2b2b; color: #e0e0e0; }
QWidget { font-family: "Segoe UI", sans-serif; font-size: 12px; color: #e0e0e0; }

/* Buttons */
QPushButton {
    background-color: #0078d4; color: white;
    border: 1px solid #0078d4; border-radius: 4px;
    padding: 4px 12px; font-weight: 600;
}
QPushButton:hover { background-color: #298ce1; border-color: #298ce1; }
QPushButton:pressed { background-color: #005a9e; }
QPushButton:disabled { background-color: #3a3a3a; color: #777; border-color: #3a3a3a; }

/* Inputs */
QLineEdit, QSpinBox {
    background-color: #1e1e1e; border: 1px solid #3e3e3e;
    border-radius: 3px; padding: 3px 5px; color: white;
}
QLineEdit:focus, QSpinBox:focus { border: 1px solid #0078d4; background-color: #252525; }

/* Lists & Trees */
QTreeView, QListWidget {
    background-color: #1e1e1e; border: 1px solid #3e3e3e;
    border-radius: 4px; padding: 2px; outline: none;
}
QTreeView::item, QListWidget::item { padding: 3px; border-radius: 2px; color: #cccccc; }
QTreeView::item:hover, QListWidget::item:hover { background-color: #333; }
QTreeView::item:selected, QListWidget::item:selected { background-color: #004c87; color: white; }

/* Splitter */
QSplitter::handle { background-color: #3e3e3e; width: 1px; }
QSplitter::handle:hover { background-color: #0078d4; width: 3px; }

/* --- SCROLLBARS (Forced Visibility) --- */
QScrollBar:vertical {
    border: none;
    background: #2b2b2b; /* Sfondo traccia scuro */
    width: 14px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #666; /* Maniglia grigia visibile */
    min-height: 20px;
    border-radius: 7px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover { background: #888; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

/* Status Bar */
QStatusBar { background-color: #1e1e1e; border-top: 1px solid #3e3e3e; color: #999; }
QLabel { color: #e0e0e0; }

/* PDF View Specific */
QPdfView {
    border: none;
    background-color: #525659;
}
"""

def ensure_config_dir():
    if not CONFIG_DIR.exists():
        try: CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        except OSError: pass

def load_config():
    ensure_config_dir()
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {}

def save_config(cfg):
    ensure_config_dir()
    try: CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError: pass

class NoteDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, text="", page=1, max_page=99999):
        super().__init__(parent)
        self.setWindowTitle("Edit Note")
        self.setFixedWidth(350)
        self._result = None
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)
        
        lbl_text = QtWidgets.QLabel("Note content:")
        lbl_text.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl_text)
        
        self.text_edit = QtWidgets.QLineEdit(text)
        self.text_edit.setPlaceholderText("Enter note text...")
        layout.addWidget(self.text_edit)
        
        h_page = QtWidgets.QHBoxLayout()
        h_page.addWidget(QtWidgets.QLabel("Page:"))
        self.spin = QtWidgets.QSpinBox()
        self.spin.setMinimum(1)
        self.spin.setMaximum(max_page)
        self.spin.setValue(page)
        self.spin.setFixedWidth(80)
        
        h_page.addWidget(self.spin)
        h_page.addStretch()
        layout.addLayout(h_page)
        
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        for btn in buttons.buttons():
            btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        text = self.text_edit.text().strip()
        self._result = {"text": text, "page": self.spin.value()}
        super().accept()

    def result(self): return self._result

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        if QPdfDocument is None or QPdfView is None:
            QtWidgets.QMessageBox.critical(None, "Error", "PyQt6 PDF module missing.\nrun: pip install PyQt6-QtPdf")
            sys.exit(1)

        self.setWindowTitle("Datasheet Explorer")
        self.resize(1100, 750)

        # Icon
        try:
            if getattr(sys, "frozen", False): icon_path = Path(sys._MEIPASS) / "icon.ico"
            else: icon_path = Path(__file__).resolve().parent / "icon.ico"
            if icon_path.exists(): self.setWindowIcon(QtGui.QIcon(str(icon_path)))
        except: pass

        # Config
        self.cfg = load_config()
        self.notes_store = self.cfg.get(NOTES_KEY, {})
        self.root_folder = self.cfg.get("root_folder", "")
        
        # Validazione root
        if self.root_folder and not os.path.isdir(self.root_folder):
            self.root_folder = ""
        if not self.root_folder:
            candidate = os.path.join(os.getcwd(), "data")
            self.root_folder = os.path.abspath(candidate) if os.path.isdir(candidate) else str(Path.home())
            self.cfg["root_folder"] = self.root_folder
            save_config(self.cfg)

        # State vars
        self.pdf_doc = None
        self.pdf_view = None
        self.current_pdf_path = None
        self._pending_doc = None
        self._pending_path = None
        self._pending_start = 0.0

        self.init_ui()
        self._set_tree_root(self.root_folder)

    def init_ui(self):
        main_widget = QtWidgets.QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QtWidgets.QHBoxLayout(main_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setHandleWidth(5)
        main_layout.addWidget(splitter)

        # --- LEFT PANEL ---
        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 5, 0)
        
        # Toolbar
        tb = QtWidgets.QHBoxLayout()
        for label, slot in [("Root", self.select_root), ("Explorer", self.show_in_file_manager), ("Open Ext", self.open_pdf_outside)]:
            btn = QtWidgets.QPushButton(label)
            btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(slot)
            tb.addWidget(btn)
        left_layout.addLayout(tb)

        # Tree
        self.fs_model = QtGui.QFileSystemModel()
        self.fs_model.setFilter(QtCore.QDir.Filter.NoDotAndDotDot | QtCore.QDir.Filter.AllDirs | QtCore.QDir.Filter.Files)
        self.fs_model.setNameFilters(["*.pdf"])
        self.fs_model.setNameFilterDisables(False)

        self.tree = QtWidgets.QTreeView()
        self.tree.setModel(self.fs_model)
        self.tree.setHeaderHidden(False)
        for i in range(1, 4): self.tree.setColumnHidden(i, True)
        self.tree.clicked.connect(self.on_tree_clicked)
        left_layout.addWidget(self.tree, stretch=4)

        # Notes
        lbl = QtWidgets.QLabel("NOTES:")
        lbl.setStyleSheet("color: #aaaaaa; font-weight: bold; margin-top: 5px;")
        left_layout.addWidget(lbl)

        self.notes_list = QtWidgets.QListWidget()
        self.notes_list.setAlternatingRowColors(False)
        self.notes_list.itemClicked.connect(self.on_note_clicked)
        left_layout.addWidget(self.notes_list, stretch=1)
        
        # Note Buttons
        nb = QtWidgets.QHBoxLayout()
        b_add = QtWidgets.QPushButton("Add")
        b_add.clicked.connect(self.add_note)
        b_edit = QtWidgets.QPushButton("Edit")
        b_edit.clicked.connect(self.edit_note)
        b_del = QtWidgets.QPushButton("Del")
        b_del.setStyleSheet("background-color: #a93226; border-color: #a93226; color: white;")
        b_del.clicked.connect(self.remove_note)
        
        nb.addWidget(b_add, 2)
        nb.addWidget(b_edit, 1)
        nb.addWidget(b_del, 1)
        left_layout.addLayout(nb)

        splitter.addWidget(left_widget)

        # --- RIGHT PANEL ---
        right_widget = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0,0,0,0)
        
        # PDF Container (Grey Background)
        pdf_cont = QtWidgets.QWidget()
        pdf_cont.setStyleSheet("background-color: #333333;")
        pc_layout = QtWidgets.QVBoxLayout(pdf_cont)
        pc_layout.setContentsMargins(0,0,0,0)

        # --- FIX: CREAZIONE VIEWER E SCROLLBAR ---
        try:
            self.pdf_view = QPdfView(self)
            # Rimosso stile inline che nascondeva la scrollbar
            # Lo stile è gestito dal CSS globale ora
            self.pdf_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        except:
            self.pdf_view = QtWidgets.QWidget(self)
            
        pc_layout.addWidget(self.pdf_view)
        right_layout.addWidget(pdf_cont)
        
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(1, 3)

        # Status Bar
        self.status = self.statusBar()
        self.status_lbl = QtWidgets.QLabel("Ready")
        self.status_lbl.setStyleSheet("padding: 0 10px; color: #999;")
        self.status.addWidget(self.status_lbl)

        # Shortcuts
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl++"), self).activated.connect(self.zoom_in)
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+-"), self).activated.connect(self.zoom_out)
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+0"), self).activated.connect(self.zoom_reset)

        # Timer
        self._load_timer = QtCore.QTimer(self)
        self._load_timer.setInterval(POLL_INTERVAL_MS)
        self._load_timer.timeout.connect(self._poll_load_status)

        try:
            vsb = self.pdf_view.verticalScrollBar()
            if vsb: vsb.valueChanged.connect(self.update_status_page)
        except: pass

    # --- LOGIC ---

    def select_root(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Root", self.root_folder)
        if d:
            self.root_folder = os.path.abspath(d)
            self.cfg["root_folder"] = self.root_folder
            save_config(self.cfg)
            self._set_tree_root(self.root_folder)

    def _set_tree_root(self, path):
        self.tree.setRootIndex(self.fs_model.setRootPath(path or str(Path.home())))

    def show_in_file_manager(self):
        target = self.root_folder if os.path.isdir(self.root_folder) else os.getcwd()
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(target))

    def on_tree_clicked(self, idx):
        path = self.fs_model.filePath(idx)
        if path and path.lower().endswith(".pdf") and os.path.isfile(path):
            self.open_pdf(path)

    def open_pdf_outside(self):
        if not self.current_pdf_path: return
        url = QtCore.QUrl.fromLocalFile(self.current_pdf_path)
        QtGui.QDesktopServices.openUrl(url)

    # --- PDF LOADING ---

    def open_pdf(self, path):
        abs_path = os.path.abspath(path)
        self._load_timer.stop()
        if self._pending_doc:
            try: self._pending_doc.deleteLater()
            except: pass
            self._pending_doc = None

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        self.status_lbl.setText(f"Loading: {os.path.basename(abs_path)}...")

        new_doc = QPdfDocument(self)
        self._pending_doc = new_doc
        self._pending_path = abs_path
        self._pending_start = monotonic()

        try:
            status = new_doc.load(abs_path)
            if status == QPdfDocument.Status.Ready:
                self._finalize_doc(new_doc, abs_path)
            else:
                self._load_timer.start()
        except Exception as e:
            self._reset_cursor()
            QtWidgets.QMessageBox.critical(self, "Error", f"Load failed: {e}")

    def _poll_load_status(self):
        doc = self._pending_doc
        if not doc:
            self._load_timer.stop()
            self._reset_cursor()
            return
        
        status = doc.status()
        if status == QPdfDocument.Status.Ready:
            self._load_timer.stop()
            self._finalize_doc(doc, self._pending_path)
        elif status == QPdfDocument.Status.Error:
            self._load_timer.stop()
            self._reset_cursor()
            self._pending_doc = None
            QtWidgets.QMessageBox.warning(self, "Error", "Failed to load PDF.")
        elif monotonic() - self._pending_start > LOAD_TIMEOUT_S:
            self._load_timer.stop()
            self._reset_cursor()
            doc.deleteLater()
            self._pending_doc = None
            self.status_lbl.setText("Timeout loading PDF.")

    def _finalize_doc(self, new_doc, abs_path):
        if self.pdf_doc: self.pdf_doc.deleteLater()
        self.pdf_doc = new_doc
        self.pdf_view.setDocument(self.pdf_doc)
        
        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        # Assicurati che la scrollbar sia visibile
        self.pdf_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        
        self.current_pdf_path = abs_path
        self._pending_doc = None
        self._reset_cursor()
        self.status_lbl.setText(f"Open: {os.path.basename(abs_path)}")
        
        self.load_notes()
        self.update_status_page()
        self.pdf_view.setFocus()

    def _reset_cursor(self):
        QtWidgets.QApplication.restoreOverrideCursor()

    # --- ZOOM (Anchored) ---

    def _apply_zoom(self, mult):
        if not self.pdf_view or not self.pdf_doc: return
        vsb = self.pdf_view.verticalScrollBar()
        ratio = vsb.value() / vsb.maximum() if vsb.maximum() > 0 else 0
        
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
        new_zoom = max(0.1, self.pdf_view.zoomFactor() * mult)
        self.pdf_view.setZoomFactor(new_zoom)
        
        QtWidgets.QApplication.processEvents() 
        if vsb.maximum() > 0:
            vsb.setValue(int(ratio * vsb.maximum()))

    def zoom_in(self): self._apply_zoom(1.25)
    def zoom_out(self): self._apply_zoom(0.8)
    def zoom_reset(self): 
        if self.pdf_view: self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

    # --- NOTES ---

    def _get_key(self, path):
        if not path or not self.root_folder: return path
        try:
            return os.path.relpath(path, self.root_folder)
        except ValueError:
            return path 

    def load_notes(self):
        self.notes_list.clear()
        if not self.current_pdf_path: return
        
        key = self._get_key(self.current_pdf_path)
        notes = self.notes_store.get(key) or self.notes_store.get(self.current_pdf_path, [])
        
        for n in notes:
            self.notes_list.addItem(f"[P.{n['page']}] {n['text']}")

    def save_notes_to_disk(self):
        self.cfg[NOTES_KEY] = self.notes_store
        save_config(self.cfg)

    def add_note(self):
        if not self.current_pdf_path or not self.pdf_doc: return
        dlg = NoteDialog(self, max_page=self.pdf_doc.pageCount())
        if dlg.exec():
            res = dlg.result()
            key = self._get_key(self.current_pdf_path)
            self.notes_store.setdefault(key, []).append(res)
            self.save_notes_to_disk()
            self.load_notes()

    def edit_note(self):
        row = self.notes_list.currentRow()
        if row < 0 or not self.current_pdf_path: return
        
        key = self._get_key(self.current_pdf_path)
        if key not in self.notes_store: key = self.current_pdf_path 
        
        current = self.notes_store.get(key, [])
        if row >= len(current): return
        
        note = current[row]
        max_p = self.pdf_doc.pageCount() if self.pdf_doc else 999
        dlg = NoteDialog(self, text=note['text'], page=note['page'], max_page=max_p)
        
        if dlg.exec():
            self.notes_store[key][row] = dlg.result()
            self.save_notes_to_disk()
            self.load_notes()

    def remove_note(self):
        row = self.notes_list.currentRow()
        if row < 0 or not self.current_pdf_path: return
        
        key = self._get_key(self.current_pdf_path)
        if key not in self.notes_store: key = self.current_pdf_path
        
        if key in self.notes_store and row < len(self.notes_store[key]):
            self.notes_store[key].pop(row)
            if not self.notes_store[key]: del self.notes_store[key]
            self.save_notes_to_disk()
            self.load_notes()

    def on_note_clicked(self, item):
        row = self.notes_list.row(item)
        if not self.current_pdf_path: return
        
        key = self._get_key(self.current_pdf_path)
        if key not in self.notes_store: key = self.current_pdf_path
        
        notes = self.notes_store.get(key, [])
        if row < len(notes) and self.pdf_view.pageNavigator():
            page_idx = max(0, notes[row]['page'] - 1)
            self.pdf_view.pageNavigator().jump(page_idx, QtCore.QPointF(0,0), self.pdf_view.zoomFactor())

    def update_status_page(self):
        if not self.pdf_doc: return
        total = self.pdf_doc.pageCount()
        if total <= 0: return 
        
        vsb = self.pdf_view.verticalScrollBar()
        if vsb.maximum() > 0:
            curr = int((vsb.value() / vsb.maximum()) * total) + 1
        else: curr = 1
        
        name = os.path.basename(self.current_pdf_path or "")
        self.status_lbl.setText(f"Page {min(curr, total)} / {total} — {name}")

def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    win = MainWindow()
    win.showMaximized()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()