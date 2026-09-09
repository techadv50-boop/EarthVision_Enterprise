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
QFrame#card {
    background: #ffffff;
    border: 1px solid #d9e1ea;
    border-radius: 10px;
}
QPushButton {
    border: 1px solid #c5d0dc;
    border-radius: 6px;
    padding: 8px 14px;
    background: #ffffff;
    color: #1c2430;
}
QPushButton:hover {
    background: #eef3f8;
}
QPushButton#primary {
    background: #1b7f4e;
    color: #ffffff;
    border: none;
    font-weight: 700;
    padding: 14px 22px;
    font-size: 16px;
}
QPushButton#primary:hover {
    background: #166b42;
}
QPushButton#danger {
    background: #b42318;
    color: #ffffff;
    border: none;
    font-weight: 600;
}
QPushButton#danger:hover {
    background: #912018;
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
