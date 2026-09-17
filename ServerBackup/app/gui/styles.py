STYLESHEET = """
QMainWindow, QDialog {
    background: #f4f6f8;
    color: #1c2430;
    font-family: "Segoe UI", "Ubuntu", sans-serif;
    font-size: 13px;
}
QLabel {
    color: #1c2430;
}
QLabel#title {
    font-size: 22px;
    font-weight: 700;
    color: #10233a;
}
QLabel#subtitle {
    color: #5b6775;
}
QLabel#sectionHeader {
    font-size: 12px;
    font-weight: 700;
    color: #64748b;
    letter-spacing: 1px;
    margin-top: 6px;
    padding: 2px 0;
}
QFrame#card {
    background: #ffffff;
    border: 1px solid #d9e1ea;
    border-radius: 10px;
}
QPushButton {
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 10px 16px;
    background: #ffffff;
    color: #1c2430;
    font-weight: 600;
    min-height: 20px;
}
QPushButton:hover {
    background: #eef3f8;
    border-color: #94a3b8;
}
QPushButton:pressed {
    background: #e2e8f0;
}
QPushButton:disabled {
    color: #9aa7b5;
    background: #f1f4f7;
    border-color: #e2e8f0;
}
/* Secondary action buttons render as a clean, uniform grid. Labels are the
   only text shown; the full action name is also available as a tooltip. */
QPushButton#secondary {
    background: #ffffff;
    color: #1f2a37;
    border: 1px solid #cbd5e1;
    min-height: 40px;
    font-weight: 600;
}
QPushButton#secondary:hover {
    background: #f1f6fb;
    border-color: #1b7f4e;
    color: #10233a;
}
QPushButton#primary {
    background: #1b7f4e;
    color: #ffffff;
    border: none;
    font-weight: 700;
    padding: 14px 22px;
    font-size: 16px;
    min-height: 26px;
}
QPushButton#primary:hover {
    background: #166b42;
}
QPushButton#primary:disabled {
    background: #a7c9b6;
    color: #eef7f1;
}
QPushButton#danger {
    background: #b42318;
    color: #ffffff;
    border: none;
    font-weight: 700;
    min-height: 26px;
}
QPushButton#danger:hover {
    background: #912018;
}
QToolTip {
    background: #10233a;
    color: #ffffff;
    border: none;
    padding: 6px 8px;
    border-radius: 4px;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QListWidget {
    border: 1px solid #c5d0dc;
    border-radius: 6px;
    padding: 6px 8px;
    background: #ffffff;
    color: #1c2430;
    selection-background-color: #1b7f4e;
    selection-color: #ffffff;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus {
    border: 1px solid #1b7f4e;
}
QLineEdit:read-only {
    background: #eef3f8;
}
QProgressBar {
    border: 1px solid #c5d0dc;
    border-radius: 6px;
    text-align: center;
    height: 18px;
    background: #ffffff;
}
QProgressBar::chunk {
    background: #1b7f4e;
}
QLabel#liveBackupPanel {
    background: #ffffff;
    border: 1px solid #d9e1ea;
    border-radius: 10px;
    padding: 12px;
    font-family: "Consolas", "Segoe UI", monospace;
    font-size: 13px;
    color: #10233a;
}
QTableWidget {
    background: #ffffff;
    border: 1px solid #d9e1ea;
    gridline-color: #e6edf3;
    color: #1c2430;
}
QHeaderView::section {
    background: #eef3f8;
    padding: 6px;
    border: none;
    font-weight: 600;
}
QStatusBar {
    background: #10233a;
    color: #ffffff;
}
QScrollArea {
    border: none;
    background: #f4f6f8;
}
"""
