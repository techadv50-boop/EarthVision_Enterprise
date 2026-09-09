"""Shared names and limits for the Employee Monitoring Agent."""

from __future__ import annotations

APP_NAME = "Employee Monitoring Agent"
APP_ID = "EmployeeMonitoringAgent"
MUTEX_NAME = "Local\\EmployeeMonitoringAgent_SingleInstance"
STARTUP_VALUE_NAME = "EmployeeMonitoringAgent"
ALREADY_RUNNING_MESSAGE = "Employee Monitoring Agent is already running."

DEFAULT_INACTIVITY_SECONDS = 30
DEFAULT_HEARTBEAT_SECONDS = 10
DEFAULT_OFFLINE_AFTER_SECONDS = 30
DEFAULT_POLL_SECONDS = 1.0

PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 200_000
PASSWORD_SALT_BYTES = 16
PASSWORD_KEY_BYTES = 32
