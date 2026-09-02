"""Tiny CLI client to test the server without a phone or browser.

    python3 client.py                 # connects to ws://localhost:8765
    python3 client.py 100.x.x.x       # or a Tailscale IP

It prompts for the auth code, then gives you a prompt where anything you type is
sent as a shell command (CMD:). Type UI commands directly (NEW_CHAT, TYPE:hi).
Type `exit` to quit.
"""

import asyncio
import sys

import websockets


async def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    port = sys.argv[2] if len(sys.argv) > 2 else "8765"
    uri = f"ws://{host}:{port}"

    async with websockets.connect(uri) as ws:
        code = input("Auth code: ").strip()
        await ws.send(code)
        print(await ws.recv())  # AUTH_SUCCESS / AUTH_FAILED

        loop = asyncio.get_event_loop()
        while True:
            line = await loop.run_in_executor(None, input, "remote$ ")
            line = line.strip()
            if line in ("exit", "quit"):
                break
            if not line:
                continue
            # Bare text is treated as a shell command; UI verbs pass through.
            if line in ("NEW_CHAT", "NEXT_CHAT", "PREV_CHAT", "PWD") or line.startswith(
                ("TYPE:", "CMD:")
            ):
                await ws.send(line)
            else:
                await ws.send(f"CMD:{line}")
            print(await ws.recv())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, EOFError):
        print("\nbye")
