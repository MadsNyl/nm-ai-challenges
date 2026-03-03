"""
Exploration script — connects to the game, prints the map and state,
then plays with a simple greedy bot so we can see how the game works.
"""

import asyncio
import json
import websockets

WS_URL = "wss://game.ainm.no/ws?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0ZWFtX2lkIjoiNTllYWY5MjgtMzNlNS00YTVjLTk1NzItNmUzZDk3MGM4NzQ2IiwibWFwX2lkIjoiYzg5ZGEyZWMtM2NhNy00MGM5LWEzYjEtODAzNmZjYTNkMGI3IiwibWFwX3NlZWQiOjcwMDEsImRpZmZpY3VsdHkiOiJlYXN5IiwiZXhwIjoxNzcyNTYwNjk0fQ.RLh2v1zyD78UOr_mCgRZsZ4PHwHop_lIecKVIhRa-24"


def render_map(state):
    """Render the grid as a visual ASCII map."""
    w = state["grid"]["width"]
    h = state["grid"]["height"]
    walls = set(tuple(p) for p in state["grid"]["walls"])
    items_by_pos = {}
    for item in state["items"]:
        pos = tuple(item["position"])
        items_by_pos[pos] = item["type"]
    bot_positions = {}
    for bot in state["bots"]:
        bot_positions[tuple(bot["position"])] = bot["id"]
    drop_off = tuple(state["drop_off"])

    print(f"\n{'='*40}")
    print(f"  Round {state['round']}/{state['max_rounds']}  |  Score: {state['score']}")
    print(f"{'='*40}")

    for y in range(h):
        row = ""
        for x in range(w):
            pos = (x, y)
            if pos in bot_positions:
                row += f" {bot_positions[pos]} "
            elif pos == drop_off:
                row += " D "
            elif pos in walls:
                row += "###"
            elif pos in items_by_pos:
                # Show first 2 chars of item type
                label = items_by_pos[pos][:2]
                row += f"[{label}]"[0:3]
            else:
                row += " . "
        print(row)
    print()


def print_orders(state):
    """Print current orders."""
    for order in state["orders"]:
        status = order["status"].upper()
        needed = list(order["items_required"])
        delivered = list(order["items_delivered"])
        remaining = needed.copy()
        for d in delivered:
            if d in remaining:
                remaining.remove(d)
        print(f"  [{status}] {order['id']}: need {remaining} (delivered {delivered})")


def print_bots(state):
    """Print bot positions and inventories."""
    for bot in state["bots"]:
        print(f"  Bot {bot['id']}: pos={bot['position']} inv={bot['inventory']}")


async def play():
    async with websockets.connect(WS_URL) as ws:
        async for message in ws:
            data = json.loads(message)

            if data["type"] == "game_over":
                print(f"\n{'='*40}")
                print(f"  GAME OVER")
                print(f"  Score: {data['score']}")
                print(f"  Rounds used: {data['rounds_used']}")
                print(f"  Items delivered: {data['items_delivered']}")
                print(f"  Orders completed: {data['orders_completed']}")
                print(f"{'='*40}")
                break

            if data["type"] == "game_state":
                # Print detailed info on first round
                if data["round"] == 0:
                    print("\n--- FULL INITIAL STATE (JSON) ---")
                    print(json.dumps(data, indent=2))
                    print("--- END INITIAL STATE ---\n")

                # Print map every 10 rounds
                if data["round"] % 10 == 0:
                    render_map(data)
                    print("Orders:")
                    print_orders(data)
                    print("Bots:")
                    print_bots(data)

                # Simple greedy actions
                actions = decide_actions(data)
                await ws.send(json.dumps({"actions": actions}))


def decide_actions(state):
    """Simple greedy bot — go to nearest needed item, pick up, deliver."""
    actions = []
    for bot in state["bots"]:
        action = decide_bot_action(bot, state)
        actions.append(action)
    return actions


def decide_bot_action(bot, state):
    bx, by = bot["position"]
    inventory = bot["inventory"]
    items = state["items"]
    orders = state["orders"]
    drop_off = tuple(state["drop_off"])

    active = next((o for o in orders if o.get("status") == "active" and not o["complete"]), None)
    if not active:
        return {"bot": bot["id"], "action": "wait"}

    # What does the active order still need?
    needed = {}
    for item in active["items_required"]:
        needed[item] = needed.get(item, 0) + 1
    for item in active["items_delivered"]:
        needed[item] = needed.get(item, 0) - 1
    needed = {k: v for k, v in needed.items() if v > 0}

    # Check if we have useful items
    has_useful = any(needed.get(item, 0) > 0 for item in inventory)

    # If at dropoff with useful items, deliver
    if has_useful and bx == drop_off[0] and by == drop_off[1]:
        return {"bot": bot["id"], "action": "drop_off"}

    # If inventory full or we have all needed items, go deliver
    if len(inventory) >= 3 or (has_useful and not needed):
        return navigate_to(bot["id"], bx, by, drop_off[0], drop_off[1])

    # If we have useful items and nothing left to pick, go deliver
    if has_useful:
        still_need = needed.copy()
        for item in inventory:
            if item in still_need and still_need[item] > 0:
                still_need[item] -= 1
        still_need = {k: v for k, v in still_need.items() if v > 0}
        if not still_need:
            return navigate_to(bot["id"], bx, by, drop_off[0], drop_off[1])

    # Find nearest needed item
    best_item = None
    best_dist = float("inf")
    for item in items:
        if needed.get(item["type"], 0) > 0:
            ix, iy = item["position"]
            dist = abs(bx - ix) + abs(by - iy)
            if dist < best_dist:
                best_dist = dist
                best_item = item

    if best_item:
        ix, iy = best_item["position"]
        if abs(bx - ix) + abs(by - iy) == 1:
            return {"bot": bot["id"], "action": "pick_up", "item_id": best_item["id"]}
        return navigate_to(bot["id"], bx, by, ix, iy)

    # If we have anything useful, go deliver
    if has_useful:
        return navigate_to(bot["id"], bx, by, drop_off[0], drop_off[1])

    return {"bot": bot["id"], "action": "wait"}


def navigate_to(bot_id, x, y, tx, ty):
    """Simple Manhattan navigation — no pathfinding, gets stuck on walls."""
    dx = tx - x
    dy = ty - y
    if abs(dx) > abs(dy):
        return {"bot": bot_id, "action": "move_right" if dx > 0 else "move_left"}
    if dy != 0:
        return {"bot": bot_id, "action": "move_down" if dy > 0 else "move_up"}
    if dx != 0:
        return {"bot": bot_id, "action": "move_right" if dx > 0 else "move_left"}
    return {"bot": bot_id, "action": "wait"}


asyncio.run(play())
