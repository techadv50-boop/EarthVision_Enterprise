STYLESHEET = """
QMainWindow, QWidget {
    background: #f4f6f8;
    color: #1c2430;
    font-family: "Segoe UI", "Ubuntu", sans-serif;
    font-size: 13px;
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
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QListWidget {
    border: 1px solid #c5d0dc;
    border-radius: 6px;
    padding: 6px 8px;
    background: #ffffff;
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
QTableWidget {
    background: #ffffff;
    border: 1px solid #d9e1ea;
    gridline-color: #e6edf3;
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
"""
