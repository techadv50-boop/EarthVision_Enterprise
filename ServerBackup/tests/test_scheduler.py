from app.scheduler.tasks import TASK_NAME, _sc, engine_command_for_scripts


def test_schedule_default_task_name():
    assert TASK_NAME == "ServerBackup-Ubuntu"
    assert _sc("daily") == "DAILY"
    assert " --backup " in f" {engine_command_for_scripts()} " or "--backup" in engine_command_for_scripts()
