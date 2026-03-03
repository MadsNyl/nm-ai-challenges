"""
Order fulfillment strategy — item targeting, task assignment, delivery logic.

Single-bot flow (Easy):
  1. Look at active order, figure out what items are still needed
  2. Find nearest needed item, BFS to adjacent tile, pick_up
  3. When inventory has useful items and nothing nearby to grab, go deliver
  4. At drop-off, drop_off
  5. Repeat

Multi-bot flow (Medium/Hard/Expert):
  - Same core logic but with item assignment to avoid duplicate targeting
  - Bots treated as temporary obstacles for each other
"""

from pathfinding import (
    build_walkable_set,
    bfs,
    bfs_to_any,
    adjacent_walkable,
    path_to_action,
)


def decide(state: dict) -> list[dict]:
    """Main entry point: given game state, return list of bot actions."""
    walkable = build_walkable_set(state["grid"], state["items"])
    drop_off = tuple(state["drop_off"])

    bots = state["bots"]
    items = state["items"]
    orders = state["orders"]

    active = next((o for o in orders if o["status"] == "active"), None)
    preview = next((o for o in orders if o["status"] == "preview"), None)

    # What does the active order still need?
    needed = _remaining_items(active) if active else {}

    # Track which items are already claimed by a bot (avoid duplicates)
    claimed_item_ids = set()
    # Track bot positions for collision avoidance
    bot_positions = {tuple(b["position"]) for b in bots}

    actions = []

    for bot in bots:
        pos = tuple(bot["position"])
        inventory = bot["inventory"]

        # Other bots' current positions (for collision-aware pathfinding)
        other_bots = bot_positions - {pos}

        action = _decide_bot(
            bot, pos, inventory, items, needed, preview,
            drop_off, walkable, other_bots, claimed_item_ids,
        )
        actions.append(action)

    return actions


def _remaining_items(order: dict) -> dict[str, int]:
    """Count how many of each item type the order still needs."""
    needed = {}
    for item_type in order["items_required"]:
        needed[item_type] = needed.get(item_type, 0) + 1
    for item_type in order["items_delivered"]:
        if item_type in needed and needed[item_type] > 0:
            needed[item_type] -= 1
    return {k: v for k, v in needed.items() if v > 0}


def _decide_bot(
    bot, pos, inventory, items, needed, preview,
    drop_off, walkable, other_bots, claimed_item_ids,
) -> dict:
    """Decide a single bot's action."""
    bot_id = bot["id"]

    # --- Priority 1: If on drop-off with useful items, deliver ---
    has_useful = _count_useful(inventory, needed)
    if pos == drop_off and has_useful > 0:
        return {"bot": bot_id, "action": "drop_off"}

    # --- Priority 2: If inventory full, go deliver ---
    if len(inventory) >= 3 and has_useful > 0:
        return _navigate(bot_id, pos, drop_off, walkable, other_bots)

    # --- Priority 3: Pick up a needed item if adjacent ---
    # Subtract what we're already carrying from what's needed
    still_needed = dict(needed)
    for item_type in inventory:
        if item_type in still_needed and still_needed[item_type] > 0:
            still_needed[item_type] -= 1
    # Also subtract items claimed by other bots
    for item in items:
        if item["id"] in claimed_item_ids and item["type"] in still_needed:
            still_needed[item["type"]] = max(0, still_needed.get(item["type"], 0) - 1)
    still_needed = {k: v for k, v in still_needed.items() if v > 0}

    # Check if we're adjacent to a needed item
    for item in items:
        if item["id"] in claimed_item_ids:
            continue
        if item["type"] not in still_needed or still_needed[item["type"]] <= 0:
            continue
        item_pos = tuple(item["position"])
        if _manhattan(pos, item_pos) == 1 and len(inventory) < 3:
            claimed_item_ids.add(item["id"])
            return {"bot": bot_id, "action": "pick_up", "item_id": item["id"]}

    # --- Priority 4: Navigate to nearest needed item ---
    if still_needed and len(inventory) < 3:
        target = _find_nearest_item(
            pos, items, still_needed, claimed_item_ids, walkable, other_bots
        )
        if target:
            item, pickup_pos = target
            claimed_item_ids.add(item["id"])
            if pos == pickup_pos:
                # Already at pickup position, grab it
                return {"bot": bot_id, "action": "pick_up", "item_id": item["id"]}
            return _navigate(bot_id, pos, pickup_pos, walkable, other_bots)

    # --- Priority 5: Deliver what we have ---
    if has_useful > 0:
        return _navigate(bot_id, pos, drop_off, walkable, other_bots)

    # --- Priority 6: Pre-pick preview order items ---
    if preview and len(inventory) < 3:
        preview_needed = _remaining_items(preview)
        # Don't pre-pick what we already carry
        for item_type in inventory:
            if item_type in preview_needed and preview_needed[item_type] > 0:
                preview_needed[item_type] -= 1
        preview_needed = {k: v for k, v in preview_needed.items() if v > 0}

        if preview_needed:
            target = _find_nearest_item(
                pos, items, preview_needed, claimed_item_ids, walkable, other_bots
            )
            if target:
                item, pickup_pos = target
                claimed_item_ids.add(item["id"])
                if pos == pickup_pos:
                    return {"bot": bot_id, "action": "pick_up", "item_id": item["id"]}
                return _navigate(bot_id, pos, pickup_pos, walkable, other_bots)

    # --- Nothing to do ---
    return {"bot": bot_id, "action": "wait"}


def _find_nearest_item(pos, items, needed_types, claimed_ids, walkable, blocked):
    """
    Find the nearest needed item and the walkable tile to stand on for pickup.

    Returns (item, pickup_pos) or None.
    """
    best = None
    best_dist = float("inf")

    for item in items:
        if item["id"] in claimed_ids:
            continue
        if item["type"] not in needed_types or needed_types[item["type"]] <= 0:
            continue

        item_pos = tuple(item["position"])
        # Find walkable tiles adjacent to this item's shelf
        pickup_tiles = adjacent_walkable(item_pos, walkable)
        if not pickup_tiles:
            continue

        # BFS to the nearest pickup tile
        pickup_set = set(pickup_tiles)
        result = bfs_to_any(pos, pickup_set, walkable, blocked)
        if result:
            reached, path = result
            dist = len(path) - 1  # steps, not positions
            if dist < best_dist:
                best_dist = dist
                best = (item, reached)

    return best


def _navigate(bot_id, pos, goal, walkable, blocked):
    """Navigate one step toward goal using BFS."""
    path = bfs(pos, goal, walkable, blocked)
    if path and len(path) >= 2:
        action = path_to_action(pos, path[1])
        return {"bot": bot_id, "action": action}
    # If blocked path (e.g. another bot in the way), try without blocked set
    if blocked:
        path = bfs(pos, goal, walkable)
        if path and len(path) >= 2:
            action = path_to_action(pos, path[1])
            return {"bot": bot_id, "action": action}
    return {"bot": bot_id, "action": "wait"}


def _count_useful(inventory: list[str], needed: dict[str, int]) -> int:
    """Count how many inventory items match the active order's needs."""
    remaining = dict(needed)
    count = 0
    for item_type in inventory:
        if item_type in remaining and remaining[item_type] > 0:
            remaining[item_type] -= 1
            count += 1
    return count


def _manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])
