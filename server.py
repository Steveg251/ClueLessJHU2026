import asyncio
import json
import uuid
import websockets

from messages import make_message, parse_message

HOST = "localhost"
PORT = 8765
MAX_PLAYERS = 6

clients = {}       # websocket -> {id, name, is_host}
game_started = False


async def send(ws, message_type, **payload):
    await ws.send(make_message(message_type, **payload))


async def broadcast(message_type, exclude=None, **payload):
    if not clients:
        return
    message = make_message(message_type, **payload)
    targets = [ws for ws in clients if ws is not exclude]
    if targets:
        await asyncio.gather(*(ws.send(message) for ws in targets), return_exceptions=True)


def lobby_snapshot():
    return [
        {"id": info["id"], "name": info["name"], "is_host": info["is_host"]}
        for info in clients.values()
    ]


async def broadcast_lobby():
    await broadcast("LOBBY_UPDATE", players=lobby_snapshot(), max_players=MAX_PLAYERS)


async def route_message(ws, data):
    global game_started
    msg_type = data["type"]
    info = clients[ws]

    print(f"[SERVER] {info['name']} -> {msg_type}: {data}")

    if msg_type == "START_GAME":
        if not info["is_host"]:
            await send(ws, "ERROR", message="Only the host can start the game.")
            return
        game_started = True
        await broadcast("GAME_STARTED", players=lobby_snapshot())

    elif msg_type == "MOVE_REQUEST":
        # Skeletal increment: demonstrate routing, direct response, then broadcast.
        # Full server-side Clue rule validation belongs in the minimal increment.
        destination = data.get("destination")
        await send(ws, "MOVE_RESPONSE", accepted=True, destination=destination)
        await broadcast(
            "GAME_UPDATE",
            event="PLAYER_MOVED",
            player_id=info["id"],
            player_name=info["name"],
            destination=destination,
        )

    elif msg_type == "SUGGESTION":
        await broadcast(
            "GAME_UPDATE",
            event="SUGGESTION",
            player_id=info["id"],
            player_name=info["name"],
            room=data.get("room"),
        )

    elif msg_type == "ACCUSATION":
        await broadcast(
            "GAME_UPDATE",
            event="ACCUSATION",
            player_id=info["id"],
            player_name=info["name"],
        )

    elif msg_type == "END_TURN":
        await broadcast(
            "GAME_UPDATE",
            event="END_TURN",
            player_id=info["id"],
            player_name=info["name"],
        )

    else:
        await send(ws, "ERROR", message=f"Unknown message type: {msg_type}")


async def handler(ws):
    global game_started
    try:
        raw = await ws.recv()
        hello = parse_message(raw)
        if hello["type"] != "HELLO":
            await send(ws, "ERROR", message="First message must be HELLO.")
            await ws.close()
            return

        if len(clients) >= MAX_PLAYERS:
            await send(ws, "ERROR", message="Lobby is full.")
            await ws.close()
            return

        if game_started:
            await send(ws, "ERROR", message="Game has already started.")
            await ws.close()
            return

        player_id = str(uuid.uuid4())[:8]
        name = str(hello.get("name") or f"Player {len(clients) + 1}")
        is_host = len(clients) == 0
        clients[ws] = {"id": player_id, "name": name, "is_host": is_host}

        await send(ws, "WELCOME", player_id=player_id, name=name, is_host=is_host)
        await broadcast("PLAYER_CONNECTED", player_id=player_id, player_name=name, exclude=ws)
        await broadcast_lobby()
        print(f"[SERVER] Connected: {name} ({player_id}) host={is_host}")

        async for raw in ws:
            try:
                data = parse_message(raw)
                await route_message(ws, data)
            except (json.JSONDecodeError, ValueError) as exc:
                await send(ws, "ERROR", message=str(exc))

    except websockets.ConnectionClosed:
        pass
    finally:
        info = clients.pop(ws, None)
        if info:
            print(f"[SERVER] Disconnected: {info['name']}")
            await broadcast("PLAYER_DISCONNECTED", player_id=info["id"], player_name=info["name"])
            if clients:
                # If the host leaves before the game starts, promote the oldest remaining client.
                if info["is_host"] and not game_started:
                    next_info = next(iter(clients.values()))
                    next_info["is_host"] = True
                await broadcast_lobby()
            else:
                game_started = False


async def main():
    print(f"Clue-Less server listening on ws://{HOST}:{PORT}")
    async with websockets.serve(handler, HOST, PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
