"""
Clue-Less rules shared by server.py and board.py.

This module holds the fixed facts of the game (board, characters, cards) and the
rule checks as plain functions. It holds no game in progress: who stands where,
who holds which cards, and whose turn it is belong to the server's game state.

"""
import random

MIN_PLAYERS = 3
MAX_PLAYERS = 6

#the board 
MANSION_MAP = [
    ["Study",        "Hallway 1",  "Hall",          "Hallway 2",  "Lounge"],
    ["Hallway 3",    None,         "Hallway 4",     None,         "Hallway 5"],
    ["Library",      "Hallway 6",  "Billiard Room", "Hallway 7",  "Dining Room"],
    ["Hallway 8",    None,         "Hallway 9",     None,         "Hallway 10"],
    ["Conservatory", "Hallway 11", "Ballroom",      "Hallway 12", "Kitchen"],
]

# Secret passage dict, connects opposite corner rooms
SECRET_PASSAGES = {
    "Study": "Kitchen",
    "Kitchen": "Study",
    "Lounge": "Conservatory",
    "Conservatory": "Lounge",
}

# Build adjacency list for all spaces, including secret passages
def build_adjacency(): 
    adjacency = {}
    rows, cols = len(MANSION_MAP), len(MANSION_MAP[0])
    for r in range(rows):
        for c in range(cols):
            name = MANSION_MAP[r][c]
            if name is None:
                continue
            neighbours = []
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols and MANSION_MAP[nr][nc]:
                    neighbours.append(MANSION_MAP[nr][nc])
            adjacency[name] = neighbours
    for room, target in SECRET_PASSAGES.items():
        adjacency[room].append(target)
    return adjacency

#builds out the set of rooms from mansion map
def build_rooms():
    return {MANSION_MAP[r][c]
            for r in range(0, len(MANSION_MAP), 2)
            for c in range(0, len(MANSION_MAP[0]), 2)}


ADJACENCY = build_adjacency()
ROOMS = build_rooms()
HALLWAYS = {name for row in MANSION_MAP for name in row if name} - ROOMS

# characters available, will be handed out in order joined for now
# need to add character select later
# host should always be Miss Scarlet
CHARACTERS = ["Miss Scarlet", "Col. Mustard", "Mrs. White",
              "Mr. Green", "Mrs. Peacock", "Prof. Plum"]

# Starting positions for each character
START = {
    "Miss Scarlet": "Hallway 2",
    "Col. Mustard": "Hallway 5",
    "Mrs. White":   "Hallway 12",
    "Mr. Green":    "Hallway 11",
    "Mrs. Peacock": "Hallway 8",
    "Prof. Plum":   "Hallway 3",
}

# Cards available
SUSPECTS = list(CHARACTERS)
WEAPONS = ["Candlestick", "Knife", "Lead Pipe", "Revolver", "Rope", "Wrench"]
ROOM_CARDS = ["Kitchen", "Ballroom", "Conservatory", "Dining Room", "Billiard Room",
              "Library", "Lounge", "Hall", "Study"]    # same names as the board rooms
ALL_CARDS = SUSPECTS + WEAPONS + ROOM_CARDS


def starting_positions(): #initial starting positions for each character
    return dict(START)


# Movement rules
def legal_moves(location, occupied): # returns the set of legal moves from the current location
    return {space for space in ADJACENCY[location]
            if space in ROOMS or space not in occupied}


def is_boxed_in(location, occupied): #handles checking if a character is completely blocked in all directions
    return not legal_moves(location, occupied)


def move_error(location, destination, occupied, has_moved): # returns an error message if the move is illegal, otherwise None
    if has_moved:
        return "You have already moved this turn."
    if destination not in ADJACENCY[location]:
        return f"{destination} is not next to {location}."
    if destination in HALLWAYS and destination in occupied:
        return f"{destination} is occupied."
    return None


def end_turn_error(started_in_hallway, has_moved, has_suggested): # checks if the player can end their turn, returns an error message if not
    if started_in_hallway and not has_moved:
        return "You are in a hallway: move to one of its two rooms before ending your turn."
    if started_in_hallway and not has_suggested:
        return "After leaving a hallway you must make a suggestion."
    return None


# Suggestions and accusations, suggestions have a lot of rules about when they can be made and by whom
def suggestion_error(location, moved_this_turn, moved_by_suggestion,
                     has_suggested, suspect, weapon): # returns an error message if the suggestion is illegal, otherwise None
    if location not in ROOMS:
        return "You must be in a room to make a suggestion."
    if has_suggested:
        return "You have already made a suggestion this turn."
    if not (moved_this_turn or moved_by_suggestion):
        return ("You can only suggest after moving into a room, or if another "
                "player's suggestion moved you here.")
    if suspect not in SUSPECTS: # check if the suspect is a valid card
        return f"Unknown suspect: {suspect}."
    if weapon not in WEAPONS: # check if the weapon is a valid card
        return f"Unknown weapon: {weapon}."
    return None


def accusation_error(suspect, weapon, room): # returns an error message if the accusation is illegal, otherwise None
    if suspect not in SUSPECTS: # check if the suspect is a valid card
        return f"Unknown suspect: {suspect}."
    if weapon not in WEAPONS: # check if the weapon is a valid card
        return f"Unknown weapon: {weapon}."
    if room not in ROOM_CARDS: # check if the room is a valid card
        return f"Unknown room: {room}."
    return None


def accusation_is_correct(case_file, suspect, weapon, room): # returns True if the accusation matches the case file, someone wins the game
    return (case_file["suspect"] == suspect
            and case_file["weapon"] == weapon
            and case_file["room"] == room)


#Dealing out cards to players
def deal(player_ids, rng=random): # deals out the cards to players, returns (case_file, hands)
    if not MIN_PLAYERS <= len(player_ids) <= MAX_PLAYERS: # check if the number of players is within the allowed range
        raise ValueError(f"A game needs {MIN_PLAYERS} to {MAX_PLAYERS} players.")
    case_file = {"suspect": rng.choice(SUSPECTS), #first thing first, dealing out the case file
                 "weapon": rng.choice(WEAPONS),
                 "room": rng.choice(ROOM_CARDS)}
    rest = [card for card in ALL_CARDS if card not in case_file.values()] # the remaining cards to be dealt to players
    rng.shuffle(rest) # shuffle the remaining cards before dealing
    hands = {pid: [] for pid in player_ids} # initialize empty hands for each player
    for i, card in enumerate(rest): # deal the remaining cards round-robin
        hands[player_ids[i % len(player_ids)]].append(card)
    return case_file, hands # return the case file and the dealt hands


def matching_cards(hand, suspect, weapon, room): # returns the cards in `hand` that match the suggestion
    return [card for card in hand if card in (suspect, weapon, room)]


def disproof_order(order, suggester_id): #everony gets asked to disprove in order, starting after the suggester and wrapping around the table, uses index in `order`
    # applies to everyone after the suggestion
    i = order.index(suggester_id)
    return order[i + 1:] + order[:i]


def next_turn_index(order, current_index, active_ids): # returns the index of the next player who can take a turn, or None if nobody can
    n = len(order)
    for step in range(1, n + 1):
        i = (current_index + step) % n
        if order[i] in active_ids:
            return i
    return None


