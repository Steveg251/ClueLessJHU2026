import asyncio
import json
import threading
from queue import Empty, Queue
import websockets

from messages import make_message, parse_message


class NetworkClient:

    def __init__(self, uri, player_name, on_message, on_status=None):
        self.uri = uri
        self.player_name = player_name
        self.on_message = on_message
        self.on_status = on_status or (lambda _message: None)

        self._events = Queue()
        self._loop = None
        self._websocket = None
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            raise RuntimeError("The network client is already running.")

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def send(self, message_type, **payload):
        if self._loop is None or self._websocket is None:
            raise RuntimeError("Not connected to the game server.")

        future = asyncio.run_coroutine_threadsafe(
            self._send_message(message_type, payload), self._loop
        )
        future.add_done_callback(self._report_send_error)

    def close(self):
        if self._loop is not None and self._websocket is not None:
            asyncio.run_coroutine_threadsafe(self._websocket.close(), self._loop)

    def poll(self):
        while True:
            try:
                event_type, value = self._events.get_nowait()
            except Empty:
                break

            if event_type == "message":
                self.on_message(value)
            else:
                self.on_status(value)

    def _run(self):
        asyncio.run(self._connect_and_read())

    async def _connect_and_read(self):
        self._loop = asyncio.get_running_loop()
        try:
            async with websockets.connect(self.uri) as websocket:
                self._websocket = websocket
                self._events.put(("status", f"Connected to {self.uri}"))
                await websocket.send(make_message("HELLO", name=self.player_name))

                async for raw_message in websocket:
                    try:
                        self._events.put(("message", parse_message(raw_message)))
                    except (json.JSONDecodeError, ValueError) as exc:
                        self._events.put(("status", f"Received an invalid server message: {exc}"))
        except (OSError, ValueError, websockets.ConnectionClosed) as exc:
            self._events.put(("status", f"Connection closed: {exc}"))
        finally:
            self._websocket = None
            self._loop = None
            self._events.put(("status", "Disconnected from the game server."))

    async def _send_message(self, message_type, payload):
        websocket = self._websocket
        if websocket is None:
            raise RuntimeError("Not connected to the game server.")
        await websocket.send(make_message(message_type, **payload))

    def _report_send_error(self, future):
        if future.cancelled():
            return
        exception = future.exception()
        if exception is not None:
            self._events.put(("status", f"Failed to send message: {exception}"))
