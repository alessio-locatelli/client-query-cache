from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from testcontainers.core.container import DockerContainer


def note_mongodb_startup_failure(
    container: DockerContainer, error: BaseException | None
) -> None:
    if error is None:
        return
    try:
        wrapped = container.get_wrapped_container()
        wrapped.reload()
        error.add_note(f"MongoDB container state: {wrapped.attrs['State']}")
        stdout, stderr = container.get_logs()
    except Exception as log_error:  # noqa: BLE001 - preserve the startup exception
        error.add_note(f"MongoDB startup logs unavailable: {log_error}")
    else:
        logs = b"\n".join((stdout + b"\n" + stderr).splitlines()[-20:])
        error.add_note(f"MongoDB startup logs:\n{logs.decode(errors='replace')}")
