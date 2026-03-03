# NM i AI 2026 — Official Documentation

Source: [app.ainm.no/docs](https://app.ainm.no/docs) and [app.ainm.no/docs/game](https://app.ainm.no/docs/game)

---

## Getting Started

The competition launches **March 19, 2026**. Right now the **Grocery Bot Challenge** is live as a pre-competition warm-up.

### What's Live

- **Team registration** — sign up with Google, create or join a team
- **Grocery Bot Challenge** — build a bot that controls workers in a grocery store
- **Leaderboard** — compete across 4 difficulty maps (sum of best scores)

The main competition tasks (Computer Vision, Language Model, Machine Learning) will be revealed on March 19.

### How to Play

1. Sign in at [app.ainm.no](https://app.ainm.no) with Google
2. Create or join a team
3. Go to the Challenge page, pick a difficulty, click Play
4. Connect your bot via WebSocket and respond with actions each round
5. Best score per map is saved — leaderboard = sum of all 4 maps

### Requirements

- Python 3.10+ with websockets (`pip install websockets`)
- Respond within 2 seconds per round
- Handle `game_over` messages for clean shutdown

### Support

- Competition Slack for questions and discussion
- MCP server for Claude Code: `claude mcp add --transport http nmiai https://mcp-docs.ainm.no/mcp`

---

## Grocery Bot — Game AI

Build a bot that controls a swarm of workers in a procedurally generated grocery store. Bots navigate the store, pick items from shelves, and deliver them to the drop-off zone to fulfill orders sequentially. Bot count scales by difficulty — from 1 to 10.

### How It Works

Your bot connects to the game server via WebSocket. Each round:

```
Server → Your Bot: game_state (round N)
Your Bot → Server: {"actions": [...]}
...
Server → Your Bot: game_over {score, items, orders}
```

The game runs for up to 300 rounds with a 120-second wall-clock limit.

### Difficulty Levels

| Level  | Grid  | Bots | Aisles | Item Types | Order Size |
|--------|-------|------|--------|------------|------------|
| Easy   | 12×10 | 1    | 2      | 4          | 3-4        |
| Medium | 16×12 | 3    | 3      | 8          | 3-5        |
| Hard   | 22×14 | 5    | 4      | 12         | 3-5        |
| Expert | 28×18 | 10   | 5      | 16         | 4-6        |

One map per difficulty. Item placement and orders change daily — same day, same game (deterministic).

---

### WebSocket Protocol

**Connection URL:** `wss://game.ainm.no/ws?token=<jwt_token>`

Get a token by clicking "Play" on a map at [app.ainm.no/challenge](https://app.ainm.no/challenge).

#### Game State Message

```json
{
  "type": "game_state",
  "round": 42,
  "max_rounds": 300,
  "grid": {
    "width": 16,
    "height": 12,
    "walls": [[1,1], [1,2], [3,1]]
  },
  "bots": [
    {"id": 0, "position": [3, 7], "inventory": ["milk"]},
    {"id": 1, "position": [5, 3], "inventory": []},
    {"id": 2, "position": [10, 7], "inventory": ["bread", "eggs"]}
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
  "drop_off": [1, 10],
  "score": 12
}
```

#### Field Reference

| Field              | Type     | Description                                        |
|--------------------|----------|----------------------------------------------------|
| `round`            | int      | Current round (0-indexed)                          |
| `max_rounds`       | int      | Maximum rounds (300)                               |
| `grid.width`       | int      | Grid width in cells                                |
| `grid.height`      | int      | Grid height in cells                               |
| `grid.walls`       | int[][]  | List of [x, y] wall positions                      |
| `bots`             | object[] | All bots with id, position [x,y], and inventory    |
| `items`            | object[] | All items on shelves with id, type, and position    |
| `orders`           | object[] | Active + preview orders (max 2 visible)             |
| `drop_off`         | int[]    | [x, y] of the drop-off zone                        |
| `score`            | int      | Current score                                      |

#### Bot Response

Send within **2 seconds** of receiving the game state:

```json
{
  "actions": [
    {"bot": 0, "action": "move_up"},
    {"bot": 1, "action": "pick_up", "item_id": "item_3"},
    {"bot": 2, "action": "drop_off"}
  ]
}
```

---

### Actions

Each bot performs one action per round:

| Action       | Extra Fields | Description                         |
|--------------|-------------|--------------------------------------|
| `move_up`    | —           | Move one cell up (y-1)               |
| `move_down`  | —           | Move one cell down (y+1)             |
| `move_left`  | —           | Move one cell left (x-1)             |
| `move_right` | —           | Move one cell right (x+1)            |
| `pick_up`    | `item_id`   | Pick up item from adjacent shelf     |
| `drop_off`   | —           | Deliver matching items at drop-off   |
| `wait`       | —           | Do nothing                           |

Invalid actions are treated as `wait` — no penalty.

#### Move Rules

- Moves into walls, shelves, or out-of-bounds fail silently (become `wait`)
- Moves into a cell occupied by another bot fail silently
- Actions resolve in **bot ID order** — bot 0 moves first, then bot 1, etc.
- The spawn tile (bottom-right) is exempt from collision at game start

#### Pickup Rules

- Bot must be **adjacent** (Manhattan distance 1) to the shelf containing the item
- Bot inventory must not be full (max 3 items)
- `item_id` must match an item on the map

#### Dropoff Rules

- Bot must be standing **on** the drop-off cell
- Only items matching the **active order** are delivered
- Non-matching items **stay in inventory**
- When an order completes, the next order activates and remaining items are re-checked

---

### Orders

Orders are revealed **one at a time** and keep generating infinitely:

- **Active order** — current order, you can deliver items for it
- **Preview order** — next order, visible but can't deliver yet (can pre-pick items)
- **Infinite** — when you complete an order, a new one appears. Rounds are the only limit.

---

### Scoring

| Event           | Points   |
|-----------------|----------|
| Item delivered   | +1       |
| Order completed  | +5 bonus |

**Leaderboard score** = sum of best scores across all 4 maps.

---

### Constraints

- 300 rounds maximum per game
- 120 seconds wall-clock limit
- 3 items per bot inventory
- Collision — bots block each other (no two on same tile, except spawn)
- Full visibility — entire map visible every round
- 2-second timeout per round for your response
- 60-second cooldown between games, max 40/hour and 300/day per team
- Disconnect = game over — no reconnect

### Coordinate System

- Origin `(0, 0)` is the **top-left** corner
- X increases to the right
- Y increases downward

---

### Example Bot

```python
import asyncio
import json
import websockets

WS_URL = "wss://game.ainm.no/ws?token=YOUR_TOKEN"

async def play():
    async with websockets.connect(WS_URL) as ws:
        while True:
            msg = json.loads(await ws.recv())

            if msg["type"] == "game_over":
                print(f"Game over! Score: {msg['score']}")
                break

            state = msg
            actions = []

            for bot in state["bots"]:
                action = decide(bot, state)
                actions.append(action)

            await ws.send(json.dumps({"actions": actions}))

def decide(bot, state):
    x, y = bot["position"]
    drop_off = state["drop_off"]

    if bot["inventory"] and [x, y] == drop_off:
        return {"bot": bot["id"], "action": "drop_off"}

    if len(bot["inventory"]) >= 3:
        return move_toward(bot["id"], x, y, drop_off)

    active = next((o for o in state["orders"] if o["status"] == "active"), None)
    if not active:
        return {"bot": bot["id"], "action": "wait"}

    needed = list(active["items_required"])
    for d in active["items_delivered"]:
        if d in needed:
            needed.remove(d)

    for item in state["items"]:
        if item["type"] in needed:
            ix, iy = item["position"]
            if abs(ix - x) + abs(iy - y) == 1:
                return {"bot": bot["id"], "action": "pick_up", "item_id": item["id"]}

    for item in state["items"]:
        if item["type"] in needed:
            return move_toward(bot["id"], x, y, item["position"])

    if bot["inventory"]:
        return move_toward(bot["id"], x, y, drop_off)

    return {"bot": bot["id"], "action": "wait"}

def move_toward(bot_id, x, y, target):
    tx, ty = target
    if abs(tx - x) > abs(ty - y):
        return {"bot": bot_id, "action": "move_right" if tx > x else "move_left"}
    elif ty != y:
        return {"bot": bot_id, "action": "move_down" if ty > y else "move_up"}
    return {"bot": bot_id, "action": "wait"}

asyncio.run(play())
```

This basic bot uses greedy Manhattan distance — it does **not** handle walls. Improvements needed:
- BFS/A* pathfinding around walls and shelves
- Role assignment for multi-bot levels
- Coordinated pickups to avoid duplication
- Pre-picking items for the preview order
