"""Privacy boundary for workstation presence monitoring.

The agent stores timestamps, status transitions, and device identifiers only.
It must never collect the items listed in FORBIDDEN_CAPABILITIES.
"""

from __future__ import annotations

ALLOWED_DATA = (
    "timestamps",
    "status_transitions",
    "employee_id",
    "device_id",
    "last_input_age_seconds",
    "connection_status",
    "heartbeat_metadata",
)

FORBIDDEN_CAPABILITIES = (
    "keylogging",
    "typed_characters",
    "passwords",
    "windows_password",
    "mouse_coordinates",
    "screenshots",
    "webcam",
    "microphone",
    "personal_documents",
    "clipboard",
    "website_contents",
    "private_messages",
)

# Win32 APIs that would violate the privacy boundary if called.
FORBIDDEN_API_NAMES = (
    "SetWindowsHookEx",
    "SetWindowsHookExW",
    "SetWindowsHookExA",
    "WH_KEYBOARD",
    "WH_KEYBOARD_LL",
    "WH_MOUSE",
    "WH_MOUSE_LL",
    "GetAsyncKeyState",
    "GetKeyState",
    "GetKeyboardState",
    "ToUnicode",
    "ToUnicodeEx",
    "GetClipboardData",
    "AddClipboardFormatListener",
    "BitBlt",
    "PrintWindow",
    "StretchBlt",
    "capCreateCaptureWindow",
    "waveInOpen",
    "waveInStart",
    "avicap32",
    "GetCursorPos",
)


def privacy_statement() -> str:
    return (
        "This agent monitors workstation presence and activity status only. "
        "It does not record typed characters, passwords, mouse coordinates, "
        "screenshots, webcam images, microphone audio, documents, clipboard "
        "contents, websites, or private messages."
    )
