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
def uart_status() -> dict:
    """Check the UART serial connection status."""
    return conn.status()


def main() -> None:
    mcp.run(transport="stdio")
