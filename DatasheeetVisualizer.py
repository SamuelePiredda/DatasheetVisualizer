#!/usr/bin/env python3
# datasheet_qtpdf.py
# PDF viewer based on PyQt6 + QtPdf
# Features:
# - window maximized on startup (showMaximized)
# - window and taskbar icon compatible with PyInstaller (uses sys._MEIPASS)
# - file tree collapsed on startup
# - persistent notes saved in datasheet_config.json next to the executable
# - robust PDF opening with polling
# - "Show" button opens file manager at the configured root

import sys
import os
import json
import subprocess
from pathlib import Path
from time import monotonic

from PyQt6 import QtCore, QtWidgets, QtGui

# try to import QtPdf; show clear error if missing
try:
    from PyQt6.QtPdf import QPdfDocument
    from PyQt6.QtPdfWidgets import QPdfView
except Exception:
    QPdfDocument = None
    QPdfView = None

# BASE_DIR: folder where the script or the PyInstaller bundle resides
if getattr(sys, "frozen", False):
    # in onefile PyInstaller, resources are extracted to sys._MEIPASS
    BASE_DIR = Path(sys._MEIPASS)
    CONFIG_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
    CONFIG_DIR = BASE_DIR

CONFIG_PATH = CONFIG_DIR / "datasheet_config.json"
NOTES_KEY = "notes"
SUPPORTED_EXTS = (".pdf",)
LOAD_TIMEOUT_S = 12.0
POLL_INTERVAL_MS = 150

def load_config():
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def save_config(cfg):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass

class NoteDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, text="", page=1, max_page=None):
        super().__init__(parent)
        self.setWindowTitle("Note")
        self._result = None
        self.max_page = max_page or 99999
        self.setModal(True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Note text:"))
        self.text_edit = QtWidgets.QLineEdit(text)
        layout.addWidget(self.text_edit)
        h = QtWidgets.QHBoxLayout()
        h.addWidget(QtWidgets.QLabel("Page (1-based):"))
        self.spin = QtWidgets.QSpinBox()
        self.spin.setMinimum(1)
        self.spin.setMaximum(self.max_page)
        self.spin.setValue(page)
        h.addWidget(self.spin)
        layout.addLayout(h)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
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
            QtWidgets.QMessageBox.critical(
                None,
                "Missing dependency",
                "The QtPdf module is not available in your PyQt6 installation.\n"
                "Install PyQt6 (pip install PyQt6) or use a distribution that provides QtPdf."
            )
            sys.exit(1)

        self.setWindowTitle("Datasheet Explorer — QtPdf")
        # set icon robustly for both script and PyInstaller executable
        try:
            if getattr(sys, "frozen", False):
                icon_path = Path(sys._MEIPASS) / "icon.ico"
            else:
                icon_path = BASE_DIR / "icon.ico"
            if icon_path.exists():
                self.setWindowIcon(QtGui.QIcon(str(icon_path)))
        except Exception:
            pass

        # configuration and notes store
        self.cfg = load_config()
        self.notes_store = self.cfg.get(NOTES_KEY, {})
        self.root_folder = self.cfg.get("root_folder", "")

        # if root invalid, look for ./data and set it automatically if present
        if not self.root_folder or not os.path.isdir(self.root_folder):
            candidate = os.path.join(os.getcwd(), "data")
            if os.path.isdir(candidate):
                self.root_folder = os.path.abspath(candidate)
                self.cfg["root_folder"] = self.root_folder
                save_config(self.cfg)
            else:
                self.root_folder = ""

        # pre-initialize attributes to avoid AttributeError
        self.pdf_doc = None
        self.pdf_view = None
        self.current_pdf_path = None
        self._pending_doc = None
        self._pending_path = None
        self._pending_start = 0.0

        # main UI: horizontal splitter
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # left panel: toolbar, tree, notes
        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        left_layout.setContentsMargins(6,6,6,6)

        toolbar = QtWidgets.QHBoxLayout()
        # Root button
        btn_root = QtWidgets.QPushButton("Root")
        btn_root.clicked.connect(self.select_root)
        toolbar.addWidget(btn_root)

        # Show button (opens file manager at root)
        btn_show = QtWidgets.QPushButton("Show")
        btn_show.clicked.connect(self.show_root_in_file_manager)
        toolbar.addWidget(btn_show)

        # Refresh button
        btn_refresh = QtWidgets.QPushButton("Refresh")
        btn_refresh.clicked.connect(self.build_tree)
        toolbar.addWidget(btn_refresh)

        left_layout.addLayout(toolbar)
        left_layout.addSpacing(6)

        self.model = QtGui.QStandardItemModel()
        self.model.setHorizontalHeaderLabels(["Files"])
        self.tree = QtWidgets.QTreeView()
        self.tree.setModel(self.model)
        self.tree.setHeaderHidden(True)
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.clicked.connect(self.on_tree_clicked)
        left_layout.addWidget(self.tree, stretch=1)

        left_layout.addWidget(QtWidgets.QLabel("Notes (selected PDF):"))
        notes_box = QtWidgets.QWidget()
        notes_layout = QtWidgets.QVBoxLayout(notes_box)
        notes_layout.setContentsMargins(0,0,0,0)
        self.notes_list = QtWidgets.QListWidget()
        self.notes_list.itemClicked.connect(self.on_note_clicked)
        notes_layout.addWidget(self.notes_list)
        btns = QtWidgets.QWidget()
        btns_h = QtWidgets.QHBoxLayout(btns)
        btn_add = QtWidgets.QPushButton("Add"); btn_add.clicked.connect(self.add_note)
        btn_edit = QtWidgets.QPushButton("Edit"); btn_edit.clicked.connect(self.edit_note)
        btn_del = QtWidgets.QPushButton("Remove"); btn_del.clicked.connect(self.remove_note)
        btns_h.addWidget(btn_add); btns_h.addWidget(btn_edit); btns_h.addWidget(btn_del)
        notes_layout.addWidget(btns, stretch=0)
        left_layout.addWidget(notes_box, stretch=0)

        splitter.addWidget(left_widget)

        # right panel: PDF view
        right_widget = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_widget)
        right_layout.setContentsMargins(6,6,6,6)

        # create QPdfView and keep it referenced
        try:
            self.pdf_view = QPdfView(self)
        except Exception:
            # fallback: create an empty widget so the UI doesn't break
            self.pdf_view = QtWidgets.QWidget(self)
        right_layout.addWidget(self.pdf_view, stretch=1)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(1,1)

        # status bar
        self.status = self.statusBar()
        self.status_label = QtWidgets.QLabel("Ready")
        self.status.addWidget(self.status_label)

        # timers: polling for load and status updates
        self._load_timer = QtCore.QTimer(self)
        self._load_timer.setInterval(POLL_INTERVAL_MS)
        self._load_timer.timeout.connect(self._poll_load_status)

        self._status_timer = QtCore.QTimer(self)
        self._status_timer.setInterval(200)
        self._status_timer.timeout.connect(self.update_status_page)
        self._status_timer.start()

        # connect scrollbar if available to update page status
        try:
            vsb = self.pdf_view.verticalScrollBar()
            if vsb is not None:
                vsb.valueChanged.connect(self.update_status_page)
        except Exception:
            pass

        # populate tree (collapsed)
        if self.root_folder and os.path.isdir(self.root_folder):
            self.build_tree()
        else:
            self.select_root(initial=True)

    # ---------- open file manager at root ----------
    def show_root_in_file_manager(self):
        if not self.root_folder or not os.path.isdir(self.root_folder):
            QtWidgets.QMessageBox.information(self, "Info", "Root folder is not set or not found.")
            return
        try:
            # cross-platform: QDesktopServices.openUrl
            url = QtCore.QUrl.fromLocalFile(str(self.root_folder))
            QtGui.QDesktopServices.openUrl(url)
        except Exception:
            # fallback platform-specific
            try:
                if sys.platform.startswith("win"):
                    os.startfile(self.root_folder)
                elif sys.platform.startswith("darwin"):
                    subprocess.Popen(["open", self.root_folder])
                else:
                    subprocess.Popen(["xdg-open", self.root_folder])
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Error", f"Unable to open file manager: {e}")

    # ---------- folder / tree ----------
    def select_root(self, initial=False):
        start_dir = self.root_folder or str(Path.cwd())
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Select root folder", start_dir)
        if folder:
            self.root_folder = os.path.abspath(folder)
            self.cfg["root_folder"] = self.root_folder
            save_config(self.cfg)
            self.build_tree()
        elif initial:
            self.status_label.setText("No folder selected. Use Root to set it.")

    def build_tree(self):
        self.model.removeRows(0, self.model.rowCount())
        if not self.root_folder or not os.path.isdir(self.root_folder):
            return
        root_item = QtGui.QStandardItem(os.path.basename(self.root_folder) or self.root_folder)
        root_item.setEditable(False)
        self.model.appendRow(root_item)
        for dirpath, dirnames, filenames in os.walk(self.root_folder):
            rel = os.path.relpath(dirpath, self.root_folder)
            parent = root_item
            if rel != ".":
                parts = rel.split(os.sep)
                acc = self.root_folder
                for p in parts:
                    acc = os.path.join(acc, p)
                    found = None
                    for i in range(parent.rowCount()):
                        child = parent.child(i)
                        if child.text() == os.path.basename(acc):
                            found = child
                            break
                    if not found:
                        found = QtGui.QStandardItem(os.path.basename(acc))
                        found.setEditable(False)
                        parent.appendRow(found)
                    parent = found
            for f in sorted(filenames):
                if f.lower().endswith(SUPPORTED_EXTS):
                    full = os.path.join(dirpath, f)
                    item = QtGui.QStandardItem(f)
                    item.setEditable(False)
                    item.setData(os.path.abspath(full), QtCore.Qt.ItemDataRole.UserRole)
                    parent.appendRow(item)
        # keep tree fully expanded
        try:
            self.tree.expandAll()
        except Exception:
            pass

    def on_tree_clicked(self, index: QtCore.QModelIndex):
        item = self.model.itemFromIndex(index)
        path = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if path and isinstance(path, str) and os.path.isfile(path):
            self.open_pdf(path)

    # ---------- open with polling ----------
    def open_pdf(self, path: str):
        abs_path = os.path.abspath(path)
        new_doc = QPdfDocument(self)
        self._pending_doc = new_doc
        self._pending_path = abs_path
        self._pending_start = monotonic()
        try:
            status = new_doc.load(abs_path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Load call failed: {e}")
            try:
                new_doc.deleteLater()
            except Exception:
                pass
            self._pending_doc = None
            self._pending_path = None
            return

        ready_enum = None
        try:
            ready_enum = QPdfDocument.Status.Ready
        except Exception:
            pass

        if ready_enum is not None and status == ready_enum:
            self._finalize_new_doc(new_doc, abs_path)
            return

        self.status_label.setText(f"Opening: {os.path.basename(abs_path)}")
        self._load_timer.start()

    def _poll_load_status(self):
        doc = getattr(self, "_pending_doc", None)
        path = getattr(self, "_pending_path", None)
        if doc is None or path is None:
            self._load_timer.stop()
            return

        status = None
        try:
            status = doc.status()
        except Exception:
            try:
                status = doc.status
            except Exception:
                status = None

        ready_enum = None
        try:
            ready_enum = QPdfDocument.Status.Ready
        except Exception:
            pass

        if ready_enum is not None and status == ready_enum:
            self._load_timer.stop()
            self._finalize_new_doc(doc, path)
            return

        if monotonic() - getattr(self, "_pending_start", 0.0) > LOAD_TIMEOUT_S:
            self._load_timer.stop()
            try:
                sname = str(status)
            except Exception:
                sname = "unknown"
            QtWidgets.QMessageBox.critical(self, "Error", f"PDF load timeout after {LOAD_TIMEOUT_S}s (status={sname}). File: {path}")
            try:
                doc.deleteLater()
            except Exception:
                pass
            self._pending_doc = None
            self._pending_path = None
            self.status_label.setText("Error opening PDF")
            return
        # still loading

    def _finalize_new_doc(self, new_doc, abs_path):
        old = getattr(self, "pdf_doc", None)
        try:
            self.pdf_doc = new_doc
            try:
                self.pdf_view.setDocument(self.pdf_doc)
            except Exception:
                pass
            # try to set multi-page if API available
            try:
                self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
            except Exception:
                try:
                    self.pdf_view.setViewMode(QPdfView.ViewMode.MultiPage)
                except Exception:
                    pass
            # try fit-to-width
            try:
                self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            except Exception:
                pass
            self.current_pdf_path = abs_path
            self.load_notes_for_current_pdf()
            QtCore.QTimer.singleShot(0, self.update_status_page)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Error during document finalization: {e}")
            try:
                new_doc.deleteLater()
            except Exception:
                pass
            if old is not None:
                self.pdf_doc = old
                try:
                    self.pdf_view.setDocument(old)
                except Exception:
                    pass
            self._pending_doc = None
            self._pending_path = None
            return

        if old is not None:
            try:
                old.deleteLater()
            except Exception:
                pass

        self._pending_doc = None
        self._pending_path = None
        self.status_label.setText(f"✅ Opened: {os.path.basename(abs_path)}")

    # ---------- safe status / page tracking ----------
    def update_status_page(self):
        cur_path = getattr(self, "current_pdf_path", None)
        pdf_doc = getattr(self, "pdf_doc", None)
        pdf_view = getattr(self, "pdf_view", None)
        if not cur_path or pdf_doc is None or pdf_view is None:
            try:
                self.status_label.setText("Ready")
            except Exception:
                pass
            return

        try:
            total = pdf_doc.pageCount()
        except Exception:
            total = 0
        if total <= 0:
            try:
                self.status_label.setText("Ready")
            except Exception:
                pass
            return

        cur = -1
        try:
            cur = pdf_view.currentPage()
            if cur is None:
                cur = -1
        except Exception:
            cur = -1

        if cur < 0:
            try:
                vsb = pdf_view.verticalScrollBar()
                if vsb is not None:
                    v = vsb.value()
                    maxv = max(1, vsb.maximum())
                    cur = int((v / maxv) * total)
                else:
                    cur = 0
            except Exception:
                cur = 0

        cur = max(0, min(total - 1, int(cur)))
        breadcrumb = self._breadcrumb(cur_path)
        try:
            self.status_label.setText(f"✅ Ready: {breadcrumb} — Page {cur+1}/{total}")
        except Exception:
            pass

    # ---------- notes ----------
    def load_notes_for_current_pdf(self):
        self.notes_list.clear()
        path = getattr(self, "current_pdf_path", None)
        if not path:
            return
        notes = self.notes_store.get(path, [])
        for n in notes:
            self.notes_list.addItem(f"[p{n['page']}] {n['text']}")

    def _save_notes_store(self):
        self.cfg[NOTES_KEY] = self.notes_store
        save_config(self.cfg)

    def add_note(self):
        path = getattr(self, "current_pdf_path", None)
        pdf_doc = getattr(self, "pdf_doc", None)
        if not path or pdf_doc is None:
            QtWidgets.QMessageBox.information(self, "Info", "Open a PDF first.")
            return
        try:
            maxp = pdf_doc.pageCount()
        except Exception:
            maxp = None
        dlg = NoteDialog(self, text="", page=1, max_page=maxp)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            res = dlg.result()
            if res:
                self.notes_store.setdefault(path, []).append(res)
                self._save_notes_store()
                self.load_notes_for_current_pdf()

    def edit_note(self):
        path = getattr(self, "current_pdf_path", None)
        pdf_doc = getattr(self, "pdf_doc", None)
        sel = self.notes_list.currentRow()
        if sel < 0 or not path or pdf_doc is None:
            QtWidgets.QMessageBox.information(self, "Info", "Select a note.")
            return
        cur = self.notes_store.get(path, [])[sel]
        try:
            maxp = pdf_doc.pageCount()
        except Exception:
            maxp = None
        dlg = NoteDialog(self, text=cur["text"], page=cur["page"], max_page=maxp)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            res = dlg.result()
            if res:
                self.notes_store[path][sel] = res
                self._save_notes_store()
                self.load_notes_for_current_pdf()

    def remove_note(self):
        path = getattr(self, "current_pdf_path", None)
        sel = self.notes_list.currentRow()
        if sel < 0 or not path:
            QtWidgets.QMessageBox.information(self, "Info", "Select a note.")
            return
        ok = QtWidgets.QMessageBox.question(self, "Confirm", "Remove selected note?")
        if ok != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.notes_store[path].pop(sel)
        if not self.notes_store[path]:
            self.notes_store.pop(path, None)
        self._save_notes_store()
        self.load_notes_for_current_pdf()

    def on_note_clicked(self, item):
        path = getattr(self, "current_pdf_path", None)
        pdf_doc = getattr(self, "pdf_doc", None)
        if not path or pdf_doc is None:
            return
        row = self.notes_list.row(item)
        notes = self.notes_store.get(path, [])
        if row < 0 or row >= len(notes):
            return
        page = notes[row]["page"]
        try:
            self.pdf_view.setPage(page - 1)
        except Exception:
            try:
                vsb = self.pdf_view.verticalScrollBar()
                if vsb is not None and pdf_doc is not None and pdf_doc.pageCount() > 0:
                    frac = (page - 1) / max(1, pdf_doc.pageCount() - 1)
                    vsb.setValue(int(frac * vsb.maximum()))
            except Exception:
                pass
        QtCore.QTimer.singleShot(60, self.update_status_page)

    def _breadcrumb(self, path):
        if not self.root_folder:
            return os.path.basename(path)
        try:
            rel = os.path.relpath(path, self.root_folder)
            return rel.replace(os.sep, " / ")
        except Exception:
            return os.path.basename(path)

def main():
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    # show maximized window (keeps title bar and taskbar)
    win.showMaximized()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()