import logging

from mcp.server.fastmcp import FastMCP

from uart_mcp.serial_conn import SerialConnection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP("uart")
conn = SerialConnection()


@mcp.tool()
def uart_exec(command: str, timeout: float = 5.0) -> str:
    """Execute a shell command on the UART-connected device and return its output.

    Wraps the command with markers for reliable output parsing.
    """
    try:
        return conn.exec_command(command, timeout)
    except Exception as e:
        logger.exception("uart_exec failed")
        return f"[ERROR] {e}"


@mcp.tool()
def uart_read(timeout: float = 1.0) -> str:
    """Read raw data from the UART serial buffer.

    Useful for boot logs, long-running commands, or monitoring output.
    """
    try:
        data = conn.read(timeout)
        return data if data else "[NO DATA]"
    except Exception as e:
        logger.exception("uart_read failed")
        return f"[ERROR] {e}"


@mcp.tool()
def uart_write(data: str) -> str:
    """Send raw data to the UART serial port without waiting for a response.

    Useful for interactive prompts, login sequences, or sending control
    characters like Ctrl-C (\\x03).
    """
    try:
        conn.write(data)
        return f"[OK] Sent {len(data)} bytes"
    except Exception as e:
        logger.exception("uart_write failed")
        return f"[ERROR] {e}"


@mcp.tool()
def uart_break(duration: float = 0.25) -> str:
    """Send a serial BREAK signal on the UART line.

    Useful for interrupting bootloaders (e.g. U-Boot), escaping hung states,
    or triggering SysRq on Linux. This is a real UART-level signal, not a
    character — it holds TX low for the specified duration.
    """
    try:
        conn.send_break(duration)
        return f"[OK] BREAK sent ({duration}s)"
    except Exception as e:
        logger.exception("uart_break failed")
        return f"[ERROR] {e}"


@mcp.tool()
def uart_configure(port: str | None = None, baud: int | None = None) -> str:
    """Establish or reconfigure the UART connection.

    Provide `port`, `baud`, or both. If a connection is already open, it's
    closed and reopened with the new settings. This is the sole mechanism
    for changing port/baud — useful for switching adapters, or for devices
    that change speed between stages (e.g. bootloader at 9600, Linux at 115200).
    """
    try:
        conn.configure(port=port, baud=baud)
        return f"[OK] Reconfigured → port={conn.port} baud={conn.baud}"
    except Exception as e:
        logger.exception("uart_configure failed")
        return f"[ERROR] {e}"


@mcp.tool()
def uart_log_start(path: str = "/tmp/uart.log") -> str:
    """Start background capture of all serial output to a local file.

    Runs in a background thread, capturing everything the device sends
    (boot logs, kernel messages, crash dumps, etc.). Only one session at a time.
    """
    try:
        conn.start_logging(path)
        return f"[OK] Logging started → {path}"
    except Exception as e:
        logger.exception("uart_log_start failed")
        return f"[ERROR] {e}"


@mcp.tool()
def uart_log_stop() -> str:
    """Stop background serial logging and return the log file path."""
    try:
        path = conn.stop_logging()
        return f"[OK] Logging stopped. File: {path}"
    except Exception as e:
        logger.exception("uart_log_stop failed")
        return f"[ERROR] {e}"


@mcp.tool()
def uart_status() -> dict:
    """Check the UART serial connection status."""
    return conn.status()


def main() -> None:
    mcp.run(transport="stdio")
