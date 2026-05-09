
from dataclasses import dataclass


@dataclass(frozen=True)
class SteamGame:
    app_id: int
    name: str


GAMES = {
    "1": SteamGame(app_id=730, name="cs2"),
    "2": SteamGame(app_id=570, name="dota2"),
    "3": SteamGame(app_id=440, name="tf2"),
    "4": SteamGame(app_id=252490, name="rust"),
}

DEFAULT_GAME = GAMES["1"]


def choose_game() -> SteamGame:
    print("Choose game to parse:")
    print("CS2   - 1")
    print("DOTA2 - 2")
    print("TF2   - 3")
    print("Rust  - 4")

    choice = input("Game number [1]: ").strip()

    if choice == "":
        return DEFAULT_GAME

    return GAMES.get(choice, DEFAULT_GAME)
