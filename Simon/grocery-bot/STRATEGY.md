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

## Current Decision Priorities (v4)

```
0. Endgame scavenge — if <45 rounds left and order can't complete
1. Drop-off — on drop-off with useful items → deliver
S. Stuck recovery — inventory full + nothing useful → go to drop-off
2. Full inventory — navigate to drop-off
3. Adjacent ACTIVE item → pick up (NEVER preview items here)
4. TSP route — optimal multi-stop for active items
   Chain items only on LAST trip (active_picks < slots_free)
4.5. Fill spare slots with preview items before delivering
     Only when active fully collected + spare slots + detour ≤ 8 rounds
     Items stay in inventory after drop_off, become useful when preview activates
5. Deliver — go to drop-off with partial inventory
6. Preview pre-pick — ONLY when active order fully handled
7. Wait
```

---

## Optimization Techniques

### 1. TSP Route Planning
**Problem**: Greedy nearest-item picks suboptimal sequences.

**Solution**: Enumerate all (item, pickup_tile) combinations and evaluate every permutation. Pick the route with minimum total distance: `pos → tile₁ → tile₂ → ... → drop_off`.

- Uses `bfs_distance_map()` for exact distance from current position
- Manhattan distance for intermediate legs (fast approximation)
- Caps at 6 items (6! = 720 permutations) — always fast enough
- Re-plans every round (stateless) — naturally adapts as items get picked up

### 2. Drop-Off Chain Exploitation (Conservative)
**Problem**: Spare inventory slots wasted on final delivery trip.

**Solution**: On the LAST pickup trip only (when `active_picks < slots_free`), fill spare slots with preview items that chain-deliver on drop-off.

**CRITICAL GUARD**: Chain items must ONLY be added when ALL active items fit in remaining inventory. Adding chain items before securing active items causes deadlocks (see Pitfalls).

### 2b. Pre-Delivery Preview Fill (v4)
**Problem**: After collecting the last active item (e.g., 4th item of a 4-item order via adjacent pickup), the bot has 1 item in inventory with 2 empty slots but heads straight to drop-off. Those empty slots are wasted.

**Solution**: Priority 4.5 — before delivering, check for preview items within a detour budget (≤8 extra rounds). Pick them up to fill inventory. After drop_off, the active items are delivered but preview items stay in inventory. When the preview order activates, those items are immediately useful — saving a full trip.

**Impact**: The v3 replay had 7 single-item return trips (9 rounds each = 63 rounds). With preview fill, these become 2-3 item trips.

### 3. Forward-Looking Tile Selection
**Problem**: Choosing the nearest pickup tile may point away from the next destination.

**Solution**: Score each pickup tile as `distance(pos → tile) + distance(tile → next_dest)` and pick the minimum. Applied in preview pre-picks (priority 6).

### 4. Endgame Scavenge Mode
**Problem**: With <45 rounds left, can't complete a full order.

**Solution**: Switch to rapid single-item deliveries (+1 each) instead of chasing +5 bonus.

### 5. Path Detours (SUPERSEDED by Priority 4.5)
Previously disabled due to deadlocks (picking preview items before active items secured).
Now replaced by Priority 4.5 which is safe: only triggers when active order is fully collected,
and uses a detour budget to avoid excessive wandering.

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

---

## Known Pitfalls

### Preview Item Deadlock (CRITICAL — fixed in v3)
- **Cause**: Bot picks preview/chain items before securing all active items. Inventory fills with items that don't match active order → permanent deadlock.
- **Example**: Active needs yogurt, bot picks butter+cheese (preview) first → full inventory → can never pick yogurt → 100+ rounds wasted.
- **Fix**: Priority 3 (adjacent pickup) ONLY checks active items. Chain items only added in Priority 4 TSP when `active_picks < slots_free`.
- **Safety net**: Stuck recovery sends bot to drop-off when inventory full + nothing useful.

### Desync
- If WebSocket response arrives >2s late, server treats round as `wait` but queues our late response.
- Creates permanent 1-round offset — bot oscillates instead of progressing.
- **Detection**: Track expected vs actual bot positions each round.
- **Recovery**: Send `wait` on mismatch to re-align. Implemented in `run.py`.

### Shelf Tiles ≠ Wall Tiles
- Item positions are NOT in `grid.walls`. They're separate non-walkable tiles.
- Must exclude them explicitly in `build_walkable_set()`.

### Silent Action Failures
- Invalid actions become `wait` with no error.
- Common causes: picking up when not adjacent, dropping off when not on drop-off tile.

### Collision Deadlocks (Multi-Bot)
- Two bots in a 1-wide aisle can permanently block each other.
- Current mitigation: treat other bots as blocked tiles, fallback to unblocked BFS if no path.

---

## Scoring History

| Date       | Map  | Score | Orders | Notes |
|------------|------|-------|--------|-------|
| 2026-03-03 | Easy | 30    | 3      | v1 greedy. Desync at R105 wasted 192 rounds |
| 2026-03-03 | Easy | 46    | 5      | v2 with TSP+chain. Chain bug caused deadlock at R190 (110 rounds wasted) |
| 2026-03-03 | Easy | 82    | 9      | v3 fixed chain logic. 37 items, 17 trips, avg 10.3 rounds/trip |

## v3 Replay Analysis (Score 82)

- 300 rounds, 9 completed orders (10th incomplete), 37 items delivered
- **1-item return trips were the #1 bottleneck**: 7 of 17 trips carried only 1 item (9 rounds each)
- Root cause: after adjacent pickup of last active item, `still_needed` = {} → chain logic skipped → priority 5 delivered immediately
- Best trips: 8 rounds for 3 items (0.38 eff). Worst: 16 rounds for 3 items on trip 1
- 3-item orders completed in 14 rounds (fast). 4-item orders took 32-39 rounds (slow due to 2 trips)
- Score/round: 0.273. Target 142 needs 0.473 (73% improvement)

## Next Improvements to Try
- Tune detour budget (currently 8) based on actual map distances
- Smarter delivery batching (deliver 2 items if 3rd is far away)
- Multi-bot coordination for Medium/Hard/Expert maps
- Profile which item clusters are fastest round-trips from drop-off
