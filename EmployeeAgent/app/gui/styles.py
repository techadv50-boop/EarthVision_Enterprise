STYLESHEET = """
QMainWindow, QDialog {
    background: #0f172a;
    color: #e2e8f0;
    font-family: "Segoe UI", "Ubuntu", sans-serif;
    font-size: 13px;
}
QLabel { color: #e2e8f0; }
QLabel#title {
    font-size: 20px;
    font-weight: 700;
    color: #f8fafc;
}
QLabel#subtitle { color: #94a3b8; }
QLabel#badge {
    font-weight: 700;
    padding: 4px 10px;
    border-radius: 8px;
}
QFrame#card {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 10px;
}
QPushButton {
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 8px 14px;
    background: #1e293b;
    color: #e2e8f0;
}
QPushButton:hover { background: #334155; }
QPushButton#primary {
    background: #0f766e;
    color: #ffffff;
    border: none;
    font-weight: 700;
}
QPushButton#primary:hover { background: #0d9488; }
QPushButton#danger {
    background: #b91c1c;
    color: #ffffff;
    border: none;
    font-weight: 600;
}
QLineEdit, QSpinBox {
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 8px;
    background: #0f172a;
    color: #f8fafc;
}
QLineEdit:focus, QSpinBox:focus { border: 1px solid #14b8a6; }
QTableWidget {
    background: #0f172a;
    color: #e2e8f0;
    gridline-color: #334155;
    border: 1px solid #334155;
}
QHeaderView::section {
    background: #1e293b;
    color: #cbd5e1;
    padding: 6px;
    border: none;
}
QTabWidget::pane { border: 1px solid #334155; }
QTabBar::tab {
    background: #1e293b;
    color: #94a3b8;
    padding: 8px 14px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected { background: #0f766e; color: #ffffff; }
QMenu {
    background: #1e293b;
    color: #e2e8f0;
    border: 1px solid #334155;
}
QMenu::item:selected { background: #0f766e; }
"""
