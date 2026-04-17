# uart-mcp

MCP server that gives [Claude Code](https://docs.anthropic.com/en/docs/claude-code) a shell on your device over UART serial. Send commands, read boot logs, interrupt bootloaders, interact with serial consoles — directly from Claude.

## Install

```bash
pip install -e .
```

Requires Python 3.10+.

## Setup

```bash
claude mcp add --transport stdio --scope project uart-mcp -- uart-mcp
```

By default it connects to `/dev/ttyUSB0` at `115200` baud. Override with environment variables:

| Variable | Default | Description |
|---|---|---|
| `UART_PORT` | `/dev/ttyUSB0` | Serial port path |
| `UART_BAUD` | `115200` | Baud rate |

## Tools

| Tool | Description |
|---|---|
| `uart_exec(command, timeout=5)` | Run a command, return clean output |
| `uart_read(timeout=1)` | Read raw serial buffer (boot logs, etc.) |
| `uart_write(data)` | Send raw text (login, Ctrl-C `\x03`, etc.) |
| `uart_break(duration=0.25)` | Send serial BREAK (interrupt U-Boot, SysRq) |
| `uart_set_port(port)` | Switch serial port at runtime |
| `uart_set_baud(baud)` | Switch baud rate at runtime |
| `uart_log_start(path=/tmp/uart.log)` | Start background capture of serial output |
| `uart_log_stop()` | Stop background logging |
| `uart_status()` | Connection + logging status |

## How It Works

- **Lazy connect** — port opens on first tool call, not at startup
- **Persistent session** — connection stays open between calls
- **Auto-reconnect** — retries once if the connection drops
- **Thread-safe** — lock prevents interleaved serial I/O
- **Marker parsing** — `uart_exec` wraps commands with `echo __START__; <cmd>; echo __END__` for reliable output extraction

## License

MIT
