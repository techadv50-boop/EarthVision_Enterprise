"""Login, password-change, and master-reset dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from webcrawler import __app_name__
from webcrawler.auth.manager import AuthManager, UserAccount


class ChangePasswordDialog(QDialog):
    def __init__(
        self,
        auth: AuthManager,
        username: str,
        parent=None,
        *,
        forced: bool = False,
        require_current: bool = True,
    ) -> None:
        super().__init__(parent)
        self.auth = auth
        self.username = username
        self.require_current = require_current
        self.user: UserAccount | None = None

        self.setWindowTitle("Change Password")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        if forced:
            note = QLabel(
                "You must change the default password before continuing."
            )
            note.setWordWrap(True)
            layout.addWidget(note)

        form = QFormLayout()
        self.current_edit = QLineEdit()
        self.current_edit.setEchoMode(QLineEdit.Password)
        self.new_edit = QLineEdit()
        self.new_edit.setEchoMode(QLineEdit.Password)
        self.confirm_edit = QLineEdit()
        self.confirm_edit.setEchoMode(QLineEdit.Password)

        if require_current:
            form.addRow("Current password", self.current_edit)
        form.addRow("New password", self.new_edit)
        form.addRow("Confirm password", self.confirm_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        if forced:
            buttons.button(QDialogButtonBox.Cancel).setEnabled(False)
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowCloseButtonHint)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.new_edit.setFocus()

    def _save(self) -> None:
        result = self.auth.change_password(
            self.username,
            self.current_edit.text(),
            self.new_edit.text(),
            self.confirm_edit.text(),
            require_current=self.require_current,
        )
        if not result.ok:
            QMessageBox.warning(self, "Change Password", result.message)
            return
        self.user = result.user
        QMessageBox.information(self, "Change Password", result.message)
        self.accept()


class MasterResetDialog(QDialog):
    def __init__(self, auth: AuthManager, parent=None) -> None:
        super().__init__(parent)
        self.auth = auth
        self.setWindowTitle("Master Reset")
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Enter the master reset code to restore the admin account\n"
                "(username: admin, password: admin, change required on next login)."
            )
        )
        self.code_edit = QLineEdit()
        self.code_edit.setEchoMode(QLineEdit.Password)
        self.code_edit.setPlaceholderText("Master reset code")
        layout.addWidget(self.code_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._reset)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.code_edit.setFocus()

    def _reset(self) -> None:
        result = self.auth.master_reset(self.code_edit.text())
        if not result.ok:
            QMessageBox.warning(self, "Master Reset", result.message)
            return
        QMessageBox.information(self, "Master Reset", result.message)
        self.accept()


class LoginDialog(QDialog):
    def __init__(self, auth: AuthManager, parent=None) -> None:
        super().__init__(parent)
        self.auth = auth
        self.user: UserAccount | None = None

        self.setWindowTitle(f"{__app_name__} — Login")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        title = QLabel(f"<b>{__app_name__}</b>")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(QLabel("Sign in with your account credentials."))

        form = QFormLayout()
        self.username_edit = QLineEdit()
        self.username_edit.setText("admin")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Password")
        form.addRow("Username", self.username_edit)
        form.addRow("Password", self.password_edit)
        layout.addLayout(form)

        row = QHBoxLayout()
        self.login_btn = QPushButton("Login")
        self.login_btn.setDefault(True)
        self.reset_btn = QPushButton("Master Reset…")
        self.cancel_btn = QPushButton("Exit")
        self.login_btn.clicked.connect(self._login)
        self.reset_btn.clicked.connect(self._master_reset)
        self.cancel_btn.clicked.connect(self.reject)
        row.addWidget(self.login_btn)
        row.addWidget(self.reset_btn)
        row.addWidget(self.cancel_btn)
        layout.addLayout(row)

        hint = QLabel("Default: admin / admin (password change required on first login)")
        hint.setStyleSheet("color: gray;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.password_edit.setFocus()

    def _login(self) -> None:
        result = self.auth.authenticate(
            self.username_edit.text(),
            self.password_edit.text(),
        )
        if not result.ok or not result.user:
            QMessageBox.warning(self, "Login Failed", result.message)
            self.password_edit.clear()
            self.password_edit.setFocus()
            return

        user = result.user
        if user.must_change_password:
            dialog = ChangePasswordDialog(
                self.auth,
                user.username,
                self,
                forced=True,
                require_current=True,
            )
            # Prefill current password from what they just typed for convenience
            dialog.current_edit.setText(self.password_edit.text())
            if dialog.exec() != QDialog.Accepted or not dialog.user:
                return
            user = dialog.user

        self.user = user
        self.accept()

    def _master_reset(self) -> None:
        dialog = MasterResetDialog(self.auth, self)
        if dialog.exec() == QDialog.Accepted:
            self.username_edit.setText("admin")
            self.password_edit.clear()
            self.password_edit.setFocus()
