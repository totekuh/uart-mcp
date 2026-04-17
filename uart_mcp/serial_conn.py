import logging
import threading
import time

import serial
import serial.tools.list_ports

logger = logging.getLogger(__name__)

DEFAULT_PORT = "/dev/ttyUSB0"
DEFAULT_BAUD = 115200


class SerialConnection:
    """Manages a persistent UART serial connection with lazy connect and auto-reconnect."""

    def __init__(self) -> None:
        self.port = DEFAULT_PORT
        self.baud = DEFAULT_BAUD
        self._ser: serial.Serial | None = None
        self._lock = threading.Lock()
        self._log_thread: threading.Thread | None = None
        self._log_stop: threading.Event = threading.Event()
        self._log_path: str | None = None

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
        self._close_unlocked()
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

    def send_break(self, duration: float = 0.25) -> None:
        """Send a serial BREAK signal. Acquires lock."""
        with self._lock:
            s = self._ensure_connected()
            s.send_break(duration)

    def configure(self, port: str | None = None, baud: int | None = None) -> None:
        """Reconfigure port and/or baud rate, reopening the connection. Acquires lock.

        At least one of `port` or `baud` must be provided. Applies both atomically.
        """
        if port is None and baud is None:
            raise ValueError("configure requires at least one of port or baud")
        with self._lock:
            self._close_unlocked()
            if port is not None:
                self.port = port
            if baud is not None:
                self.baud = baud
            self._ser = serial.Serial(self.port, self.baud, timeout=1)
            logger.info("Reconnected to %s at %d baud", self.port, self.baud)

    def _close_unlocked(self) -> None:
        """Close the serial port without acquiring lock. Caller must hold lock."""
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def start_logging(self, path: str) -> None:
        """Start background capture of all serial output to a file.

        Spawns a daemon thread that reads from serial and writes to the file.
        Only one logging session at a time.
        """
        if self._log_thread is not None and self._log_thread.is_alive():
            raise RuntimeError("Logging already active")
        self._log_stop = threading.Event()
        self._log_path = path
        self._log_thread = threading.Thread(
            target=self._log_worker, args=(path,), daemon=True
        )
        self._log_thread.start()
        logger.info("Started logging to %s", path)

    def stop_logging(self) -> str:
        """Stop background logging and return the file path."""
        if self._log_thread is None or not self._log_thread.is_alive():
            raise RuntimeError("No active logging session")
        self._log_stop.set()
        self._log_thread.join(timeout=3)
        self._log_thread = None
        path = self._log_path or ""
        self._log_path = None
        logger.info("Stopped logging to %s", path)
        return path

    def _log_worker(self, path: str) -> None:
        """Background worker that captures serial output to a file."""
        with open(path, "a") as f:
            while not self._log_stop.is_set():
                with self._lock:
                    s = self._ensure_connected()
                    s.timeout = 0.1
                    chunk = s.read(s.in_waiting or 1)
                if chunk:
                    f.write(chunk.decode(errors="replace"))
                    f.flush()
                else:
                    time.sleep(0.05)

    def logging_active(self) -> bool:
        """Return whether background logging is active."""
        return self._log_thread is not None and self._log_thread.is_alive()

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
            "logging": self.logging_active(),
            "log_path": self._log_path,
        }
