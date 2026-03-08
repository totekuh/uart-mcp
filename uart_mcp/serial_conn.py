import logging
import os
import threading
import time

import serial
import serial.tools.list_ports

logger = logging.getLogger(__name__)


class SerialConnection:
    """Manages a persistent UART serial connection with lazy connect and auto-reconnect."""

    def __init__(self) -> None:
        self.port = os.environ.get("UART_PORT", "/dev/ttyUSB0")
        self.baud = int(os.environ.get("UART_BAUD", "115200"))
        self.prompt = os.environ.get("UART_PROMPT", "# ")
        self._ser: serial.Serial | None = None
        self._lock = threading.Lock()

    def _connect(self) -> serial.Serial:
        """Open the serial port. Raises SerialException on failure."""
        try:
            s = serial.Serial(self.port, self.baud, timeout=1)
            logger.info("Connected to %s at %d baud", self.port, self.baud)
            return s
        except serial.SerialException:
            available = [p.device for p in serial.tools.list_ports.comports()]
            raise serial.SerialException(
                f"Cannot open {self.port}. Available ports: {available}"
            )

    def _ensure_connected(self) -> serial.Serial:
        """Return an open serial connection, reconnecting if needed."""
        if self._ser is not None and self._ser.is_open:
            return self._ser
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = self._connect()
        return self._ser

    def _reconnect_once(self) -> serial.Serial:
        """Close and reopen the serial port. One attempt."""
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None
        self._ser = self._connect()
        return self._ser

    def write(self, data: str) -> None:
        """Send raw data to serial. Acquires lock."""
        with self._lock:
            s = self._ensure_connected()
            try:
                s.write(data.encode())
            except serial.SerialException:
                s = self._reconnect_once()
                s.write(data.encode())

    def read(self, timeout: float = 1.0) -> str:
        """Read available data from serial with timeout. Acquires lock."""
        with self._lock:
            return self._read_unlocked(timeout)

    def _read_unlocked(self, timeout: float) -> str:
        """Read from serial without acquiring lock. Caller must hold lock."""
        s = self._ensure_connected()
        buf = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            s.timeout = min(remaining, 0.1)
            chunk = s.read(s.in_waiting or 1)
            if chunk:
                buf.extend(chunk)
            elif buf:
                # Got data previously, and nothing new — give a short grace period
                time.sleep(0.05)
                if not s.in_waiting:
                    break
        return buf.decode(errors="replace")

    def exec_command(self, command: str, timeout: float = 5.0) -> str:
        """Execute a command with __START__/__END__ markers and return clean output.

        Acquires lock for the entire duration to prevent interleaving.
        """
        with self._lock:
            s = self._ensure_connected()
            s.reset_input_buffer()

            wrapped = f"echo __START__; {command}; echo __END__\n"
            try:
                s.write(wrapped.encode())
            except serial.SerialException:
                s = self._reconnect_once()
                s.reset_input_buffer()
                s.write(wrapped.encode())

            buf = bytearray()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                s.timeout = min(remaining, 0.1)
                chunk = s.read(s.in_waiting or 1)
                if chunk:
                    buf.extend(chunk)
                text = buf.decode(errors="replace")
                if "__END__" in text:
                    parsed = self._parse_markers(text)
                    if parsed is not None:
                        return parsed

            # Timeout — return what we have
            text = buf.decode(errors="replace")
            parsed = self._parse_markers(text)
            if parsed is not None:
                return parsed
            return text.strip() + "\n[TIMEOUT]"

    @staticmethod
    def _parse_markers(text: str) -> str | None:
        """Extract output between __START__ and __END__ markers.

        Returns None if markers are not found.
        """
        start_idx = text.find("__START__\n")
        if start_idx == -1:
            # Try with \r\n (some serial terminals use CR+LF)
            start_idx = text.find("__START__\r\n")
            if start_idx == -1:
                return None
            start_idx += len("__START__\r\n")
        else:
            start_idx += len("__START__\n")

        end_idx = text.find("__END__", start_idx)
        if end_idx == -1:
            return None

        # Trim trailing whitespace/newlines before __END__
        output = text[start_idx:end_idx].strip()
        return output

    def reset_input(self) -> None:
        """Clear the serial input buffer. Acquires lock."""
        with self._lock:
            s = self._ensure_connected()
            s.reset_input_buffer()

    def status(self) -> dict:
        """Return connection status without acquiring lock."""
        connected = self._ser is not None and self._ser.is_open
        return {
            "connected": connected,
            "port": self.port,
            "baud": self.baud,
        }
