# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Challenge Context

This is a submission for the **NM i AI 2026 Grocery Bot** pre-competition challenge (Feb 20 – Mar 16, 2026). The bot controls warehouse agents via WebSocket to navigate a grocery store, pick up items, and deliver orders.

- Platform: [app.ainm.no](https://app.ainm.no) / [dev.ainm.no](https://dev.ainm.no)
- 4 difficulty maps: Easy (1 bot, 12×10), Medium (3 bots, 16×12), Hard (5 bots, 22×14), Expert (10 bots, 28×18)
- **Scoring**: `score = items_delivered × 1 + orders_completed × 5`
- 300 rounds max per game, 120s wall-clock limit, 10s cooldown between games
- Leaderboard = sum of best scores across all 4 maps

## Running the Bot

```bash
# Install dependencies
pip install -r requirements.txt

# Run with default hardcoded WS_URL
python bot.py

# Run with a specific WebSocket URL
python bot.py "wss://game.ainm.no/ws?token=<jwt>"
```

Get a WebSocket token by clicking "Play" on a map at dev.ainm.no/challenge.

## Architecture

`bot.py` is a single-file bot with four layers:

1. **Pathfinding** — `bfs(start, goal, walls_set, grid_width, grid_height)` returns a list of `(x, y, action)` steps. `next_action_towards()` wraps it to return a single action dict.

2. **Item targeting** — `_find_target_items()` selects which items to pick up: active-order items first, then preview-order items to fill remaining slots (3 per bot). `claimed_item_ids` prevents multiple bots from targeting the same item.

3. **Decision logic** — `decide_actions()` orchestrates per-round decisions, iterating bots in ID order (matching server collision resolution). `decide_bot()` implements per-bot priority:
   - Deliver if carrying useful items AND (inventory full OR all active items in hand)
   - Wait if inventory full but nothing useful
   - Pick up targeting items (active order priority, preview fills remaining slots)
   - Deliver now if carrying useful items but no more targets exist

4. **WebSocket loop** — `play()` connects, accumulates `shelf_positions` across rounds (shelves remain impassable after pickup), and sends actions each round.

## Game Protocol

**Server → Client** (each round):
```json
{"type": "game_state", "round": 0, "grid": {"width": 14, "height": 10, "walls": [[x,y]]},
 "bots": [{"id": 0, "position": [x,y], "inventory": ["milk"]}],
 "items": [{"id": "item_0", "type": "milk", "position": [x,y]}],
 "orders": [{"status": "active", "items_required": [...], "items_delivered": [...]},
             {"status": "preview", "items_required": [...], "items_delivered": []}],
 "drop_off": [x,y], "score": 0}
```

**Client → Server** (within 2s):
```json
{"actions": [{"bot": 0, "action": "move_up"}, {"bot": 1, "action": "pick_up", "item_id": "item_3"}]}
```

Key constraints:
- Coordinate system: `(0,0)` = top-left, X right, Y down
- Bots must be **adjacent** to a shelf to pick up (not on it — shelves are walls)
- Bots must be **on** the drop-off cell to deliver
- Only active-order items are consumed at drop-off; non-matching items stay in inventory
- Actions resolve in bot ID order (lower ID moves first)

## Strategy Notes

- Order completion bonus (+5) is significant — prioritize completing orders over raw item delivery
- Pre-pick items for the preview order to fill inventory while active order is being completed
- Shelf positions accumulate over rounds and block movement (tracked in `shelf_positions`)
- Bot collision: bots process in ID order, so lower-ID bots have movement priority
