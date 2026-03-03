# Grocery Bot — Strategy & Tricks Reference

## Game Mechanics

### Scoring
- **+1** per item delivered to active order
- **+5** bonus per completed order
- 4-item order completed = 4 + 5 = **9 points**
- 3-item order completed = 3 + 5 = **8 points**
- Key metric: **rounds per completed order** (lower = more orders = higher score)

### Items Are Infinite
- Shelves never deplete. The `items` list stays constant throughout 300 rounds.
- Same `item_id` can be picked up repeatedly from the same shelf tile.
- No scarcity — optimize purely for shortest round-trip loops.

### Drop-Off Chain Reaction
- When the active order completes via `drop_off`, the preview order becomes active **immediately**.
- Any items already in inventory matching the NEW active order are **auto-delivered** on the same `drop_off` action.
- This can cascade: if auto-delivered items complete the new order, the next preview also activates.
- **Exploit**: On the final pickup trip for an active order, fill spare inventory slots with preview-order items. They deliver for free on the same drop-off.

### Pickup Directions
- Pickup works from all 4 cardinal directions (Manhattan distance 1).
- Some shelves sandwiched between other shelves have only 1 accessible side.
- Choose the pickup tile that minimizes the TOTAL trip, not just the approach distance.

### Action Resolution
- Bot 0 moves first, then bot 1, etc. Lower IDs have collision priority.
- Invalid actions silently become `wait` — no penalty, but wastes a round.
- Bots block each other on all tiles except the spawn tile.

### Deterministic Per Day
- Same day = same map layout, item placement, and order sequence.
- Can replay to learn optimal routes for the day's configuration.

### Limits
- 300 rounds max, 120s wall-clock, 2s response timeout per round
- Max 3 items per bot inventory
- 60s cooldown between games

---

## Optimization Techniques (v2)

### 1. TSP Route Planning
**Problem**: Greedy nearest-item picks suboptimal sequences (e.g., picks a nearby item then backtracks past a closer second item).

**Solution**: For each set of items to pick up, enumerate all (item, pickup_tile) combinations and evaluate every permutation. Pick the route with minimum total distance: `pos → tile₁ → tile₂ → ... → drop_off`.

- Uses `bfs_distance_map()` for exact distance from current position
- Manhattan distance for intermediate legs (fast approximation)
- Caps at 6 items (6! = 720 permutations) — always fast enough
- Re-plans every round (stateless) — naturally adapts as items get picked up

### 2. Drop-Off Chain Exploitation
**Problem**: Spare inventory slots wasted on final delivery trip.

**Solution**: When heading to drop-off with the last active-order items, fill spare slots with preview-order items.

- Calculate: `spare = max_inventory - carried - active_items_still_to_pick`
- If spare > 0 and preview exists, merge preview types into the pickup target set
- These chain-deliver automatically when active order completes

### 3. Opportunistic Path Detours
**Problem**: Bot walks past useful preview items without picking them up.

**Solution**: When navigating to any target, check if preview-order items have pickup tiles on or near the BFS path.

- **0-step detour** (pickup tile on path): Only costs 1 extra round (the pick_up action). Always worth it.
- **1-step detour** (1 tile off path): Costs ~3 rounds. Worth it on longer paths (>6 steps).
- Applied when navigating to items AND to drop-off.

### 4. Forward-Looking Tile Selection
**Problem**: Choosing the nearest pickup tile may point away from the next destination, adding backtracking.

**Solution**: Score each pickup tile as `distance(pos → tile) + distance(tile → next_dest)` and pick the minimum.

- `next_dest` = drop-off when delivering, or next item in route
- Biggest impact on preview pre-picks (priority 7) where the next stop is often drop-off

### 5. Endgame Scavenge Mode
**Problem**: With <45 rounds left, starting a 4-item order that can't be completed wastes the order bonus AND the remaining rounds.

**Solution**: When `rounds_remaining < 45` and estimated completion exceeds remaining rounds, switch to rapid single-item deliveries.

- Grab nearest item matching active order → deliver immediately
- Scores +1 per item instead of gambling on +5 bonus
- Trigger threshold: 45 rounds (enough for ~4-5 single-item runs)

---

## Easy Map Layout (12×10)

```
  0 1 2 3 4 5 6 7 8 9 10 11
0 W W W W W W W W W W W  W
1 W . W . . . W . . . W  W     ← top corridor
2 W . W S . S W . . S W  W     S = shelf (item)
3 W . W S . S W . . S W  W
4 W . W S . S W . . S W  W
5 W . . . . . . . . . .  W     ← middle corridor
6 W . W S . S W . . . W  W
7 W . . . . . . . . . .  W     ← bottom corridor
8 W D . . . . . . . . Sp W     D=drop-off, Sp=spawn
9 W W W W W W W W W W W  W
```

- **Drop-off**: (1, 8) — bottom-left
- **Spawn**: (10, 8) — bottom-right
- **Shelf columns**: x=3,5 (top & bottom blocks), x=9 (top block)
- **Wall columns**: x=2,6,10
- **Walkway aisles**: x=1,4,8
- **Horizontal corridors**: y=1, y=5, y=7

### Round-Trip Analysis (Easy)
- Average item pickup from spawn area: ~12-15 steps
- Drop-off round trip (center map → drop-off → center): ~16-20 steps
- Optimal 3-item order: ~25 rounds (3 pickups + 1 delivery trip)
- With TSP routing: saves 3-5 rounds per order vs greedy

---

## Known Pitfalls

### Desync
- If WebSocket response arrives >2s late, server treats round as `wait` but queues our late response.
- Creates permanent 1-round offset — bot oscillates instead of progressing.
- **Detection**: Track expected vs actual bot positions each round.
- **Recovery**: Send `wait` on mismatch to re-align. Implemented in `run.py`.

### Shelf Tiles ≠ Wall Tiles
- Item positions are NOT in `grid.walls`. They're separate non-walkable tiles.
- Must exclude them explicitly in `build_walkable_set()`.
- Forgetting this causes BFS to route through shelves → bot gets stuck.

### Silent Action Failures
- Invalid actions become `wait` with no error. Easy to miss.
- Common causes: picking up when not adjacent, dropping off when not on drop-off tile.

### Collision Deadlocks (Multi-Bot)
- Two bots in a 1-wide aisle can permanently block each other.
- Current mitigation: treat other bots as blocked tiles, fallback to unblocked BFS if no path.
- Better: corridor-sharing protocol with yielding behavior.

---

## Scoring History

| Date       | Map  | Score | Orders | Notes |
|------------|------|-------|--------|-------|
| 2026-03-03 | Easy | 30    | 3      | Desync at R105 wasted 192 rounds |
