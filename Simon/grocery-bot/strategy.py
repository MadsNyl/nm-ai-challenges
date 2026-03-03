"""
Order fulfillment strategy — item targeting, task assignment, delivery logic.

Decision priorities (per bot, per round):
  0. Endgame scavenge — rapid single-item deliveries when order can't complete
  1. Drop-off — deliver if on drop-off with useful items
  S. Stuck recovery — if inventory full + nothing useful, go to drop-off
  2. Full inventory — navigate to drop-off
  3. Adjacent active item — pick up (ONLY active order items, never preview)
  4. TSP route — optimal multi-stop pickup for active items
     Chain items (preview) only added on LAST trip when active fits with room to spare
  5. Deliver — go to drop-off with partial inventory
  6. Preview pre-pick — only when active order fully handled (forward-looking tile selection)

Key lessons learned:
  - NEVER pick preview/chain items before all active items are secured
  - Adjacent pickup must ONLY target active order items (priority 3)
  - Detours disabled — were filling inventory with useless preview items
  - Stuck recovery prevents permanent deadlock from stale inventory

Multi-bot flow (Medium/Hard/Expert):
  - Same core logic but with item assignment to avoid duplicate targeting
  - Bots treated as temporary obstacles for each other
"""

from itertools import permutations

from pathfinding import (
    build_walkable_set,
    bfs,
    bfs_to_any,
    bfs_distance_map,
    adjacent_walkable,
    path_to_action,
)

MAX_INVENTORY = 3
ENDGAME_THRESHOLD = 45  # rounds remaining to trigger scavenge mode


def decide(state: dict) -> list[dict]:
    """Main entry point: given game state, return list of bot actions."""
    walkable = build_walkable_set(state["grid"], state["items"])
    drop_off = tuple(state["drop_off"])

    bots = state["bots"]
    items = state["items"]
    orders = state["orders"]
    current_round = state["round"]
    max_rounds = state.get("max_rounds", 300)

    active = next((o for o in orders if o["status"] == "active"), None)
    preview = next((o for o in orders if o["status"] == "preview"), None)

    needed = _remaining_items(active) if active else {}

    claimed_item_ids = set()
    bot_positions = {tuple(b["position"]) for b in bots}

    actions = []

    for bot in bots:
        pos = tuple(bot["position"])
        inventory = bot["inventory"]
        other_bots = bot_positions - {pos}

        action = _decide_bot(
            bot, pos, inventory, items, needed, preview,
            drop_off, walkable, other_bots, claimed_item_ids,
            current_round, max_rounds,
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
    current_round, max_rounds,
) -> dict:
    """Decide a single bot's action."""
    bot_id = bot["id"]
    rounds_left = max_rounds - current_round

    # Compute what we still need (subtract carried + claimed)
    still_needed = _subtract_carried_and_claimed(needed, inventory, items, claimed_item_ids)
    has_useful = _count_useful(inventory, needed)

    # Preview order needs
    preview_needed = _remaining_items(preview) if preview else {}
    if preview_needed:
        for item_type in inventory:
            if item_type in preview_needed and preview_needed[item_type] > 0:
                preview_needed[item_type] -= 1
        preview_needed = {k: v for k, v in preview_needed.items() if v > 0}

    # --- Priority 0: Endgame scavenge mode ---
    if rounds_left < ENDGAME_THRESHOLD and still_needed:
        est = _estimate_rounds_to_complete(
            pos, inventory, items, still_needed, drop_off, walkable, other_bots,
        )
        if est is not None and est > rounds_left:
            return _scavenge_mode_action(
                bot_id, pos, inventory, items, needed,
                drop_off, walkable, other_bots, claimed_item_ids,
            )

    # --- Priority 1: On drop-off with useful items → deliver ---
    if pos == drop_off and has_useful > 0:
        return {"bot": bot_id, "action": "drop_off"}

    # --- Stuck recovery: inventory full, nothing useful, but order needs items ---
    # This prevents permanent deadlock from stale inventory items
    if len(inventory) >= MAX_INVENTORY and has_useful == 0 and still_needed:
        # Go to drop-off and try anyway — drop_off delivers whatever matches
        if pos == drop_off:
            return {"bot": bot_id, "action": "drop_off"}
        return _navigate(bot_id, pos, drop_off, walkable, other_bots)

    # --- Priority 2: Inventory full with useful items → deliver ---
    if len(inventory) >= MAX_INVENTORY and has_useful > 0:
        return _navigate(bot_id, pos, drop_off, walkable, other_bots)

    # --- Priority 3: Adjacent to needed ACTIVE item → pick up ---
    # ONLY active order items here — never chain/preview items
    if still_needed and len(inventory) < MAX_INVENTORY:
        for item in items:
            if item["id"] in claimed_item_ids:
                continue
            if item["type"] not in still_needed or still_needed[item["type"]] <= 0:
                continue
            item_pos = tuple(item["position"])
            if _manhattan(pos, item_pos) == 1:
                claimed_item_ids.add(item["id"])
                return {"bot": bot_id, "action": "pick_up", "item_id": item["id"]}

    # --- Priority 4: Plan optimal pickup route for ACTIVE items (TSP) ---
    # Chain items only added when this is the LAST pickup trip
    # (all remaining active items fit in available slots)
    pickup_types = dict(still_needed)
    active_picks = sum(still_needed.values())
    slots_free = MAX_INVENTORY - len(inventory)

    # Only add chain items when all active items fit with room to spare
    if active_picks > 0 and active_picks < slots_free and preview_needed:
        spare = slots_free - active_picks
        for item_type, count in preview_needed.items():
            if spare <= 0:
                break
            take = min(count, spare)
            pickup_types[item_type] = pickup_types.get(item_type, 0) + take
            spare -= take

    if pickup_types and len(inventory) < MAX_INVENTORY:
        route_action = _plan_pickup_route(
            bot_id, pos, items, pickup_types, drop_off,
            walkable, other_bots, claimed_item_ids,
            preview_needed, inventory,
        )
        if route_action:
            return route_action

    # --- Priority 4.5: Fill spare slots with preview items BEFORE delivering ---
    # When all active items are collected but inventory has room, grab preview
    # items on the way to drop-off. These stay in inventory after drop_off
    # (only active-order items are delivered) and become useful when the
    # preview order activates — saving a full trip later.
    if has_useful > 0 and not still_needed and len(inventory) < MAX_INVENTORY and preview_needed:
        # Check for adjacent preview item first
        for item in items:
            if item["id"] in claimed_item_ids:
                continue
            if item["type"] not in preview_needed or preview_needed[item["type"]] <= 0:
                continue
            item_pos = tuple(item["position"])
            if _manhattan(pos, item_pos) == 1:
                claimed_item_ids.add(item["id"])
                return {"bot": bot_id, "action": "pick_up", "item_id": item["id"]}

        # Find nearest preview item within a detour budget
        # Budget: only detour if the extra cost is worth it vs a separate trip later
        dist_map = bfs_distance_map(pos, walkable, other_bots)
        dist_to_dropoff = dist_map.get(drop_off, 99)
        max_detour = 8  # rounds of detour we'll accept to fill a slot

        target = _find_item_with_lookahead(
            pos, items, preview_needed, claimed_item_ids, walkable, other_bots, drop_off,
        )
        if target:
            item, pickup_pos = target
            d_to_item = dist_map.get(pickup_pos, 99)
            d_item_to_drop = _manhattan(pickup_pos, drop_off)
            detour_cost = d_to_item + 1 + d_item_to_drop - dist_to_dropoff  # +1 for pickup action
            if detour_cost <= max_detour:
                claimed_item_ids.add(item["id"])
                if pos == pickup_pos:
                    return {"bot": bot_id, "action": "pick_up", "item_id": item["id"]}
                return _navigate(bot_id, pos, pickup_pos, walkable, other_bots)

    # --- Priority 5: Deliver what we have ---
    if has_useful > 0:
        return _navigate(bot_id, pos, drop_off, walkable, other_bots)

    # --- Priority 6: Pre-pick preview order items (forward-looking) ---
    # Only when active order is fully handled (nothing more to pick or carry)
    if preview_needed and len(inventory) < MAX_INVENTORY and not still_needed:
        # Adjacent check first
        for item in items:
            if item["id"] in claimed_item_ids:
                continue
            if item["type"] not in preview_needed or preview_needed[item["type"]] <= 0:
                continue
            item_pos = tuple(item["position"])
            if _manhattan(pos, item_pos) == 1:
                claimed_item_ids.add(item["id"])
                return {"bot": bot_id, "action": "pick_up", "item_id": item["id"]}

        # Navigate to nearest preview item with forward-looking tile selection
        target = _find_item_with_lookahead(
            pos, items, preview_needed, claimed_item_ids, walkable, other_bots, drop_off,
        )
        if target:
            item, pickup_pos = target
            claimed_item_ids.add(item["id"])
            if pos == pickup_pos:
                return {"bot": bot_id, "action": "pick_up", "item_id": item["id"]}
            return _navigate(bot_id, pos, pickup_pos, walkable, other_bots)

    # --- Nothing to do ---
    return {"bot": bot_id, "action": "wait"}


# ---------------------------------------------------------------------------
# TSP Route Planning
# ---------------------------------------------------------------------------

def _plan_pickup_route(
    bot_id, pos, items, pickup_types, drop_off,
    walkable, other_bots, claimed_item_ids,
    preview_needed, inventory,
):
    """
    Plan the optimal multi-stop pickup route using permutation search.

    For each combination of items matching the needed types, try all visit
    orderings and pick the one with minimum total distance (pos → stops → drop_off).
    """
    slots_available = MAX_INVENTORY - len(inventory)

    # Collect candidate (item, pickup_tiles) for each needed type, sorted by distance
    candidates_by_type = {}
    dist_from_pos = bfs_distance_map(pos, walkable, other_bots)
    for item in items:
        if item["id"] in claimed_item_ids:
            continue
        itype = item["type"]
        if itype not in pickup_types or pickup_types[itype] <= 0:
            continue
        item_pos = tuple(item["position"])
        tiles = adjacent_walkable(item_pos, walkable)
        if not tiles:
            continue
        candidates_by_type.setdefault(itype, []).append((item, tiles))

    # Sort candidates by nearest pickup tile distance so truncation keeps closest
    for itype in candidates_by_type:
        candidates_by_type[itype].sort(
            key=lambda c: min((dist_from_pos.get(t, 999) for t in c[1]), default=999)
        )

    if not candidates_by_type:
        return None

    # Build (type, count) list capped by available slots
    type_counts = []
    remaining_slots = slots_available
    for t, c in pickup_types.items():
        if t in candidates_by_type and remaining_slots > 0:
            take = min(c, remaining_slots)
            type_counts.append((t, take))
            remaining_slots -= take

    if not type_counts:
        return None

    # Generate all possible item selections
    selections = _enumerate_selections(type_counts, candidates_by_type)
    if not selections:
        return None

    # dist_from_pos already computed above for candidate sorting
    best_route = None
    best_cost = float("inf")

    for selection in selections:
        # selection is list of (item, pickup_tile)
        if len(selection) <= 6:  # 6! = 720, still fast
            for perm in permutations(selection):
                cost = _evaluate_route_cost(perm, dist_from_pos, drop_off)
                if cost < best_cost:
                    best_cost = cost
                    best_route = list(perm)

    if best_route is None:
        return None

    # Execute first stop
    first_item, first_tile = best_route[0]
    claimed_item_ids.add(first_item["id"])

    if pos == first_tile:
        return {"bot": bot_id, "action": "pick_up", "item_id": first_item["id"]}

    return _navigate(bot_id, pos, first_tile, walkable, other_bots)


def _enumerate_selections(type_counts, candidates_by_type):
    """
    Generate all valid item selections matching required type/counts.
    Returns list of selections, where each selection is [(item, pickup_tile), ...].
    """
    MAX_CANDIDATES_PER_TYPE = 3
    MAX_SELECTIONS = 50

    result = [[]]
    for item_type, count in type_counts:
        cands = candidates_by_type.get(item_type, [])
        if not cands:
            return []
        # Expand each candidate into (item, tile) pairs
        expanded = []
        for item, tiles in cands[:MAX_CANDIDATES_PER_TYPE]:
            for tile in tiles:
                expanded.append((item, tile))

        new_result = []
        for sel in result:
            for combo in _combinations(expanded, count):
                new_result.append(sel + list(combo))
                if len(new_result) >= MAX_SELECTIONS:
                    return new_result
        result = new_result

    return result


def _combinations(items, k):
    """Simple k-combinations from a list."""
    if k == 0:
        yield ()
        return
    for i in range(len(items)):
        for rest in _combinations(items[i + 1:], k - 1):
            yield (items[i],) + rest


def _evaluate_route_cost(perm, dist_from_start, drop_off):
    """
    Evaluate total cost for route: start → tile₁ → tile₂ → ... → drop_off.
    Uses BFS dist map for first leg, Manhattan for subsequent legs.
    """
    total = 0
    stops = list(perm)

    # First leg: start → first tile (exact BFS distance)
    first_tile = stops[0][1]
    d = dist_from_start.get(first_tile)
    if d is None:
        return float("inf")
    total += d

    # Intermediate legs + pickup actions
    prev_tile = first_tile
    for i in range(1, len(stops)):
        next_tile = stops[i][1]
        total += _manhattan(prev_tile, next_tile)
        prev_tile = next_tile

    # Pickup actions (1 round each)
    total += len(stops)

    # Last leg: last tile → drop_off
    total += _manhattan(prev_tile, drop_off)

    return total


# ---------------------------------------------------------------------------
# Path Detour — grab preview items on the current path (conservative)
# ---------------------------------------------------------------------------
# Detours are DISABLED for now. The aggressive detour logic was picking up
# preview items that filled inventory slots needed for active order items,
# causing deadlocks. Detours should only be re-enabled with strict guards:
# - Only detour when ALL active items are already in inventory
# - Only detour for 0-cost on-path items (not 1-step off-path)


# ---------------------------------------------------------------------------
# Forward-Looking Pickup Tile Selection
# ---------------------------------------------------------------------------

def _find_item_with_lookahead(
    pos, items, needed_types, claimed_ids, walkable, blocked, next_dest,
):
    """
    Find the nearest needed item, choosing the pickup tile that minimizes
    distance(pos → tile) + distance(tile → next_dest).
    """
    best = None
    best_cost = float("inf")

    dist_from_pos = bfs_distance_map(pos, walkable, blocked)

    for item in items:
        if item["id"] in claimed_ids:
            continue
        if item["type"] not in needed_types or needed_types[item["type"]] <= 0:
            continue

        item_pos = tuple(item["position"])
        pickup_tiles = adjacent_walkable(item_pos, walkable)
        if not pickup_tiles:
            continue

        for tile in pickup_tiles:
            d_to_tile = dist_from_pos.get(tile)
            if d_to_tile is None:
                continue
            d_to_next = _manhattan(tile, next_dest) if next_dest else 0
            cost = d_to_tile + d_to_next
            if cost < best_cost:
                best_cost = cost
                best = (item, tile)

    return best


# ---------------------------------------------------------------------------
# Endgame / Scavenge Mode
# ---------------------------------------------------------------------------

def _estimate_rounds_to_complete(pos, inventory, items, still_needed, drop_off, walkable, blocked):
    """Estimate rounds needed to complete the active order from current state."""
    if not still_needed:
        return 0

    total_items = sum(still_needed.values())
    if total_items == 0:
        return 0

    dist_from_pos = bfs_distance_map(pos, walkable, blocked)

    # Find nearest pickup distance for each needed type
    type_dists = {}
    for item_type in still_needed:
        min_d = float("inf")
        for item in items:
            if item["type"] != item_type:
                continue
            item_pos = tuple(item["position"])
            tiles = adjacent_walkable(item_pos, walkable)
            for tile in tiles:
                d = dist_from_pos.get(tile)
                if d is not None and d < min_d:
                    min_d = d
        if min_d < float("inf"):
            type_dists[item_type] = min_d

    if not type_dists:
        return None

    # Estimate: sum of pickup distances + delivery trips + pickup actions
    total_pickup_dist = sum(
        type_dists.get(t, 10) * c for t, c in still_needed.items()
    )
    trips = (total_items + MAX_INVENTORY - 1) // MAX_INVENTORY
    avg_dropoff_dist = _manhattan(pos, drop_off)

    return int(total_pickup_dist + avg_dropoff_dist * trips + total_items)


def _scavenge_mode_action(
    bot_id, pos, inventory, items, needed,
    drop_off, walkable, other_bots, claimed_item_ids,
):
    """
    Endgame scavenge: grab the nearest single item and deliver immediately.
    Maximizes +1 per item instead of chasing +5 order bonus.
    """
    has_useful = _count_useful(inventory, needed)

    # Deliver what we have
    if has_useful > 0:
        if pos == drop_off:
            return {"bot": bot_id, "action": "drop_off"}
        return _navigate(bot_id, pos, drop_off, walkable, other_bots)

    # Adjacent to a needed item? Pick it up
    if len(inventory) < MAX_INVENTORY:
        for item in items:
            if item["id"] in claimed_item_ids:
                continue
            if item["type"] not in needed or needed[item["type"]] <= 0:
                continue
            item_pos = tuple(item["position"])
            if _manhattan(pos, item_pos) == 1:
                claimed_item_ids.add(item["id"])
                return {"bot": bot_id, "action": "pick_up", "item_id": item["id"]}

    # Grab nearest needed item
    if len(inventory) < MAX_INVENTORY and needed:
        target = _find_nearest_item(pos, items, needed, claimed_item_ids, walkable, other_bots)
        if target:
            item, pickup_pos = target
            claimed_item_ids.add(item["id"])
            if pos == pickup_pos:
                return {"bot": bot_id, "action": "pick_up", "item_id": item["id"]}
            return _navigate(bot_id, pos, pickup_pos, walkable, other_bots)

    return {"bot": bot_id, "action": "wait"}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _subtract_carried_and_claimed(needed, inventory, items, claimed_item_ids):
    """Subtract carried inventory and claimed items from needed counts."""
    still_needed = dict(needed)
    for item_type in inventory:
        if item_type in still_needed and still_needed[item_type] > 0:
            still_needed[item_type] -= 1
    for item in items:
        if item["id"] in claimed_item_ids and item["type"] in still_needed:
            still_needed[item["type"]] = max(0, still_needed.get(item["type"], 0) - 1)
    return {k: v for k, v in still_needed.items() if v > 0}


def _find_nearest_item(pos, items, needed_types, claimed_ids, walkable, blocked):
    """Find the nearest needed item and walkable pickup tile. Returns (item, pos) or None."""
    best = None
    best_dist = float("inf")

    for item in items:
        if item["id"] in claimed_ids:
            continue
        if item["type"] not in needed_types or needed_types[item["type"]] <= 0:
            continue

        item_pos = tuple(item["position"])
        pickup_tiles = adjacent_walkable(item_pos, walkable)
        if not pickup_tiles:
            continue

        pickup_set = set(pickup_tiles)
        result = bfs_to_any(pos, pickup_set, walkable, blocked)
        if result:
            reached, path = result
            dist = len(path) - 1
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
