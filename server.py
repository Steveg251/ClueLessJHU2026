import asyncio
import json
import websockets

import rules as rules
from game import Game
from messages import make_message, parse_message
from player import Player

HOST = "localhost"
PORT = 8765

game = Game()
connections = {}  # websocket -> player ID
next_player_id = 1


def create_message(message_type, data=None):
    return make_message(message_type, **(data or {}))


async def send_to(player_id, message_type, data=None):
    for websocket, pid in list(connections.items()):
        if pid == player_id:
            try:
                await websocket.send(create_message(message_type, data))
            except websockets.ConnectionClosed:
                pass
            return


async def broadcast(message_type, data=None):
    if not connections:
        return
    message = create_message(message_type, data)
    await asyncio.gather(
        *[ws.send(message) for ws in list(connections)],
        return_exceptions=True,
    )


async def send_error(player_id, message):
    await send_to(player_id, "ERROR", {"message": message})


async def send_lobby_update():
    await broadcast("LOBBY_UPDATE", {
        "players": [
            {
                "playerId": p.player_id,
                "name": p.name,
                "character": p.character,
            }
            for p in game.players
        ]
    })


async def join_game(websocket, data):
    global next_player_id

    name = data.get("name") or data.get("playerName")
    if not name:
        await websocket.send(create_message("ERROR", {"message": "Player name required."}))
        return
    if game.started:
        await websocket.send(create_message("ERROR", {"message": "Game already started."}))
        return
    if len(game.players) >= rules.MAX_PLAYERS:
        await websocket.send(create_message("ERROR", {"message": "Game is full."}))
        return

    player = Player(next_player_id, name)
    next_player_id += 1

    # Updated requirement: host is always Miss Scarlet.
    if not game.players:
        player.character = "Miss Scarlet"

    game.add_player(player)
    connections[websocket] = player.player_id

    await send_to(player.player_id, "WELCOME", {
        "playerId": player.player_id,
        "name": player.name,
        "character": player.character,
        "host": len(game.players) == 1,
    })
    await send_lobby_update()


async def select_character(player_id, data):
    player = game.get_player(player_id)
    if not player:
        return
    if player == game.players[0]:
        await send_error(player_id, "The host is Miss Scarlet.")
        return

    character = data.get("character")
    if character not in rules.CHARACTERS:
        await send_error(player_id, "Invalid character.")
        return
    if character == "Miss Scarlet":
        await send_error(player_id, "Miss Scarlet belongs to the host.")
        return
    if game.character_taken(character):
        await send_error(player_id, "Character already selected.")
        return

    player.character = character
    await send_lobby_update()


async def start_game(player_id):
    if not game.players:
        return
    if player_id != game.players[0].player_id:
        await send_error(player_id, "Only the host can start the game.")
        return
    if len(game.players) < rules.MIN_PLAYERS:
        await send_error(player_id, f"At least {rules.MIN_PLAYERS} players are required.")
        return

    for player in game.players:
        if player.character is None:
            await send_error(player_id, f"{player.name} has not selected a character.")
            return

    game.initialize()

    for player in game.players:
        await send_to(player.player_id, "HAND", {"cards": player.cards})

    await broadcast("GAME_STARTED", game.public_state())
    current = game.get_current_player()
    await broadcast("TURN_STARTED", {
        "playerId": current.player_id,
        "name": current.name,
    })


async def move_player(player_id, data):
    player = game.get_player(player_id)
    if not player:
        return
    if not game.started:
        await send_error(player_id, "Game has not started.")
        return
    if game.get_current_player().player_id != player_id:
        await send_error(player_id, "It is not your turn.")
        return
    if player.eliminated:
        await send_error(player_id, "You have been eliminated.")
        return

    valid, error, old_location = game.move_player(player, data.get("destination"))
    if not valid:
        await send_error(player_id, error)
        return

    await broadcast("GAME_UPDATE", {
        "event": "CHARACTER_MOVED",
        "playerId": player.player_id,
        "character": player.character,
        "from": old_location,
        "to": player.location,
        "state": game.public_state(),
    })


async def suggestion(player_id, data):
    player = game.get_player(player_id)
    if not player:
        return
    if game.get_current_player().player_id != player_id:
        await send_error(player_id, "It is not your turn.")
        return

    suspect = data.get("suspect")
    weapon = data.get("weapon")
    valid, error = game.make_suggestion(player, suspect, weapon)
    if not valid:
        await send_error(player_id, error)
        return

    await broadcast("GAME_UPDATE", {
        "event": "SUGGESTION",
        "playerId": player_id,
        "suspect": suspect,
        "weapon": weapon,
        "room": player.location,
        "state": game.public_state(),
    })


async def accusation(player_id, data):
    player = game.get_player(player_id)
    if not player:
        return
    if game.get_current_player().player_id != player_id:
        await send_error(player_id, "It is not your turn.")
        return

    suspect = data.get("suspect")
    weapon = data.get("weapon")
    room = data.get("room")

    error = rules.accusation_error(suspect, weapon, room)
    if error:
        await send_error(player_id, error)
        return

    if rules.accusation_is_correct(game.case_file, suspect, weapon, room):
        await broadcast("GAME_WON", {
            "playerId": player_id,
            "name": player.name,
        })
    else:
        player.eliminated = True
        await broadcast("PLAYER_ELIMINATED", {
            "playerId": player_id,
            "name": player.name,
        })


async def end_turn(player_id):
    player = game.get_player(player_id)
    if not player:
        return
    if game.get_current_player().player_id != player_id:
        await send_error(player_id, "It is not your turn.")
        return

    error = game.end_turn_error(player)
    if error:
        await send_error(player_id, error)
        return

    await broadcast("TURN_ENDED", {
        "playerId": player.player_id,
        "name": player.name,
    })

    next_player = game.next_turn()
    if next_player:
        await broadcast("TURN_STARTED", {
            "playerId": next_player.player_id,
            "name": next_player.name,
        })


async def process_message(websocket, raw_message):
    try:
        message = parse_message(raw_message)
    except (json.JSONDecodeError, ValueError) as exc:
        await websocket.send(create_message("ERROR", {"message": f"Invalid message: {exc}"}))
        return

    message_type = message["type"]
    data = message["data"]
    player_id = connections.get(websocket)

    if message_type in ("HELLO", "JOIN_GAME"):
        await join_game(websocket, data)
        return

    if player_id is None:
        await websocket.send(create_message("ERROR", {"message": "Join the game first."}))
        return

    if message_type == "SELECT_CHARACTER":
        await select_character(player_id, data)
    elif message_type == "START_GAME":
        await start_game(player_id)
    elif message_type == "MOVE_REQUEST":
        await move_player(player_id, data)
    elif message_type == "SUGGESTION":
        await suggestion(player_id, data)
    elif message_type == "ACCUSATION":
        await accusation(player_id, data)
    elif message_type == "END_TURN":
        await end_turn(player_id)
    elif message_type == "GET_GAME_STATE":
        await send_to(player_id, "GAME_STATE", game.public_state())
    else:
        await send_error(player_id, f"Unknown message: {message_type}")


async def handle_client(websocket):
    print("[SERVER] Client connected.")
    try:
        async for raw_message in websocket:
            await process_message(websocket, raw_message)
    except websockets.ConnectionClosed:
        pass
    finally:
        player_id = connections.pop(websocket, None)
        if player_id:
            player = game.get_player(player_id)
            if player:
                print(f"[SERVER] {player.name} disconnected.")


async def main():
    print("CLUE-LESS minimal server")
    print(f"Listening on ws://{HOST}:{PORT}")
    async with websockets.serve(handle_client, HOST, PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
