import asyncio
import json
from collections import deque

import websockets

WS_URL = "wss://game.ainm.no/ws?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0ZWFtX2lkIjoiNTllYWY5MjgtMzNlNS00YTVjLTk1NzItNmUzZDk3MGM4NzQ2IiwibWFwX2lkIjoiYzg5ZGEyZWMtM2NhNy00MGM5LWEzYjEtODAzNmZjYTNkMGI3IiwibWFwX3NlZWQiOjcwMDEsImRpZmZpY3VsdHkiOiJlYXN5IiwiZXhwIjoxNzcyNTY4NTUzfQ.t0RwVI5moFQuxBFLp2uoZKWybY803CbvAPLUjuqL9hM"


# ---------------------------------------------------------------------------
# Pathfinding
# ---------------------------------------------------------------------------

def bfs(start, goal, walls_set, grid_width, grid_height):
    """Return list of (x, y) positions from start to goal (exclusive of start).
    Returns empty list if already at goal or no path found."""
    if start == goal:
        return []

    queue = deque()
    queue.append((start, []))
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

    return []  # no path


def next_action_towards(bot_id, start, goal, walls_set, grid_width, grid_height):
    """Return the action dict to take one BFS step towards goal."""
    path = bfs(start, goal, walls_set, grid_width, grid_height)
    if not path:
        return {"bot": bot_id, "action": "wait"}
    _, _, action = path[0]
    return {"bot": bot_id, "action": action}


# ---------------------------------------------------------------------------
# Adjacent cells (for pickup)
# ---------------------------------------------------------------------------

def adjacent_cells(x, y):
    return [(x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)]


# ---------------------------------------------------------------------------
# Decision logic (single bot — Easy map)
# ---------------------------------------------------------------------------

def decide_actions(state, shelf_positions):
    walls_set = set(map(tuple, state["grid"]["walls"])) | shelf_positions
    grid_w = state["grid"]["width"]
    grid_h = state["grid"]["height"]
    drop_off = tuple(state["drop_off"])
    bots = state["bots"]
    items = state["items"]
    orders = state["orders"]

    # Items indexed by id and by position
    items_by_id = {item["id"]: item for item in items}
    items_by_pos = {tuple(item["position"]): item for item in items}

    # Active and preview orders
    active_order = next((o for o in orders if o.get("status") == "active"), None)
    preview_order = next((o for o in orders if o.get("status") == "preview"), None)

    actions = []
    for bot in bots:
        action = decide_bot(
            bot, active_order, preview_order,
            items, items_by_id, items_by_pos,
            drop_off, walls_set, grid_w, grid_h
        )
        actions.append(action)

    return actions


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


def decide_bot(bot, active_order, preview_order,
               items, items_by_id, items_by_pos,
               drop_off, walls_set, grid_w, grid_h):
    bot_id = bot["id"]
    bx, by = bot["position"]
    pos = (bx, by)
    inventory = bot["inventory"]

    active_needed = needed_items(active_order)
    preview_needed = needed_items(preview_order)

    # Items we're carrying that the active order needs
    useful_for_active = [i for i in inventory if active_needed.get(i, 0) > 0]

    # -----------------------------------------------------------------------
    # 1. If at drop-off and carrying useful items → deliver
    # -----------------------------------------------------------------------
    if pos == drop_off and useful_for_active:
        return {"bot": bot_id, "action": "drop_off"}

    # -----------------------------------------------------------------------
    # 2. If carrying useful items → go deliver
    # -----------------------------------------------------------------------
    if useful_for_active:
        return next_action_towards(bot_id, pos, drop_off, walls_set, grid_w, grid_h)

    # -----------------------------------------------------------------------
    # 3. Inventory full → go deliver (even if nothing matches yet — clear space)
    # -----------------------------------------------------------------------
    if len(inventory) >= 3:
        if pos == drop_off:
            return {"bot": bot_id, "action": "drop_off"}
        return next_action_towards(bot_id, pos, drop_off, walls_set, grid_w, grid_h)

    # -----------------------------------------------------------------------
    # 4. Pick up items for active order (priority), then preview order
    # -----------------------------------------------------------------------
    # Build combined target list: active first, then preview to fill remaining slots
    slots_left = 3 - len(inventory)
    targets = _find_target_items(
        inventory, active_needed, preview_needed, items, slots_left
    )

    if targets:
        best = min(targets, key=lambda item: abs(bx - item["position"][0]) + abs(by - item["position"][1]))
        ix, iy = best["position"]
        item_pos = (ix, iy)

        # Adjacent to shelf → pick up
        if item_pos in [tuple(a) for a in [
            (bx, by - 1), (bx, by + 1), (bx - 1, by), (bx + 1, by)
        ]]:
            return {"bot": bot_id, "action": "pick_up", "item_id": best["id"]}

        # Walk towards item (stand adjacent to it)
        adj = _walkable_adjacent(ix, iy, walls_set, grid_w, grid_h)
        if adj:
            closest_adj = min(adj, key=lambda p: abs(bx - p[0]) + abs(by - p[1]))
            return next_action_towards(bot_id, pos, closest_adj, walls_set, grid_w, grid_h)

    # -----------------------------------------------------------------------
    # 5. Nothing to do
    # -----------------------------------------------------------------------
    return {"bot": bot_id, "action": "wait"}


def _find_target_items(inventory, active_needed, preview_needed, items, slots_left):
    """Find items worth picking up: active order first, then preview."""
    # Track what we're already carrying
    carrying = {}
    for i in inventory:
        carrying[i] = carrying.get(i, 0) + 1

    still_needed_active = {}
    for k, v in active_needed.items():
        still_needed_active[k] = v - carrying.get(k, 0)
    still_needed_active = {k: v for k, v in still_needed_active.items() if v > 0}

    still_needed_preview = {}
    for k, v in preview_needed.items():
        still_needed_preview[k] = v - carrying.get(k, 0)
    still_needed_preview = {k: v for k, v in still_needed_preview.items() if v > 0}

    targets = []
    for item in items:
        if item["type"] in still_needed_active:
            targets.append(item)
        elif item["type"] in still_needed_preview and slots_left > len([
            t for t in targets if t["type"] in still_needed_active
        ]):
            targets.append(item)

    return targets


def _walkable_adjacent(x, y, walls_set, grid_w, grid_h):
    """Return walkable cells adjacent to (x, y)."""
    result = []
    for nx, ny in [(x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)]:
        if 0 <= nx < grid_w and 0 <= ny < grid_h and (nx, ny) not in walls_set:
            result.append((nx, ny))
    return result


# ---------------------------------------------------------------------------
# WebSocket loop
# ---------------------------------------------------------------------------

async def play(ws_url):
    print(f"Connecting to {ws_url}")
    # Accumulated set of shelf positions — built from all item positions ever seen.
    # Items disappear when picked up, but shelves remain impassable, so we keep
    # the union across all rounds.
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
                # Accumulate shelf positions from every item we've ever seen
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
