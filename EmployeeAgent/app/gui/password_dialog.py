from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PasswordDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        *,
        title: str,
        prompt: str,
        confirm_label: str = "Login",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(prompt))
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setPlaceholderText("Password")
        layout.addWidget(self.edit)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #fca5a5;")
        layout.addWidget(self.error)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        submit = QPushButton(confirm_label)
        submit.setObjectName("primary")
        submit.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(submit)
        layout.addLayout(row)
        self.edit.returnPressed.connect(self.accept)

    def password(self) -> str:
        return self.edit.text()

    def set_error(self, text: str) -> None:
        self.error.setText(text)


def prompt_password(
    parent: QWidget | None,
    *,
    title: str,
    prompt: str,
    confirm_label: str,
    verifier,
) -> bool:
    dialog = PasswordDialog(parent, title=title, prompt=prompt, confirm_label=confirm_label)
    while True:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        if verifier(dialog.password()):
            return True
        dialog.set_error("Incorrect password.")
        dialog.edit.selectAll()
        dialog.edit.setFocus()
