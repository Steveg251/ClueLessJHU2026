# Clue-Less game board, connected to the server through the network client.
# Opened by lobby.py when the host starts the game.
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox

import rules as rules

# pawn color for each character; characters and starting locations come from the server
CHARACTER_COLORS = {
    "Miss Scarlet": "#e53e3e",
    "Col. Mustard": "#dd6b20",
    "Mrs. White": "#edf2f7",
    "Mr. Green": "#38a169",
    "Mrs. Peacock": "#3182ce",
    "Prof. Plum": "#805ad5",
}


class ClueGameGUI:
    MANSION_MAP = [
        ["Study",        "Hallway 1",  "Hall",          "Hallway 2",  "Lounge"],
        ["Hallway 3",    None,         "Hallway 4",     None,         "Hallway 5"],
        ["Library",      "Hallway 6",  "Billiard Room", "Hallway 7",  "Dining Room"],
        ["Hallway 8",    None,         "Hallway 9",     None,         "Hallway 10"],
        ["Conservatory", "Hallway 11", "Ballroom",      "Hallway 12", "Kitchen"],
    ]

    # Each corner room connects diagonally to the opposite corner room
    SECRET_PASSAGES = {
        "Study": "Kitchen",
        "Kitchen": "Study",
        "Lounge": "Conservatory",
        "Conservatory": "Lounge",
    }
    # Where the passage square sits inside each tile (relative x, y)
    PASSAGE_CORNERS = {
        "Study": (0.92, 0.88),         # bottom-right, facing the center
        "Lounge": (0.08, 0.88),        # bottom-left
        "Conservatory": (0.92, 0.12),  # top-right
        "Kitchen": (0.08, 0.12),       # top-left
    }

    @classmethod
    def build_adjacency(cls):
        """Derive {space: [neighbors]} from MANSION_MAP, plus secret passages."""
        adjacency = {}
        rows, cols = len(cls.MANSION_MAP), len(cls.MANSION_MAP[0])
        for r in range(rows):
            for c in range(cols):
                name = cls.MANSION_MAP[r][c]
                if name is None:
                    continue
                neighbors = []
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols and cls.MANSION_MAP[nr][nc]:
                        neighbors.append(cls.MANSION_MAP[nr][nc])
                adjacency[name] = neighbors
        for room, target in cls.SECRET_PASSAGES.items():
            adjacency[room].append(target)
        return adjacency

    @classmethod
    def build_rooms(cls):
        """Rooms sit on even rows and even columns of MANSION_MAP."""
        return {cls.MANSION_MAP[r][c]
                for r in range(0, len(cls.MANSION_MAP), 2)
                for c in range(0, len(cls.MANSION_MAP[0]), 2)}

    def __init__(self, root, client, game_state, my_id, my_cards):
        """game_state is the data of the server's GAME_STARTED message."""
        self.root = root
        self.client = client
        self.my_id = my_id
        self.my_cards = my_cards

        # Game State Variables (one entry per player in the game, in turn order)
        self.players_data = []
        for player in game_state["players"]:
            self.players_data.append({
                "id": player["playerId"],
                "name": player["name"],
                "character": player["character"],
                "color": CHARACTER_COLORS.get(player["character"], "#a0aec0"),
                "location": player["location"],
                "active": not player["eliminated"],
            })
        # characters nobody plays: still drawn on the board, moved only by suggestions
        self.unplayed = [
            {
                "character": info["character"],
                "color": CHARACTER_COLORS.get(info["character"], "#a0aec0"),
                "location": info["location"],
            }
            for info in game_state["characters"]
            if info["playerId"] is None
        ]
        self.current_turn_index = 0
        self.set_current_player(game_state["currentPlayerId"])

        me = self.find_player(my_id)
        self.root.title(f"Clue-Less - {me['name']} ({me['character']})")
        self.root.geometry("1400x750")

        # Balanced proportions allocating space to the game board
        self.root.columnconfigure(0, weight=2, uniform="group1")  # Left: Roster/Log
        self.root.columnconfigure(1, weight=6, uniform="group1")  # Center: Board (Wide)
        self.root.columnconfigure(2, weight=3, uniform="group1")  # Right: Notebook/Actions
        self.root.rowconfigure(0, weight=1)

        self.board_tiles = {}
        self.tile_frames = {}  # space name -> (tile frame, base background color)
        self.adjacency = self.build_adjacency()
        self.rooms = self.build_rooms()

        # Turn state
        self.game_over = False
        self.has_moved = False
        self.reachable = set()

        # --- COLUMN 0: ACTIVE PLAYERS & STATUS LOG ---
        self.left_frame = ttk.Frame(root, padding=10)
        self.left_frame.grid(row=0, column=0, sticky="nsew")
        self.left_frame.rowconfigure(0, weight=3)
        self.left_frame.rowconfigure(1, weight=2)
        self.left_frame.columnconfigure(0, weight=1)

        self.players_frame = ttk.LabelFrame(self.left_frame, text=" Active Players ", padding=10) # Active players panel
        self.players_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        self.create_players_panel()

        self.log_frame = ttk.LabelFrame(self.left_frame, text=" Game Action Log ", padding=10) # Message log panel
        self.log_frame.grid(row=1, column=0, sticky="nsew")
        self.create_status_log()

        # --- COLUMN 1: GAME BOARD ---
        self.board_frame = ttk.LabelFrame(root, text=" Tudor Mansion Board ", padding=10) # Game board panel
        self.board_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.create_board()

        # --- COLUMN 2: DETECTIVE NOTEPAD & ACTION BUTTONS ---
        self.right_frame = ttk.Frame(root, padding=10)
        self.right_frame.grid(row=0, column=2, sticky="nsew")
        self.right_frame.rowconfigure(0, weight=1)  # Actions bar at top
        self.right_frame.rowconfigure(1, weight=4)  # Notepad below it
        self.right_frame.columnconfigure(0, weight=1)

        self.actions_frame = ttk.LabelFrame(self.right_frame, text=" Game Actions ", padding=10) # Action buttons panel
        self.actions_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        self.create_actions_panel()
        #Notebook
        self.notepad_frame = ttk.LabelFrame(self.right_frame, text=" Detective Notebook ", padding=10) # Notebook panel
        self.notepad_frame.grid(row=1, column=0, sticky="nsew")
        self.create_notepad()

        # Initial layout rendering and starting msg
        self.update_character_tokens()
        self.log_message(f"Game started! You are {me['character']}.")
        self.log_message("Your cards: " + (", ".join(self.my_cards) or "none"))
        # the server's TURN_STARTED message (sent right after GAME_STARTED) begins the first turn

    # --- PLAYER HELPERS ---
    def find_player(self, player_id):
        for player in self.players_data:
            if player["id"] == player_id:
                return player
        return None

    def set_current_player(self, player_id):
        player = self.find_player(player_id)
        if player is not None:
            self.current_turn_index = self.players_data.index(player)

    def current_player(self):
        return self.players_data[self.current_turn_index]

    def is_my_turn(self):
        return self.current_player()["id"] == self.my_id

    def am_eliminated(self):
        return not self.find_player(self.my_id)["active"]

    def can_act(self):
        """True if this player may take a turn action now; otherwise logs why not."""
        if self.game_over:
            self.log_message("The game is over.")
            return False
        if self.am_eliminated():
            self.log_message("You have been eliminated. You can still disprove suggestions.")
            return False
        if not self.is_my_turn():
            self.log_message("It's not your turn.")
            return False
        return True

    #Initial game setup and layout
    def create_players_panel(self):
        for player in self.players_data:
            p_card = tk.Frame(self.players_frame, bd=1, relief="groove", bg="#f7fafc")
            p_card.pack(fill="x", pady=4, ipady=3)

            canvas = tk.Canvas(p_card, width=14, height=14, bg="#f7fafc", highlightthickness=0)
            canvas.pack(side="left", padx=6)
            canvas.create_rectangle(1, 1, 13, 13, fill=player["color"], outline="black")

            details_frame = tk.Frame(p_card, bg="#f7fafc")
            details_frame.pack(side="left", fill="both", expand=True)

            you = " (You)" if player["id"] == self.my_id else ""
            player["name_widget"] = tk.Label(details_frame, text=f"{player['name']}: {player['character']}{you}",
                                             font=("Arial", 8, "bold"), bg="#f7fafc", anchor="w")
            player["name_widget"].pack(fill="x")

            player["loc_widget"] = tk.Label(details_frame, text=f"Location: {player['location']}",
                                            font=("Arial", 8), fg="#4a5568", bg="#f7fafc", anchor="w")
            player["loc_widget"].pack(fill="x")

        for token in self.unplayed:
            p_card = tk.Frame(self.players_frame, bd=1, relief="groove", bg="#edf2f7")
            p_card.pack(fill="x", pady=4, ipady=3)

            canvas = tk.Canvas(p_card, width=14, height=14, bg="#edf2f7", highlightthickness=0)
            canvas.pack(side="left", padx=6)
            canvas.create_rectangle(1, 1, 13, 13, fill=token["color"], outline="#a0aec0")

            details_frame = tk.Frame(p_card, bg="#edf2f7")
            details_frame.pack(side="left", fill="both", expand=True)

            tk.Label(details_frame, text=f"{token['character']} (not in play)",
                     font=("Arial", 8), fg="#718096", bg="#edf2f7", anchor="w").pack(fill="x")
            token["loc_widget"] = tk.Label(details_frame, text=f"Location: {token['location']}",
                                           font=("Arial", 8), fg="#a0aec0", bg="#edf2f7", anchor="w")
            token["loc_widget"].pack(fill="x")

    #Players panel
    def create_status_log(self):
        self.log_text = tk.Text(self.log_frame, wrap="word", state="disabled",
                                bg="#1a202c", fg="#e2e8f0", font=("Consolas", 8))
        scrollbar = ttk.Scrollbar(self.log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

    #Message log panel
    def log_message(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    #Action buttons panel
    def create_actions_panel(self):
        self.actions_frame.columnconfigure(0, weight=1)
        self.actions_frame.columnconfigure(1, weight=1)

        self.suggestion_btn = ttk.Button(self.actions_frame, text="Make Suggestion",
                                         command=self.action_make_suggestion)
        self.suggestion_btn.grid(row=0, column=0, sticky="ew", padx=(0, 2), pady=2)

        self.accusation_btn = ttk.Button(self.actions_frame, text="Make Accusation",
                                         command=self.action_make_accusation)
        self.accusation_btn.grid(row=0, column=1, sticky="ew", padx=(2, 0), pady=2)

        self.end_btn = ttk.Button(self.actions_frame, text="⏭ End Turn", command=self.end_turn)
        self.end_btn.grid(row=1, column=0, columnspan=2, sticky="ew", pady=2)

    def disable_turn_controls(self):
        """An eliminated player keeps watching (and disproving) but can't take turns."""
        for button in (self.suggestion_btn, self.accusation_btn, self.end_btn):
            button.state(["disabled"])
        self.reachable = set()
        self.set_highlights(set())

    # --- TURN & MOVEMENT HELPERS ---
    def legal_moves(self, player):
        """Spaces the player may move to: any adjacent space (including a secret
        passage), except a hallway that another pawn is already occupying."""
        occupied = {p["location"] for p in self.players_data if p is not player}
        return {space for space in self.adjacency[player["location"]]
                if space in self.rooms or space not in occupied}

    def set_highlights(self, spaces):
        """Outline the given spaces in green; clear the outline everywhere else."""
        for name, (tile, base_bg) in self.tile_frames.items():
            tile.config(highlightbackground="#48bb78" if name in spaces else base_bg)

    def start_turn(self):
        player = self.current_player()
        self.has_moved = False

        if not self.is_my_turn():
            self.reachable = set()
            self.set_highlights(set())
            self.log_message(f"It is {player['name']}'s ({player['character']}) turn.")
            return

        self.reachable = self.legal_moves(player)
        self.set_highlights(self.reachable)
        if self.reachable:
            self.log_message("Your turn! Click a green-outlined space to move, or End Turn to stay put.")
        else:
            self.log_message("Your turn! You are boxed in and can't move.")

    # --- BUTTON COMMAND HOOKS (each sends a message to the server) ---
    def end_turn(self):
        if not self.can_act():
            return
        self.reachable = set()
        self.set_highlights(set())
        self.client.send("END_TURN")

    def action_make_suggestion(self):
        if not self.can_act():
            return
        active_player = self.current_player()
        if active_player["location"] not in self.rooms:
            messagebox.showinfo("Suggestion", "You must be inside a room to make a suggestion.")
            return
        suspect = self.picks["Suspects"].get()
        weapon = self.picks["Weapons"].get()
        if not suspect or not weapon:
            messagebox.showinfo("Suggestion", "You must select both a suspect and a weapon.")
            return
        self.client.send("SUGGESTION", room=active_player["location"], suspect=suspect, weapon=weapon) # Send the suggestion to the server

    def action_make_accusation(self):
        if not self.can_act():
            return
        suspect = self.picks["Suspects"].get()
        weapon = self.picks["Weapons"].get()
        room = self.picks["Rooms"].get()
        if not suspect or not weapon or not room:
            messagebox.showinfo("Accusation", "You must select a suspect, a weapon, and a room.")
            return
        messagebox.showwarning("FINAL ACCUSATION",
                               "Be careful! An incorrect final accusation eliminates you from the game.")
        self.client.send("ACCUSATION", suspect=suspect, weapon=weapon, room=room)

    def on_space_click(self, space_name):
        if not self.can_act():
            return
        active_player = self.current_player()
        if self.has_moved:
            self.log_message("You've already moved this turn. Make a suggestion or End Turn.")
            return
        if space_name not in self.reachable:
            self.log_message(f"{space_name} isn't a legal move from {active_player['location']}.")
            return

        # the pawn moves on every board (including this one) when the server announces the move
        self.has_moved = True
        self.reachable = set()
        self.set_highlights(set())
        self.client.send("MOVE_REQUEST", destination=space_name)

    # --- MESSAGES FROM THE SERVER ---
    def apply_state(self, state):
        """Sync every pawn with the server's public game state."""
        for info in state["players"]:
            player = self.find_player(info["playerId"])
            if player is None:
                continue
            player["location"] = info["location"]
            player["loc_widget"].config(text=f"Location: {player['location']}")
            if info["eliminated"] and player["active"]:
                player["active"] = False
                player["name_widget"].config(fg="#a0aec0")
        locations = {info["character"]: info["location"] for info in state["characters"]}
        for token in self.unplayed:
            token["location"] = locations.get(token["character"], token["location"])
            token["loc_widget"].config(text=f"Location: {token['location']}")
        self.update_character_tokens()

    def describe(self, player):
        return f"{player['name']} ({player['character']})"

    def handle_message(self, message):
        message_type = message["type"]
        data = message["data"]

        if message_type == "GAME_UPDATE":
            player = self.find_player(data.get("playerId"))
            if player is None:
                return
            who = self.describe(player)
            self.apply_state(data["state"])

            if data["event"] == "CHARACTER_MOVED":
                self.log_message(f"{who} moved from {data['from']} to {data['to']}.")

            elif data["event"] == "SUGGESTION":
                self.log_message(f"{who} suggests {data['suspect']} with the "
                                 f"{data['weapon']} in the {data['room']}.")

        elif message_type == "TURN_STARTED":
            self.set_current_player(data["playerId"])
            self.start_turn()

        elif message_type == "TURN_ENDED":
            player = self.find_player(data["playerId"])
            if player is not None:
                self.log_message(f"{self.describe(player)} ended their turn.")

        elif message_type == "PLAYER_ELIMINATED":
            player = self.find_player(data["playerId"])
            if player is None:
                return
            player["active"] = False
            player["name_widget"].config(fg="#a0aec0")
            self.log_message(f"❌ {self.describe(player)} made a wrong accusation and is eliminated.")
            if player["id"] == self.my_id:
                self.disable_turn_controls()
                self.log_message("You can no longer move, suggest or accuse, "
                                 "but you must still disprove other players' suggestions.")

        elif message_type == "GAME_WON":
            player = self.find_player(data["playerId"])
            who = self.describe(player) if player else data["name"]
            if data.get("reason") == "last_player":
                result = f"{who} is the last player left and wins!"
            else:
                result = f"{who} solved the case and wins!"
            case = data["caseFile"]
            answer = f"It was {case['suspect']} with the {case['weapon']} in the {case['room']}."

            self.game_over = True
            self.disable_turn_controls()
            self.log_message(f"🏆 {result}")
            self.log_message(f"📁 {answer}")
            messagebox.showinfo("Game Over", f"{result}\n\n{answer}")

        elif message_type == "DISPROVE_REQUEST":
            suggester = self.find_player(data["suggesterId"])
            who = self.describe(suggester) if suggester else data["suggesterName"]
            self.log_message(f"You can disprove {who}'s suggestion. Choose a card to show them.")
            self.ask_disprove_card(who, data)

        elif message_type == "CARD_SHOWN":
            disprover = self.find_player(data["disproverId"])
            who = self.describe(disprover) if disprover else data["disproverName"]
            self.log_message(f"🔍 {who} showed you: {data['card']}")
            messagebox.showinfo("Suggestion Disproved", f"{who} showed you the card:\n\n{data['card']}")

        elif message_type == "SUGGESTION_DISPROVED":
            suggester = self.find_player(data["suggesterId"])
            disprover = self.find_player(data["disproverId"])
            suggester_text = f"{self.describe(suggester)}'s" if suggester else "the"
            disprover_text = self.describe(disprover) if disprover else data["disproverName"]
            self.log_message(f"{disprover_text} disproved {suggester_text} suggestion.")

        elif message_type == "SUGGESTION_NOT_DISPROVED":
            suggester = self.find_player(data["suggesterId"])
            who = f"{self.describe(suggester)}'s" if suggester else "the"
            self.log_message(f"Nobody could disprove {who} suggestion of {data['suspect']} "
                             f"with the {data['weapon']} in the {data['room']}.")

        elif message_type == "ERROR":
            self.log_message(f"Server error: {data['message']}")

    def ask_disprove_card(self, suggester, request):
        """Pop-up where this player picks which matching card to show the suggester.
        It can't be dismissed without choosing: the game waits on this answer."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Disprove the Suggestion")
        dialog.transient(self.root)
        dialog.protocol("WM_DELETE_WINDOW", lambda: None)
        self.disprove_dialog = dialog

        ttk.Label(dialog, padding=(15, 12, 15, 4), wraplength=320,
                  text=f"{suggester} suggests {request['suspect']} with the {request['weapon']} "
                       f"in the {request['room']}.").pack()
        ttk.Label(dialog, padding=(15, 0, 15, 8),
                  text="Choose one card to show (only they will see it):").pack()

        choice = tk.StringVar(value=request["cards"][0])
        for card in request["cards"]:
            ttk.Radiobutton(dialog, text=card, variable=choice, value=card).pack(anchor="w", padx=30)

        def show_card():
            self.client.send("DISPROVE_RESPONSE", card=choice.get())
            self.log_message(f"You showed {choice.get()} to {suggester}.")
            self.disprove_dialog = None
            dialog.destroy()

        ttk.Button(dialog, text="Show Card", command=show_card).pack(pady=12)

    def create_board(self):
        rows, cols = len(self.MANSION_MAP), len(self.MANSION_MAP[0])
        for i in range(cols):
            self.board_frame.columnconfigure(i, weight=1)
        for i in range(rows):
            self.board_frame.rowconfigure(i, weight=1)

        for r in range(rows):
            for c in range(cols):
                space_name = self.MANSION_MAP[r][c]
                if space_name is None:
                    continue

                is_room = space_name in self.rooms
                bg_color = "#2d3748" if is_room else "#d69e2e"
                fg_color = "white" if is_room else "black"

                # highlightthickness is always 3 so highlighting never shifts the layout
                tile = tk.Frame(self.board_frame, bg=bg_color, relief="raised", bd=2,
                                highlightthickness=3, highlightbackground=bg_color)
                tile.grid(row=r, column=c, sticky="nsew", padx=3, pady=3)
                self.tile_frames[space_name] = (tile, bg_color)

                lbl = tk.Label(tile, text=space_name, bg=bg_color, fg=fg_color, font=("Arial", 9, "bold"))
                lbl.pack(pady=2)

                token_area = tk.Frame(tile, bg=bg_color)
                token_area.pack(fill="both", expand=True)

                self.board_tiles[space_name] = token_area

                for w in (tile, lbl, token_area):
                    w.bind("<Button-1>", lambda event, name=space_name: self.on_space_click(name))

                # Secret passage marker: clicking it uses the passage to the linked room
                if space_name in self.SECRET_PASSAGES:
                    relx, rely = self.PASSAGE_CORNERS[space_name]
                    passage = tk.Frame(tile, width=14, height=14, bg="#f6e05e",
                                       highlightbackground="black", highlightthickness=1)
                    passage.place(relx=relx, rely=rely, anchor="center")
                    target = self.SECRET_PASSAGES[space_name]
                    passage.bind("<Button-1>", lambda event, name=target: self.on_space_click(name))

    def update_character_tokens(self):
        for space_name, token_area in self.board_tiles.items():
            for child in token_area.winfo_children():
                child.destroy()

        for player in self.players_data + self.unplayed:
            loc = player["location"]
            if loc in self.board_tiles:
                parent_area = self.board_tiles[loc]
                pawn = tk.Canvas(parent_area, width=12, height=12, bg=parent_area.cget("bg"),
                                 highlightthickness=0)
                pawn.pack(side="left", padx=2, pady=2)
                pawn.create_rectangle(1, 1, 11, 11, fill=player["color"], outline="black")
                pawn.bind("<Button-1>", lambda event, name=loc: self.on_space_click(name))

    def create_notepad(self):
        suspects = rules.SUSPECTS
        weapons = rules.WEAPONS
        rooms = rules.ROOM_CARDS

        canvas = tk.Canvas(self.notepad_frame, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.notepad_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        # Keep the scroll region in sync with the content size
        scrollable_frame.bind("<Configure>",
                              lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mouse wheel scrolling while the cursor is over the notebook
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        self.notepad_vars = {} # the notepad for ruling out a card
        # one pick per category (suspect, weapon, room)
        self.picks = {
            "Suspects": tk.StringVar(),
            "Weapons": tk.StringVar(),
            "Rooms": tk.StringVar(),
        }
        ttk.Label(scrollable_frame, text="Ruled out", foreground="#718096").grid(row=0, column=0, sticky="w", padx=10)
        ttk.Label(scrollable_frame, text="Your Picks", foreground="#718096").grid(row=0, column=1, sticky="w", padx=10)
        current_row = 0

        def add_section(title, items):
            nonlocal current_row
            lbl = ttk.Label(scrollable_frame, text=title, font=("Arial", 11, "bold"), foreground="#1a365d")
            lbl.grid(row=current_row, column=0, columnspan=2, sticky="w", pady=(8, 4))
            current_row += 1
            for item in items:
                var = tk.BooleanVar(value=False)
                self.notepad_vars[item] = var
                chk = ttk.Checkbutton(scrollable_frame, text=item, variable=var)
                chk.grid(row=current_row, column=0, sticky="w", padx=10, pady=1)
                # Add a radio button for the user's pick
                pick_var = self.picks[title]
                rdo = ttk.Radiobutton(scrollable_frame, text=item, variable=pick_var, value=item)
                rdo.grid(row=current_row, column=1, sticky="w", padx=10, pady=1)
                current_row += 1

        add_section("Suspects", suspects)
        add_section("Weapons", weapons)
        add_section("Rooms", rooms)
