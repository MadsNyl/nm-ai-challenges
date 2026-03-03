# Grocery Bot — Game Rules

Source: NM i AI 2026 pre-competition challenge (Feb 20 – Mar 16, 2026)

---

## Overview

Build a bot that connects via WebSocket to control warehouse agents navigating a grocery store. Pick up items from shelves and deliver them to the drop-off zone to complete orders and score points.

- **Platform**: [dev.ainm.no/challenge](https://dev.ainm.no/challenge)
- **Period**: February 20 – March 16, 2026
- **300 rounds** max per game, **120 seconds** wall-clock limit
- **10 second cooldown** between games per team
- Leaderboard = sum of your best scores across all 4 maps

---

## Difficulty Levels

| Level  | Grid  | Bots | Aisles | Item Types |
|--------|-------|------|--------|------------|
| Easy   | 12×10 | 1    | 2      | 4          |
| Medium | 16×12 | 3    | 3      | 8          |
| Hard   | 22×14 | 5    | 4      | 12         |
| Expert | 28×18 | 10   | 5      | 16         |

---

## Store Layout

The store is a rectangular grid with:

- **Floor** (`.`) — walkable cells
- **Walls** (`#`) — impassable barriers (borders + aisle walls)
- **Shelves** — contain items, not walkable. Pick up by standing adjacent.
- **Drop-off** (`D`) — where you deliver items (walkable)

Stores have parallel vertical aisles (shelf–walkway–shelf, 3 cells wide), connected by horizontal corridors at top, bottom, and mid-height.

**Coordinate system**: origin `(0,0)` is top-left. X increases right, Y increases downward.

---

## Bots

- All bots start at bottom-right of the store
- **Inventory capacity**: 3 items per bot
- **Collision**: no two bots can occupy the same tile (spawn tile exempt). Actions resolve in **bot ID order** — lower IDs move first.
- **Full visibility**: all items on all shelves are visible every round

---

## Orders

Orders are revealed one at a time and generate infinitely:

- **Active order**: current order you must complete. You can deliver items for it.
- **Preview order**: next order. Full details visible — you can pre-pick items but cannot deliver yet.
- **Hidden orders**: all remaining orders are not shown.

When the active order completes:
- Preview becomes active
- A new preview appears
- Items already in bot inventories matching the new active order are auto-delivered

### Order Sizes

| Level  | Items per Order |
|--------|----------------|
| Easy   | 3–4            |
| Medium | 3–5            |
| Hard   | 3–5            |
| Expert | 4–6            |

---

## Actions

Each bot performs one action per round:

| Action      | Extra Fields | Description                                      |
|-------------|-------------|--------------------------------------------------|
| `move_up`   | —           | Move one cell up (y−1)                           |
| `move_down` | —           | Move one cell down (y+1)                         |
| `move_left` | —           | Move one cell left (x−1)                         |
| `move_right`| —           | Move one cell right (x+1)                        |
| `pick_up`   | `item_id`   | Pick up item from adjacent shelf (distance = 1)  |
| `drop_off`  | —           | Deliver matching inventory at the drop-off zone  |
| `wait`      | —           | Do nothing                                       |

Invalid actions are treated as `wait` — no penalty.

### Pickup Rules
- Bot must be **adjacent** (Manhattan distance 1) to the shelf containing the item
- Bot inventory must not be full (max 3 items)

### Dropoff Rules
- Bot must be standing **on** the drop-off cell
- Only items matching the **active order** are consumed — non-matching items stay in inventory
- When the active order completes, the next order activates immediately and remaining inventory is re-checked

---

## Scoring

```
score = items_delivered × 1 + orders_completed × 5
```

- **+1 point** per item delivered
- **+5 bonus** for completing an entire order

### Game End Conditions

| Condition          | Description                     |
|--------------------|---------------------------------|
| 300 rounds used    | Maximum rounds reached          |
| Wall-clock timeout | 120 seconds elapsed             |
| Disconnect         | Client disconnected, score saved |

---

## WebSocket Protocol

### Connection

```
wss://game.ainm.no/ws?token=<jwt_token>
```

Get a token by clicking "Play" on a map at dev.ainm.no/challenge.

### Message Flow

```
Server → Client: {"type": "game_state", ...}   (each round)
Client → Server: {"actions": [...]}             (within 2s)
...
Server → Client: {"type": "game_over", ...}     (final)
```

### Game State (Server → Client)

```json
{
  "type": "game_state",
  "round": 42,
  "max_rounds": 300,
  "grid": {
    "width": 14,
    "height": 10,
    "walls": [[1,1], [1,2], [3,1]]
  },
  "bots": [
    {"id": 0, "position": [3, 7], "inventory": ["milk"]},
    {"id": 1, "position": [5, 3], "inventory": []}
  ],
  "items": [
    {"id": "item_0", "type": "milk", "position": [2, 1]},
    {"id": "item_1", "type": "bread", "position": [4, 1]}
  ],
  "orders": [
    {
      "id": "order_0",
      "items_required": ["milk", "bread", "eggs"],
      "items_delivered": ["milk"],
      "complete": false,
      "status": "active"
    },
    {
      "id": "order_1",
      "items_required": ["cheese", "butter"],
      "items_delivered": [],
      "complete": false,
      "status": "preview"
    }
  ],
  "drop_off": [6, 9],
  "score": 12,
  "active_order_index": 0,
  "total_orders": 8
}
```

### Actions (Client → Server, within 2 seconds)

```json
{
  "actions": [
    {"bot": 0, "action": "move_up"},
    {"bot": 1, "action": "pick_up", "item_id": "item_3"},
    {"bot": 2, "action": "drop_off"}
  ]
}
```

Timeout (>2s) → all bots wait that round. Disconnect → game ends, score saved.

### Game Over (Server → Client)

```json
{
  "type": "game_over",
  "score": 47,
  "rounds_used": 200,
  "items_delivered": 22,
  "orders_completed": 5
}
```

---

## Daily Rotation

Item placement on shelves and order contents change **daily at midnight UTC**. Grid structure (walls, shelf positions) stays fixed. Within a single day, games are **deterministic** — same algorithm = same score every run.

---

## Strategy Tips

- **Complete orders** — the +5 bonus is significant; don't just deliver individual items
- **Pre-pick for the preview order** — fill remaining inventory slots with preview items while completing the active order
- **Don't pick random items** — non-matching items waste inventory slots until the order changes
- **Assign bots to regions** — use `bot["id"]` to split bots across different map areas
- **Use BFS/A\*** — full map visible from round 1, plan routes around walls and shelves
- **Coordinate pickups** — track what each bot targets to avoid duplicate item grabs
- **Actions resolve in bot ID order** — lower-ID bots move first, plan around this for collisions
