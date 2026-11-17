#Start button and lobby system for Clue-Less
# Run with: python3 lobby.py <player name> <server's Tailscale IP>   (start server.py first; see README.md)
#   same computer as the server:  python3 lobby.py Scarlet
#   different computer:           python3 lobby.py Mustard 100.64.1.5
# server.py prints the exact command to use when it starts
import sys
import tkinter as tk
from tkinter import ttk

import rules
from network_client import NetworkClient
from board import ClueGameGUI

HOST_CHARACTER = "Miss Scarlet"  # the server always gives the host Miss Scarlet

MAX_PLAYERS = 6
BG = "#1e1e2e"

PLAYER_NAME = sys.argv[1] if len(sys.argv) > 1 else "Player"

# connects to the server on this computer unless the server's Tailscale IP is given
SERVER_IP = sys.argv[2] if len(sys.argv) > 2 else "localhost"
SERVER_URI = "ws://" + SERVER_IP + ":8765"

root = tk.Tk()
root.title("Clue-Less - " + PLAYER_NAME)
root.geometry("420x680")
root.configure(bg=BG)

players = []  # players currently in the lobby: dicts with playerId, name, character (host first)
client = None  # connection to the server, created when entering the lobby
my_id = None  # id the server gave this player
my_cards = []  # this player's hand, sent by the server when the game starts
game = None  # game board, created when the host starts the game

# ---------- Frames (one per screen) ----------
menu_frame = tk.Frame(root, bg=BG)
lobby_frame = tk.Frame(root, bg=BG)

def show_frame(frame):
    menu_frame.pack_forget()
    lobby_frame.pack_forget()
    frame.pack(fill="both", expand=True)

# ---------- Lobby logic ----------
def find_me():
    for player in players:
        if player["playerId"] == my_id:
            return player
    return None

def refresh_lobby():
    for i, slot in enumerate(slot_labels):
        if i < len(players):
            player = players[i]
            text = player["name"]
            if i == 0:
                text += " (Host)"
            if player["playerId"] == my_id:
                text += " (You)"
            text += " - " + (player["character"] or "choosing...")
            slot.config(text=text, fg="#a6e3a1" if player["character"] else "#f9e2af")
        else:
            slot.config(text="Waiting for player...", fg="#6c7086")
    count_label.config(text=f"Players: {len(players)}/{MAX_PLAYERS}")
    refresh_character_picker()

def refresh_character_picker():
    """Offer only the characters nobody else has taken; the host is locked to Miss Scarlet."""
    me = find_me()
    if me is None:
        character_picker.set("")
        character_picker.config(values=[], state="disabled")
        picker_hint.config(text="")
        return

    if players[0] is me:
        character_picker.config(values=[HOST_CHARACTER], state="disabled")
        character_picker.set(HOST_CHARACTER)
        picker_hint.config(text="The host always plays Miss Scarlet.")
        return

    taken = {player["character"] for player in players if player is not me}
    available = [c for c in rules.CHARACTERS if c != HOST_CHARACTER and c not in taken]
    character_picker.config(values=available, state="readonly")
    character_picker.set(me["character"] or "")
    picker_hint.config(text="" if me["character"] else "Pick a character before the host starts.")

def choose_character(_event=None):
    me = find_me()
    choice = character_picker.get()
    if client is None or me is None or not choice or choice == me["character"]:
        return
    client.send("SELECT_CHARACTER", character=choice)
    show_status("Choosing " + choice + "...")

def show_status(text):
    status_label.config(text=text)

# ---------- Network ----------
def handle_server_message(message):
    global my_id, game

    # once the game starts, the board handles the messages
    if game is not None:
        game.handle_message(message)
        return

    message_type = message["type"]
    data = message["data"]

    if message_type == "LOBBY_UPDATE":
        # the first player in the list is the host
        players[:] = data["players"]
        refresh_lobby()
        me = find_me()
        if me is not None and me["character"]:
            show_status("You are " + me["character"])
    elif message_type == "WELCOME":
        my_id = data["playerId"]
        show_status("Joined as " + data["name"] + (" (Host)" if data["host"] else ""))
        refresh_lobby()
    elif message_type == "ERROR":
        print("Server error:", data["message"])
        show_status("Server error: " + data["message"])
        # e.g. someone else grabbed that character first: show what we really have
        refresh_character_picker()
    elif message_type == "HAND":
        # sent just before GAME_STARTED; kept until the board exists
        my_cards[:] = data["cards"]
    elif message_type == "GAME_STARTED":
        print("The host started the game.")
        # hide the lobby and open the game board for every player
        root.withdraw()
        board_window = tk.Toplevel(root)
        board_window.protocol("WM_DELETE_WINDOW", root.destroy)
        game = ClueGameGUI(board_window, client, data, my_id, list(my_cards))

def handle_network_status(status):
    print(status)

def poll_network():
    if client is not None:
        client.poll()
    root.after(100, poll_network)

def enter_lobby():
    global client, my_id
    my_id = None
    players.clear()
    refresh_lobby()
    show_status("Connecting...")
    show_frame(lobby_frame)

    # connect to the server, the server sends the lobby list once we join
    client = NetworkClient(SERVER_URI, PLAYER_NAME, handle_server_message, handle_network_status)
    client.start()

def leave_lobby():
    global client
    if client is not None:
        client.close()
        client = None
    players.clear()
    show_frame(menu_frame)

# ---------- Menu screen ----------
tk.Label(menu_frame, text="Clue-Less", font=("Arial", 32, "bold"),
         fg="white", bg=BG).pack(pady=(100, 30))

tk.Button(menu_frame, text="Start Game", font=("Arial", 18), width=10,
          command=enter_lobby).pack()

# ---------- Lobby screen ----------
tk.Label(lobby_frame, text="Lobby", font=("Arial", 28, "bold"),
         fg="white", bg=BG).pack(pady=(30, 5))

count_label = tk.Label(lobby_frame, font=("Arial", 14), fg="white", bg=BG)
count_label.pack(pady=(0, 15))

slot_labels = []
for _ in range(MAX_PLAYERS):
    lbl = tk.Label(lobby_frame, font=("Arial", 13), width=34,
                   bg="#313244", pady=6)
    lbl.pack(pady=3)
    slot_labels.append(lbl)

picker_row = tk.Frame(lobby_frame, bg=BG)
picker_row.pack(pady=(15, 0))
tk.Label(picker_row, text="Your character:", font=("Arial", 12),
         fg="white", bg=BG).grid(row=0, column=0, padx=5)
character_picker = ttk.Combobox(picker_row, width=16, state="disabled")
character_picker.grid(row=0, column=1, padx=5)
character_picker.bind("<<ComboboxSelected>>", choose_character)
picker_hint = tk.Label(lobby_frame, font=("Arial", 11), fg="#6c7086", bg=BG)
picker_hint.pack()

button_row = tk.Frame(lobby_frame, bg=BG)
button_row.pack(pady=20)

tk.Button(button_row, text="Leave", font=("Arial", 12), width=8,
          command=leave_lobby).grid(row=0, column=0, padx=5)

#temporary button to simulate players joining while you test
tk.Button(button_row, text="Start Game", font=("Arial", 12), width=12,
          command=lambda: client.send("START_GAME")).grid(row=0, column=1, padx=5)

# shows the latest message from the server
status_label = tk.Label(lobby_frame, font=("Arial", 12), fg="#f9e2af", bg=BG, wraplength=350)
status_label.pack(pady=5)

# ---------- Start ----------
show_frame(menu_frame)
poll_network()
root.mainloop()
