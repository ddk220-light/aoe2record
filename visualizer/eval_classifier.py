"""Eval harness for the v2 unit classifier (unit_classifier.py).

Runs the new pipeline on a replay, prints phase-gate metrics, and compares the
class decision against the shipping baseline (server._classify_units).

Usage:
    python eval_classifier.py <replay.aoe2record> [target_player]

The mgz fork path can be overridden with the MGZ_PATH env var.
"""
import os
import sys
import types
from collections import Counter
from itertools import combinations


def _bootstrap_imports():
    # stub the web deps so 'import server' works headless
    for m in ("flask", "flask_cors", "requests"):
        sys.modules.setdefault(m, types.ModuleType(m))
    sys.modules["flask"].Flask = lambda *a, **k: types.SimpleNamespace(route=lambda *a, **k: (lambda f: f))
    sys.modules["flask"].jsonify = lambda *a, **k: None
    sys.modules["flask"].request = None
    sys.modules["flask"].send_from_directory = lambda *a, **k: None
    sys.modules["flask_cors"].CORS = lambda *a, **k: None
    mgz_path = os.environ.get("MGZ_PATH", "C:/dev/aoe2/aoc-mgz-67x")
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (mgz_path, here):
        if p not in sys.path:
            sys.path.insert(0, p)


def main():
    _bootstrap_imports()
    import mgz.model
    import server
    import unit_classifier as uc

    replay = sys.argv[1] if len(sys.argv) > 1 else "C:/dev/_tmp_replay/AgeIIDE_Replay_481391706.aoe2record"
    target = sys.argv[2] if len(sys.argv) > 2 else None

    with open(replay, "rb") as f:
        match = mgz.model.parse_match(f)
    if target is None:
        # default to the player with the most commanded units
        target = max((p.name for p in match.players), key=lambda n: 1)
    print(f"replay: {os.path.basename(replay)}  players: {[p.name for p in match.players]}")

    # --- run the pipeline with instrumentation ---
    ctx = uc.build_context(match)
    uc.behavioral_labels(ctx)
    hard = sum(1 for g in ctx.guesses.values() if g.cls != "unknown" and g.instance_id not in ctx.start_ids)
    weight = uc.cocommand_graph(ctx)
    uc.propagate_class(ctx, weight)
    # Stages 3-4: types
    uc.production_timeline(ctx)
    uc.type_units(ctx)
    squads = uc.form_squads(ctx, weight)
    uc.type_squads(ctx, squads)
    uc.finalize(ctx)
    guesses = ctx.guesses

    # --- Stage 0 gate: id normalization / no phantom dupes ---
    raw_shifted = set()
    for a in match.actions:
        if a.player:
            for o in (a.payload or {}).get("object_ids", []):
                if o >= uc.SHIFT_THRESHOLD:
                    raw_shifted.add(o)
    phantom_in_output = [cid for cid in guesses if cid >= uc.SHIFT_THRESHOLD]
    merged = sum(1 for s in raw_shifted if (s >> 8) in guesses)
    print("\n== Stage 0: id normalization ==")
    print(f"  raw shifted ids in stream: {len(raw_shifted)}  | shifted ids leaking into output: {len(phantom_in_output)} (want 0)")
    print(f"  shifted refs merged onto a canonical id: {merged}")

    # --- per-target class split vs production villager count ---
    tgt = [g for g in guesses.values() if g.player == target and g.instance_id not in ctx.start_ids
           and g.instance_id not in ctx.building_ids]
    csplit = Counter(g.cls for g in tgt)
    # villager production for target = sum of DE_QUEUE amounts (expanded)
    vil_q = 0
    for a in match.actions:
        if str(a.type).endswith("DE_QUEUE") and a.player and a.player.name == target and a.payload:
            if uc._norm(a.payload.get("unit")) == "villager":
                vil_q += a.payload.get("amount", 1) or 1
    print(f"\n== class split for {target} (non-start, non-building units: {len(tgt)}) ==")
    print(f"  villager={csplit.get('villager',0)}  military={csplit.get('military',0)}  unknown={csplit.get('unknown',0)}")
    print(f"  (DE_QUEUE villager count for {target}: {vil_q})")
    print(f"  class coverage: hard-only={hard} -> after co-command propagation="
          f"{sum(1 for g in guesses.values() if g.cls!='unknown' and g.instance_id not in ctx.start_ids)}")

    # --- Stage 1 gate: villagers that also attack stay villagers ---
    vil_attackers = [g for g in guesses.values()
                     if g.cls == "villager" and g.behavior.get("attacks_building")]
    flipped = [g for g in vil_attackers if g.cls != "villager"]
    print("\n== Stage 1: refined rules (attacks != military) ==")
    print(f"  hard/with-attack villagers that ALSO attack an enemy object: {len(vil_attackers)}")
    print(f"  of those wrongly flipped to military: {len(flipped)} (want 0)")

    # --- Stage 2 gate: pairwise class consistency among co-commanded units ---
    same = diff = 0          # all labeled (hard + propagated)
    hsame = hdiff = 0        # hard-only (cls_conf >= hard_class)
    HC = uc.CONF["hard_class"]
    for (x, y), w in weight.items():
        gx, gy = guesses.get(x), guesses.get(y)
        if not (gx and gy and gx.cls != "unknown" and gy.cls != "unknown"):
            continue
        if gx.cls == gy.cls:
            same += 1
        else:
            diff += 1
        if gx.cls_conf >= HC and gy.cls_conf >= HC:
            if gx.cls == gy.cls:
                hsame += 1
            else:
                hdiff += 1
    print("\n== Stage 2: co-command class consistency ==")
    if same + diff:
        print(f"  all-labeled edges: {same+diff}  | SAME: {100*same/(same+diff):.1f}%  | mixed: {diff}")
    if hsame + hdiff:
        print(f"  hard-only  edges: {hsame+hdiff}  | SAME: {100*hsame/(hsame+hdiff):.1f}%  | mixed: {hdiff}  (validates the signal)")

    # --- compare class decision vs shipping baseline ---
    try:
        base = server._classify_units(match)  # {id: type_string}
        agree = disagree = 0
        for g in tgt:
            bt = base.get(g.instance_id) or base.get(g.instance_id << 8)
            if bt is None:
                continue
            bcls = "villager" if bt == "villager" else "military"
            if g.cls == "unknown":
                continue
            if g.cls == bcls:
                agree += 1
            else:
                disagree += 1
        print("\n== vs shipping baseline (class agreement on target) ==")
        print(f"  agree={agree}  disagree={disagree}"
              f"  ({100*agree/(agree+disagree):.1f}% agree)" if (agree+disagree) else "  (no overlap)")
    except Exception as e:  # noqa
        print(f"\n(baseline comparison skipped: {e})")

    # --- Stage 3-4: type breakdown vs production ---
    tb = Counter(g.type for g in tgt)
    prod = Counter()
    for a in match.actions:
        if str(a.type).endswith("DE_QUEUE") and a.player and a.player.name == target and a.payload:
            prod[uc._norm(a.payload.get("unit"))] += a.payload.get("amount", 1) or 1
    typed = sum(1 for g in tgt if g.type not in uc.GENERIC_TYPES)
    print(f"\n== types for {target} ({typed}/{len(tgt)} = {100*typed/len(tgt):.0f}% typed; squads={len(squads)}) ==")
    print(f"  classified: {dict(tb.most_common())}")
    print(f"  produced:   {dict(prod.most_common())}")
    # treb placement
    treb = [g for g in tgt if g.type == "trebuchet"]
    if treb:
        import statistics
        print(f"  treb-labeled: {len(treb)} (9 queued); median first_seen="
              f"{statistics.median([g.behavior.get('first_seen',0) for g in treb]):.0f}s "
              f"%patrol={100*sum(1 for g in treb if g.behavior.get('patrols'))/len(treb):.0f} "
              f"%atkBldg={100*sum(1 for g in treb if g.behavior.get('attacks_building'))/len(treb):.0f}")


if __name__ == "__main__":
    main()
