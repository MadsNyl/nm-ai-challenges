import asyncio
import json
from collections import deque

import websockets

WS_URL = "wss://game.ainm.no/ws?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0ZWFtX2lkIjoiNTllYWY5MjgtMzNlNS00YTVjLTk1NzItNmUzZDk3MGM4NzQ2IiwibWFwX2lkIjoiYzg5ZGEyZWMtM2NhNy00MGM5LWEzYjEtODAzNmZjYTNkMGI3IiwibWFwX3NlZWQiOjcwMDEsImRpZmZpY3VsdHkiOiJlYXN5IiwiZXhwIjoxNzcyNTcwMzY2fQ.1OX6DE-ZoKEb9C5lcaTIuc4gDPej8fGMkCoGaY6meaw"


# ---------------------------------------------------------------------------
# Pathfinding
# ---------------------------------------------------------------------------

def bfs(start, goal, walls_set, grid_width, grid_height):
    """Return list of (x, y, action) steps from start to goal (exclusive of start)."""
    if start == goal:
        return []

    queue = deque([(start, [])])
    visited = {start}

    while queue:
        (x, y), path = queue.popleft()
        for dx, dy, action in [
            (0, -1, "move_up"),
            (0,  1, "move_down"),
            (-1, 0, "move_left"),
            ( 1, 0, "move_right"),
        ]:
            nx, ny = x + dx, y + dy
            if (nx, ny) in visited:
                continue
            if nx < 0 or ny < 0 or nx >= grid_width or ny >= grid_height:
                continue
            if (nx, ny) in walls_set:
                continue
            new_path = path + [(nx, ny, action)]
            if (nx, ny) == goal:
                return new_path
            visited.add((nx, ny))
            queue.append(((nx, ny), new_path))

    return []


def next_action_towards(bot_id, start, goal, walls_set, grid_width, grid_height):
    """Return the action dict to take one BFS step towards goal."""
    path = bfs(start, goal, walls_set, grid_width, grid_height)
    if not path:
        return {"bot": bot_id, "action": "wait"}
    _, _, action = path[0]
    return {"bot": bot_id, "action": action}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def needed_items(order):
    """Return dict of {item_type: count_still_needed} for an order."""
    if order is None:
        return {}
    needed = {}
    for item in order["items_required"]:
        needed[item] = needed.get(item, 0) + 1
    for item in order["items_delivered"]:
        needed[item] = needed.get(item, 0) - 1
    return {k: v for k, v in needed.items() if v > 0}


def _walkable_adjacent(x, y, walls_set, grid_w, grid_h):
    """Return walkable cells adjacent to (x, y)."""
    return [
        (nx, ny)
        for nx, ny in [(x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)]
        if 0 <= nx < grid_w and 0 <= ny < grid_h and (nx, ny) not in walls_set
    ]


# ---------------------------------------------------------------------------
# Item targeting
# ---------------------------------------------------------------------------

def _find_target_items(carrying, active_needed, preview_needed, items, slots_left, claimed_item_ids):
    """Find items worth picking up: active order first, then preview to fill remaining slots.

    Respects per-type counts and claimed_item_ids to avoid multi-bot conflicts.
    """
    still_active = {
        k: v - carrying.get(k, 0)
        for k, v in active_needed.items()
        if v - carrying.get(k, 0) > 0
    }
    still_preview = {
        k: v - carrying.get(k, 0)
        for k, v in preview_needed.items()
        if v - carrying.get(k, 0) > 0
    }

    # Collect active-order targets first (respect per-type count)
    active_targets = []
    active_count = {}
    for item in items:
        if len(active_targets) >= slots_left:
            break
        if item["id"] in claimed_item_ids:
            continue
        t = item["type"]
        if t in still_active and active_count.get(t, 0) < still_active[t]:
            active_targets.append(item)
            active_count[t] = active_count.get(t, 0) + 1

    # Fill remaining slots with preview targets (only types not in active)
    preview_targets = []
    preview_count = {}
    remaining_slots = slots_left - len(active_targets)
    for item in items:
        if len(preview_targets) >= remaining_slots:
            break
        if item["id"] in claimed_item_ids:
            continue
        t = item["type"]
        if t in still_preview and t not in still_active and preview_count.get(t, 0) < still_preview[t]:
            preview_targets.append(item)
            preview_count[t] = preview_count.get(t, 0) + 1

    return active_targets + preview_targets


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------

def decide_actions(state, shelf_positions):
    walls_set = set(map(tuple, state["grid"]["walls"])) | shelf_positions
    grid_w = state["grid"]["width"]
    grid_h = state["grid"]["height"]
    drop_off = tuple(state["drop_off"])
    bots = state["bots"]
    items = state["items"]
    orders = state["orders"]

    active_order = next((o for o in orders if o.get("status") == "active"), None)
    preview_order = next((o for o in orders if o.get("status") == "preview"), None)

    # Compute needed items once for all bots
    active_needed = needed_items(active_order)
    preview_needed = needed_items(preview_order)

    # claimed_item_ids prevents two bots from targeting the same physical item.
    # Bots are processed in ID order (matching server resolution order).
    claimed_item_ids = set()
    actions = []
    for bot in bots:
        action = decide_bot(
            bot, active_needed, preview_needed,
            items, drop_off, walls_set, grid_w, grid_h,
            claimed_item_ids
        )
        actions.append(action)

    return actions


def decide_bot(bot, active_needed, preview_needed,
               items, drop_off, walls_set, grid_w, grid_h,
               claimed_item_ids):
    bot_id = bot["id"]
    bx, by = bot["position"]
    pos = (bx, by)
    inventory = bot["inventory"]

    # Count carried items by type
    carrying = {}
    for i in inventory:
        carrying[i] = carrying.get(i, 0) + 1

    useful_for_active = [i for i in inventory if active_needed.get(i, 0) > 0]

    # Active items still needed beyond what this bot already carries
    still_need_active = {
        k: v - carrying.get(k, 0)
        for k, v in active_needed.items()
        if v - carrying.get(k, 0) > 0
    }

    # -----------------------------------------------------------------------
    # Deliver when: have useful items AND (full OR all active items in hand).
    # This "load up then deliver" strategy avoids unnecessary round-trips.
    # -----------------------------------------------------------------------
    should_deliver = bool(useful_for_active) and (len(inventory) >= 3 or not still_need_active)
    if should_deliver:
        if pos == drop_off:
            return {"bot": bot_id, "action": "drop_off"}
        return next_action_towards(bot_id, pos, drop_off, walls_set, grid_w, grid_h)

    # -----------------------------------------------------------------------
    # Inventory full with nothing useful → wait.
    # Going to drop-off would do nothing (non-matching items stay in inventory).
    # -----------------------------------------------------------------------
    if len(inventory) >= 3:
        return {"bot": bot_id, "action": "wait"}

    # -----------------------------------------------------------------------
    # Pick up items (active order priority, preview fills remaining slots)
    # -----------------------------------------------------------------------
    slots_left = 3 - len(inventory)
    targets = _find_target_items(
        carrying, active_needed, preview_needed, items, slots_left, claimed_item_ids
    )

    if targets:
        best = min(targets, key=lambda item: abs(bx - item["position"][0]) + abs(by - item["position"][1]))
        claimed_item_ids.add(best["id"])

        ix, iy = best["position"]
        if (ix, iy) in [(bx, by - 1), (bx, by + 1), (bx - 1, by), (bx + 1, by)]:
            return {"bot": bot_id, "action": "pick_up", "item_id": best["id"]}

        adj = _walkable_adjacent(ix, iy, walls_set, grid_w, grid_h)
        if adj:
            closest_adj = min(adj, key=lambda p: abs(bx - p[0]) + abs(by - p[1]))
            return next_action_towards(bot_id, pos, closest_adj, walls_set, grid_w, grid_h)

    # No targets found but carrying useful items → deliver now
    if useful_for_active:
        if pos == drop_off:
            return {"bot": bot_id, "action": "drop_off"}
        return next_action_towards(bot_id, pos, drop_off, walls_set, grid_w, grid_h)

    return {"bot": bot_id, "action": "wait"}


# ---------------------------------------------------------------------------
# WebSocket loop
# ---------------------------------------------------------------------------

async def play(ws_url):
    print(f"Connecting to {ws_url}")
    # Accumulate shelf positions across rounds — shelves stay impassable even
    # after items are picked up.
    shelf_positions: set[tuple[int, int]] = set()

    async with websockets.connect(ws_url) as ws:
        async for message in ws:
            data = json.loads(message)

            if data["type"] == "game_over":
                print(
                    f"Game over! Score: {data['score']} | "
                    f"Rounds: {data['rounds_used']} | "
                    f"Items delivered: {data['items_delivered']} | "
                    f"Orders completed: {data['orders_completed']}"
                )
                break

            if data["type"] == "game_state":
                for item in data["items"]:
                    shelf_positions.add(tuple(item["position"]))

                if data["round"] == 0:
                    print(f"Game started — grid {data['grid']['width']}x{data['grid']['height']}, "
                          f"{len(data['bots'])} bot(s), {len(shelf_positions)} shelf tiles discovered")

                actions = decide_actions(data, shelf_positions)
                await ws.send(json.dumps({"actions": actions}))


if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else WS_URL
    asyncio.run(play(url))
