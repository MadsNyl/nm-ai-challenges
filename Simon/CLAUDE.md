# NM i AI 2026

**Team Guttakrutt** — Competition project for NM i AI (Norwegian Championship in AI) 2026.
Main competition launches March 19 with CV, NLP, and ML tasks.

**Repo**: https://github.com/SimonKvalheim/guttakrutt-NMiAI

## Project Structure

```
nm/
├── CLAUDE.md
├── docs.md                # Full official docs (game rules, protocol, examples)
├── requirements.txt
├── venv/                  # Python 3.14, websockets
├── grocery-bot/           # Pre-competition warm-up challenge
│   ├── run.py             # Entry point — connects via WebSocket
│   ├── pathfinding.py     # BFS grid navigation
│   ├── strategy.py        # Order fulfillment & bot coordination
│   └── explore.py         # Exploration/debugging script
```

## Running

```bash
source venv/bin/activate
python grocery-bot/run.py <websocket_url>
```

Get a fresh WebSocket URL from app.ainm.no/challenge (tokens expire).

## Grocery Bot — Key Reference

Game: control bots in a grocery store grid to fulfill orders.

### Protocol
- Connect via WebSocket, receive JSON game state each round, respond with actions
- 300 rounds max, 120s wall-clock, 2s response timeout per round
- 60s cooldown between games

### Coordinate System
- Origin (0,0) = top-left. X right, Y down.

### Actions
- `move_up` (y-1), `move_down` (y+1), `move_left` (x-1), `move_right` (x+1)
- `pick_up` (needs `item_id`, bot must be adjacent to shelf)
- `drop_off` (bot must be ON the drop-off cell, only delivers to active order)
- `wait` — invalid actions silently become wait

### Difficulty Scaling
| Level  | Grid  | Bots | Item Types | Order Size |
|--------|-------|------|------------|------------|
| Easy   | 12×10 | 1    | 4          | 3-4        |
| Medium | 16×12 | 3    | 8          | 3-5        |
| Hard   | 22×14 | 5    | 12         | 3-5        |
| Expert | 28×18 | 10   | 16         | 4-6        |

### Core Mechanics
- **Inventory**: max 3 items per bot
- **Orders**: sequential (active + preview visible). Infinite supply, rounds are the limit.
- **Scoring**: +1 per item delivered, +5 bonus per completed order
- **Collisions**: bots block each other (except spawn tile)
- **Items on shelves**: shelves aren't walkable, pick up from adjacent floor tile
- **Daily rotation**: item placement and orders change daily, deterministic within a day

### Map Structure (observed from Easy)
- Border walls on all edges
- Vertical shelf columns with 1-tile walkways between them
- Horizontal corridors at top, middle, and bottom connecting the aisles
- Drop-off at bottom-left, bots spawn at bottom-right

## MCP Server

Challenge docs available via the `grocery-bot` MCP server.
```bash
claude mcp add --transport http grocery-bot https://mcp-docs.ainm.no/mcp
```

## Development Notes

- The naive greedy move-toward strategy gets stuck on walls — BFS pathfinding is mandatory
- Items are on non-walkable shelf tiles; the bot navigates to an adjacent walkable tile then issues pick_up
- **Items are infinite** — shelves never deplete. The `items` list stays constant. Same item can be picked up repeatedly.
- **Shelf tiles ≠ wall tiles** — item positions are NOT in `grid.walls`. Must exclude them separately in pathfinding.
- **Desync risk**: if a WebSocket response arrives >2s late, the server offsets all subsequent actions by 1 round. Added detection + recovery (send `wait` to re-align).
- For multi-bot levels: coordinate to avoid collisions and duplicate item targeting
- Leaderboard = sum of best scores across all 4 maps

## Scoring History (Easy)

| Date       | Score | Orders | Notes |
|------------|-------|--------|-------|
| 2026-03-03 | 30    | 3      | Desync at R105 wasted 192 rounds |
