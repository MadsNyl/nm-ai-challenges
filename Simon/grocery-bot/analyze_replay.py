"""Analyze a replay file for optimization insights."""
import json
import sys

def analyze(path):
    with open(path) as f:
        data = json.load(f)

    rounds = data["frames"]
    print(f"=== GAME INFO ===")
    print(f"Rounds: {len(rounds)}")
    s0 = rounds[0]["state"]
    print(f"Grid: {s0['grid']['width']}x{s0['grid']['height']}")
    print(f"Drop-off: {s0['drop_off']}")
    print(f"Bot spawn: {s0['bots'][0]['position']}")

    # Item layout
    items = s0["items"]
    item_types = {}
    for item in items:
        t = item["type"]
        item_types.setdefault(t, []).append(tuple(item["position"]))
    print(f"\n=== MAP ITEMS ({len(items)} total, {len(item_types)} types) ===")
    for t, positions in sorted(item_types.items()):
        print(f"  {t}: {len(positions)} items at {positions[:5]}")

    # Action distribution
    print("\n=== ACTION DISTRIBUTION ===")
    action_counts = {}
    wait_rounds = []
    for r in rounds:
        act = r.get("actions", [{}])[0].get("action", "unknown")
        action_counts[act] = action_counts.get(act, 0) + 1
        if act == "wait":
            wait_rounds.append(r["state"]["round"])
    for a, c in sorted(action_counts.items(), key=lambda x: -x[1]):
        print(f"  {a}: {c}")
    if wait_rounds:
        print(f"  Wait rounds ({len(wait_rounds)}): {wait_rounds}")

    # Score changes / deliveries
    print("\n=== SCORE EVENTS ===")
    prev_score = 0
    for r in rounds:
        rd = r["state"]["round"]
        s = r["state"]
        score = s.get("score", 0)
        if score > prev_score:
            delta = score - prev_score
            bot = s["bots"][0]
            active = next((o for o in s["orders"] if o["status"] == "active"), None)
            info = ""
            if delta >= 5:
                info = " << ORDER COMPLETE"
            print(f"  R{rd:3d}: +{delta:2d} (total={score:3d}) bot@{bot['position']} inv={bot['inventory']}{info}")
            prev_score = score

    # Order timeline
    print("\n=== ORDER TIMELINE ===")
    prev_active_id = None
    order_starts = {}
    order_ends = {}
    order_items = {}
    for r in rounds:
        rd = r["state"]["round"]
        active = next((o for o in r["state"]["orders"] if o["status"] == "active"), None)
        if active:
            aid = active["id"]
            if aid != prev_active_id:
                if prev_active_id is not None:
                    order_ends[prev_active_id] = rd - 1
                order_starts[aid] = rd
                order_items[aid] = len(active["items_required"])
                prev_active_id = aid
    if prev_active_id and prev_active_id not in order_ends:
        order_ends[prev_active_id] = len(rounds) - 1

    for i, oid in enumerate(order_starts):
        start = order_starts[oid]
        end = order_ends.get(oid, len(rounds) - 1)
        dur = end - start + 1
        n_items = order_items[oid]
        completed = "DONE" if dur < 290 else "INCOMPLETE"
        print(f"  Order {i+1} ({n_items} items): R{start:3d}-R{end:3d} = {dur:3d} rounds  [{completed}]")

    # Trip analysis (pick_up → drop_off cycles)
    print("\n=== TRIP ANALYSIS ===")
    trips = []
    trip_start = None
    trip_items = 0
    for r in rounds:
        rd = r["state"]["round"]
        act = r.get("actions", [{}])[0].get("action", "unknown")
        if act == "pick_up" and trip_start is None:
            trip_start = rd
            trip_items = 1
        elif act == "pick_up" and trip_start is not None:
            trip_items += 1
        elif act == "drop_off" and trip_start is not None:
            trips.append((trip_start, rd, rd - trip_start, trip_items))
            trip_start = None
            trip_items = 0

    for i, (start, end, dur, items) in enumerate(trips):
        eff = items / dur if dur > 0 else 0
        print(f"  Trip {i+1:2d}: R{start:3d}-R{end:3d} = {dur:2d} rounds, {items} items (eff={eff:.2f})")

    if trips:
        avg_dur = sum(t[2] for t in trips) / len(trips)
        avg_items = sum(t[3] for t in trips) / len(trips)
        print(f"\n  Total trips: {len(trips)}")
        print(f"  Avg trip duration: {avg_dur:.1f} rounds")
        print(f"  Avg items/trip: {avg_items:.1f}")
        print(f"  Avg rounds/item: {avg_dur/avg_items:.1f}" if avg_items > 0 else "")

    # Efficiency estimate
    final_score = rounds[-1]["state"].get("score", 0)
    print(f"\n=== SUMMARY ===")
    print(f"  Final score: {final_score}")
    print(f"  Rounds used: {len(rounds)}")
    print(f"  Score/round: {final_score/len(rounds):.3f}")
    print(f"  Target (142): would need {142/len(rounds):.3f} score/round")
    print(f"  Gap: {142 - final_score} points ({(142-final_score)/142*100:.0f}% improvement needed)")

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "grocery-bot/replays/20260303_211252_unknown.json"
    analyze(path)
