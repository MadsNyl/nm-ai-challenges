"""
Grocery Bot — entry point.

Usage:
    source venv/bin/activate
    python grocery-bot/run.py <websocket_url>
"""

import asyncio
import json
import os
import sys
from datetime import datetime

import websockets

from strategy import decide

REPLAY_DIR = os.path.join(os.path.dirname(__file__), "replays")


MOVE_DELTAS = {
    "move_up": (0, -1), "move_down": (0, 1),
    "move_left": (-1, 0), "move_right": (1, 0),
}


async def play(ws_url: str):
    frames = []
    game_result = None
    difficulty = None
    # Desync detection: track what we expect each bot's position to be
    expected_positions = {}  # bot_id -> (x, y) or None
    desync_count = 0

    async with websockets.connect(ws_url) as ws:
        async for message in ws:
            data = json.loads(message)

            if data["type"] == "game_over":
                print(f"\nGame Over!")
                print(f"  Score: {data['score']}")
                print(f"  Rounds: {data['rounds_used']}")
                print(f"  Items delivered: {data['items_delivered']}")
                print(f"  Orders completed: {data['orders_completed']}")
                if desync_count:
                    print(f"  Desyncs detected: {desync_count}")
                game_result = data
                break

            if data["type"] == "game_state":
                # --- Desync detection ---
                # Check if bots are where we expected them to be
                desynced = False
                for bot in data["bots"]:
                    bid = bot["id"]
                    actual = tuple(bot["position"])
                    exp = expected_positions.get(bid)
                    if exp is not None and exp != actual:
                        desynced = True
                        desync_count += 1
                        print(f"  !! DESYNC R{data['round']}: B{bid} expected {exp} got {actual} — sending wait to re-sync")
                        break

                if desynced:
                    # Send wait for all bots to let server catch up
                    actions = [{"bot": b["id"], "action": "wait"} for b in data["bots"]]
                    expected_positions.clear()
                else:
                    actions = decide(data)

                if difficulty is None:
                    difficulty = data.get("difficulty", "unknown")

                # Log progress periodically
                r = data["round"]
                if r % 25 == 0 or r < 3:
                    _log_round(data, actions)

                # Record expected positions for next round
                for bot, act in zip(data["bots"], actions):
                    pos = tuple(bot["position"])
                    if act["action"] in MOVE_DELTAS:
                        dx, dy = MOVE_DELTAS[act["action"]]
                        expected_positions[bot["id"]] = (pos[0] + dx, pos[1] + dy)
                    elif act["action"] in ("pick_up", "drop_off", "wait"):
                        expected_positions[bot["id"]] = pos
                    else:
                        expected_positions[bot["id"]] = None

                frames.append({"state": data, "actions": actions})

                await ws.send(json.dumps({"actions": actions}))

    save_replay(frames, game_result, difficulty)



def _log_round(state, actions):
    """Print a compact summary of the current round."""
    r = state["round"]
    score = state["score"]
    bots = state["bots"]
    orders = state["orders"]

    active = next((o for o in orders if o["status"] == "active"), None)
    order_info = ""
    if active:
        delivered = len(active["items_delivered"])
        total = len(active["items_required"])
        order_info = f"order {delivered}/{total}"

    bot_parts = []
    for i, bot in enumerate(bots):
        inv = len(bot["inventory"])
        act = actions[i]["action"] if i < len(actions) else "?"
        bot_parts.append(f"B{bot['id']}:{act}(inv={inv})")

    print(f"  R{r:3d} | score={score:3d} | {order_info} | {' '.join(bot_parts)}")


def save_replay(frames, game_result, difficulty):
    """Save replay data to a JSON file."""
    os.makedirs(REPLAY_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    difficulty = difficulty or "unknown"
    filename = f"{timestamp}_{difficulty}.json"
    filepath = os.path.join(REPLAY_DIR, filename)

    replay = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "difficulty": difficulty,
        },
        "frames": frames,
        "result": game_result,
    }

    with open(filepath, "w") as f:
        json.dump(replay, f)

    print(f"\nReplay saved: {filepath}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python grocery-bot/run.py <websocket_url>")
        sys.exit(1)
    asyncio.run(play(sys.argv[1]))


if __name__ == "__main__":
    main()
