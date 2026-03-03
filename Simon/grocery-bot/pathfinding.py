"""
Pathfinding utilities (BFS) for navigating the grocery store grid.

Grid conventions:
  - Origin (0,0) = top-left
  - X increases right, Y increases down
  - Walls/shelves are non-walkable
  - Items sit on shelf (non-walkable) tiles; bots pick up from adjacent floor
"""

from collections import deque

# Direction vectors: action name -> (dx, dy)
DIRECTIONS = {
    "move_up": (0, -1),
    "move_down": (0, 1),
    "move_left": (-1, 0),
    "move_right": (1, 0),
}


def build_walkable_set(grid: dict, items: list[dict]) -> set[tuple[int, int]]:
    """Build set of walkable (x, y) positions from the grid data.

    Items sit on shelf tiles which are non-walkable but NOT listed in
    grid.walls — we must exclude them explicitly.
    """
    w, h = grid["width"], grid["height"]
    walls = set(tuple(p) for p in grid["walls"])
    shelves = set(tuple(i["position"]) for i in items)
    blocked = walls | shelves
    walkable = set()
    for y in range(h):
        for x in range(w):
            if (x, y) not in blocked:
                walkable.add((x, y))
    return walkable


def bfs(
    start: tuple[int, int],
    goal: tuple[int, int],
    walkable: set[tuple[int, int]],
    blocked: set[tuple[int, int]] | None = None,
) -> list[tuple[int, int]] | None:
    """
    BFS shortest path from start to goal on walkable tiles.

    Args:
        start: (x, y) starting position
        goal: (x, y) target position (must be walkable)
        walkable: set of walkable positions
        blocked: additional temporarily blocked positions (e.g. other bots)

    Returns:
        List of (x, y) positions from start to goal (inclusive), or None if
        no path exists.
    """
    if start == goal:
        return [start]

    passable = walkable - blocked if blocked else walkable
    # Start and goal must be passable even if "blocked" (bot is already there)
    if goal not in walkable:
        return None

    queue = deque([(start, [start])])
    visited = {start}

    while queue:
        (x, y), path = queue.popleft()
        for dx, dy in DIRECTIONS.values():
            nx, ny = x + dx, y + dy
            npos = (nx, ny)
            if npos in visited:
                continue
            if npos == goal:
                return path + [npos]
            if npos not in passable:
                continue
            visited.add(npos)
            queue.append((npos, path + [npos]))

    return None


def bfs_to_any(
    start: tuple[int, int],
    goals: set[tuple[int, int]],
    walkable: set[tuple[int, int]],
    blocked: set[tuple[int, int]] | None = None,
) -> tuple[tuple[int, int], list[tuple[int, int]]] | None:
    """
    BFS from start to the nearest goal in `goals`.

    Returns:
        (goal_reached, path) or None if no goal is reachable.
    """
    if start in goals:
        return (start, [start])

    passable = walkable - blocked if blocked else walkable

    queue = deque([(start, [start])])
    visited = {start}

    while queue:
        (x, y), path = queue.popleft()
        for dx, dy in DIRECTIONS.values():
            nx, ny = x + dx, y + dy
            npos = (nx, ny)
            if npos in visited:
                continue
            if npos in goals:
                return (npos, path + [npos])
            if npos not in passable:
                continue
            visited.add(npos)
            queue.append((npos, path + [npos]))

    return None


def adjacent_walkable(
    pos: tuple[int, int], walkable: set[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Get walkable tiles adjacent to pos (for picking up items on shelves)."""
    x, y = pos
    result = []
    for dx, dy in DIRECTIONS.values():
        adj = (x + dx, y + dy)
        if adj in walkable:
            result.append(adj)
    return result


def bfs_distance_map(
    start: tuple[int, int],
    walkable: set[tuple[int, int]],
    blocked: set[tuple[int, int]] | None = None,
) -> dict[tuple[int, int], int]:
    """
    BFS from start, returning distance to every reachable tile.

    Used for efficient multi-point distance lookups (e.g. TSP route planning)
    without running separate BFS for each destination.
    """
    passable = walkable - blocked if blocked else walkable
    dist = {start: 0}
    queue = deque([start])

    while queue:
        x, y = queue.popleft()
        d = dist[(x, y)]
        for dx, dy in DIRECTIONS.values():
            npos = (x + dx, y + dy)
            if npos not in dist and npos in passable:
                dist[npos] = d + 1
                queue.append(npos)

    return dist


def path_to_action(current: tuple[int, int], next_pos: tuple[int, int]) -> str:
    """Convert a step from current to next_pos into a move action string."""
    dx = next_pos[0] - current[0]
    dy = next_pos[1] - current[1]
    for action, (adx, ady) in DIRECTIONS.items():
        if dx == adx and dy == ady:
            return action
    return "wait"
