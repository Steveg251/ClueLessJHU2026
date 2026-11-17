import asyncio
import json
import sys
import websockets

import rules as rules
from game import Game
from messages import make_message, parse_message
from player import Player

# Run with: python3 server.py                 only players on this computer can join
#           python3 server.py <Tailscale IP>  players on your tailnet can join too
HOST = sys.argv[1] if len(sys.argv) > 1 else "localhost"
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

    await start_disproof(player, suspect, weapon, player.location)


async def start_disproof(suggester, suspect, weapon, room):
    disprover, cards = game.start_disproof(suggester, suspect, weapon, room)
    if disprover is None:
        await broadcast("SUGGESTION_NOT_DISPROVED", {
            "suggesterId": suggester.player_id,
            "suspect": suspect,
            "weapon": weapon,
            "room": room,
        })
        return

    # only the disprover learns which of their cards match; they choose one to show
    await send_to(disprover.player_id, "DISPROVE_REQUEST", {
        "suggesterId": suggester.player_id,
        "suggesterName": suggester.name,
        "suspect": suspect,
        "weapon": weapon,
        "room": room,
        "cards": cards,
    })


async def disprove_response(player_id, data):
    player = game.get_player(player_id)
    if not player:
        return

    card = data.get("card")
    error = game.disprove_error(player, card)
    if error:
        await send_error(player_id, error)
        return

    pending = game.pending_disproof
    game.pending_disproof = None
    suggester = game.get_player(pending["suggester_id"])

    # the card itself goes only to the suggester
    await send_to(suggester.player_id, "CARD_SHOWN", {
        "card": card,
        "disproverId": player.player_id,
        "disproverName": player.name,
    })
    await broadcast("SUGGESTION_DISPROVED", {
        "suggesterId": suggester.player_id,
        "disproverId": player.player_id,
        "disproverName": player.name,
        "suspect": pending["suspect"],
        "weapon": pending["weapon"],
        "room": pending["room"],
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
        await end_game(player, "accusation")
        return

    player.eliminated = True
    await broadcast("PLAYER_ELIMINATED", {
        "playerId": player_id,
        "name": player.name,
    })

    # if everyone else is out, the last player left wins by default
    remaining = game.active_players()
    if len(remaining) == 1:
        await end_game(remaining[0], "last_player")
        return

    # an eliminated player can't finish their turn, so it passes straight on
    await pass_turn(player)


async def end_game(winner, reason):
    """reason is "accusation" (solved the case) or "last_player" (everyone else eliminated).
    The game is over, so the case file is revealed to everyone."""
    game.over = True
    await broadcast("GAME_WON", {
        "playerId": winner.player_id,
        "name": winner.name,
        "reason": reason,
        "caseFile": game.case_file,
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

    await pass_turn(player)


async def pass_turn(player):
    """Announce the end of player's turn and start the next active player's."""
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

    # turn actions only make sense while a game is being played
    if message_type in ("MOVE_REQUEST", "SUGGESTION", "ACCUSATION", "END_TURN"):
        if not game.started:
            await send_error(player_id, "The game has not started.")
            return
        if game.over:
            await send_error(player_id, "The game is over.")
            return

        # nothing else happens on the turn until the suggestion has been disproved
        error = game.waiting_on_disproof_error()
        if error:
            await send_error(player_id, error)
            return

        # eliminated players keep only one action: disproving other players' suggestions
        player = game.get_player(player_id)
        if player is not None and player.eliminated:
            await send_error(player_id, "You have been eliminated. You can still disprove suggestions.")
            return

    if message_type == "SELECT_CHARACTER":
        await select_character(player_id, data)
    elif message_type == "START_GAME":
        await start_game(player_id)
    elif message_type == "MOVE_REQUEST":
        await move_player(player_id, data)
    elif message_type == "SUGGESTION":
        await suggestion(player_id, data)
    elif message_type == "DISPROVE_RESPONSE":
        await disprove_response(player_id, data)
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
                if not game.started:
                    await leave_lobby(player)


async def leave_lobby(player):
    """Before the game starts, a player who disconnects gives up their slot and character."""
    was_host = player is game.players[0]
    game.players.remove(player)

    # the next player in line becomes host, and the host always plays Miss Scarlet
    if was_host and game.players:
        new_host = game.players[0]
        new_host.character = "Miss Scarlet"
        await send_to(new_host.player_id, "WELCOME", {
            "playerId": new_host.player_id,
            "name": new_host.name,
            "character": new_host.character,
            "host": True,
        })

    await send_lobby_update()


async def main():
    print("CLUE-LESS minimal server")
    print(f"Listening on ws://{HOST}:{PORT}")
    if HOST == "localhost":
        print("Players on this computer join with:  python3 lobby.py <your name>")
    else:
        print(f"Players join with:  python3 lobby.py <your name> {HOST}")
    async with websockets.serve(handle_client, HOST, PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
