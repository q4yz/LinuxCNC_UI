import logging
from fastapi import HTTPException

logger = logging.getLogger("backend.hardware.connection")

try:
    import linuxcnc
    logger.info("Successfully imported real linuxcnc module.")
    USE_MOCK = False
except ImportError:
    from . import linuxcnc_mock as linuxcnc
    logger.warning("Could not import real linuxcnc. Falling back to linuxcnc_mock.")
    USE_MOCK = True

# Initialize machine stat and command interfaces
machine_stat = linuxcnc.stat()
machine_cmd = linuxcnc.command()
machine_error = linuxcnc.error_channel()


def get_machine_stat():
    """Returns the global machine stat object."""
    return machine_stat


def get_machine_cmd():
    """Returns the global machine command object."""
    return machine_cmd


def get_machine_error():
    """Returns the global machine error object."""
    return machine_error


def execute_sync_cmd(cmd_name: str, cmd_timeout: float = 0, *args) -> dict:
    """
    Executes a LinuxCNC command and optionally waits for it to complete.
    
    This synchronous function handles calling the physical LinuxCNC command
    bindings and waiting for completion statuses.
    
    Args:
        cmd_name: The string name of the command to execute (e.g., 'jog', 'mode').
        cmd_timeout: How long to wait for command completion in seconds.
        *args: Arguments to pass to the underlying command function.
        
    Returns:
        dict: A status dictionary containing success information.
        
    Raises:
        HTTPException: If the command fails, times out, or is unimplemented.
    """
    try:
        func = getattr(machine_cmd, cmd_name)
        func(*args)
        
        if cmd_timeout > 0:
            # wait_complete blocks until the command is processed by LinuxCNC
            ret = machine_cmd.wait_complete(cmd_timeout)
            if ret == getattr(linuxcnc, 'RCS_DONE', 1):
                return {"status": "success"}
            elif ret == getattr(linuxcnc, 'RCS_ERROR', 3):
                raise HTTPException(status_code=400, detail="Command execution error")
            else:
                raise HTTPException(status_code=408, detail="Command timed out")
        else:
            return {"status": "success"}
    except AttributeError:
        raise HTTPException(
            status_code=500,
            detail=f"Command '{cmd_name}' not implemented in hardware interface."
        )
    except Exception as e:
        logger.error(f"Command execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
