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



async def play(ws_url: str):
    frames = []
    game_result = None
    difficulty = None

    async with websockets.connect(ws_url) as ws:
        async for message in ws:
            data = json.loads(message)

            if data["type"] == "game_over":
                print(f"\nGame Over!")
                print(f"  Score: {data['score']}")
                print(f"  Rounds: {data['rounds_used']}")
                print(f"  Items delivered: {data['items_delivered']}")
                print(f"  Orders completed: {data['orders_completed']}")
                game_result = data
                break

            if data["type"] == "game_state":
                actions = decide(data)

                if difficulty is None:
                    difficulty = data.get("difficulty", "unknown")

                # Log progress periodically
                r = data["round"]
                if r % 25 == 0 or r < 3:
                    _log_round(data, actions)

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
