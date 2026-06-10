"""
HoopIQ API — NBA + Euroleague projections + real-time draft + waiver wire
"""

import os
import random
import string
import time
import gevent
import pandas as pd
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "hoopiq-secret-2026")
CORS(app, resources={r"/*": {"origins": [
    "https://rozymozy.github.io",
    "http://localhost:3000",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
]}})
socketio = SocketIO(app, cors_allowed_origins=[
    "https://rozymozy.github.io",
    "http://localhost:3000",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
], async_mode="gevent")

folder = os.path.dirname(os.path.abspath(__file__))

# =============================================================================
# LOAD DATA
# =============================================================================
print("Loading NBA data...")
df    = pd.read_csv(os.path.join(folder, "nba_features.csv"))
df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"])
preds = pd.read_csv(os.path.join(folder, "nba_predictions.csv"))
preds["GAME_DATE"] = pd.to_datetime(preds["GAME_DATE"])
print(f"  NBA: {len(df):,} records, {df['PLAYER_NAME'].nunique()} players")

el_df = el_preds = None
if os.path.exists(os.path.join(folder, "euroleague_features.csv")):
    print("Loading Euroleague data...")
    el_df    = pd.read_csv(os.path.join(folder, "euroleague_features.csv"))
    el_df["GAME_DATE"] = pd.to_datetime(el_df["GAME_DATE"], errors="coerce")
    el_preds = pd.read_csv(os.path.join(folder, "euroleague_predictions.csv"))
    el_preds["GAME_DATE"] = pd.to_datetime(el_preds["GAME_DATE"], errors="coerce")
    print(f"  EL:  {len(el_df):,} records, {el_df['PLAYER_NAME'].nunique()} players")

# =============================================================================
# DATA HELPERS
# =============================================================================
def get_nba_team_map():
    latest = (df.sort_values("GAME_DATE")
                .groupby("PLAYER_NAME").last()
                .reset_index()[["PLAYER_NAME","TEAM"]])
    return dict(zip(latest["PLAYER_NAME"], latest["TEAM"]))

def get_projections():
    team_map = get_nba_team_map()
    latest = (preds.sort_values("GAME_DATE")
              .groupby("PLAYER_NAME").last()
              .reset_index())[["PLAYER_NAME","PREDICTED","OPP","HOME","GAME_DATE"]]
    latest.columns = ["name","proj_dk","opp","home","last_game"]
    latest["proj_dk"] = latest["proj_dk"].round(1)
    latest["team"] = latest["name"].map(team_map).fillna("—")
    return latest

def get_season_avgs():
    avgs = (df.groupby("PLAYER_NAME").agg(
        games=("GAME_DATE","count"), pts=("PTS","mean"), reb=("REB","mean"),
        ast=("AST","mean"), stl=("STL","mean"), blk=("BLK","mean"),
        tov=("TOV","mean"), fg3m=("FG3M","mean"), fgm=("FGM","mean"),
        fga=("FGA","mean"), ftm=("FTM","mean"), fta=("FTA","mean"),
        dk_avg=("DK_PTS","mean"), dk_std=("DK_PTS","std"), min_avg=("MIN","mean"),
    ).reset_index().round(2))
    avgs["fg_pct"] = (avgs["fgm"] / avgs["fga"].replace(0,1)).round(3)
    avgs["ft_pct"] = (avgs["ftm"] / avgs["fta"].replace(0,1)).round(3)
    avgs.rename(columns={"PLAYER_NAME":"name"}, inplace=True)
    return avgs

def get_el_projections():
    latest = (el_preds.sort_values("GAME_DATE")
              .groupby("PLAYER_NAME").last().reset_index())
    keep = ["PLAYER_NAME","TEAM","OPP","GAME_DATE","DK_PTS_pred",
            "PTS","REB","AST","STL","BLK","TOV","FG3M","FGM","FGA","FTM","FTA"]
    keep = [c for c in keep if c in latest.columns]
    latest = latest[keep].copy()
    latest.rename(columns={"PLAYER_NAME":"name","TEAM":"team","OPP":"opp",
        "GAME_DATE":"last_game","DK_PTS_pred":"proj_dk","PTS":"proj_pts",
        "REB":"proj_reb","AST":"proj_ast","STL":"proj_stl","BLK":"proj_blk",
        "TOV":"proj_tov","FG3M":"proj_fg3m","FGM":"proj_fgm","FGA":"proj_fga",
        "FTM":"proj_ftm","FTA":"proj_fta"}, inplace=True)
    num_cols = [c for c in latest.columns if c not in ("name","team","opp","last_game")]
    latest[num_cols] = latest[num_cols].round(1)
    return latest

def get_el_season_avgs():
    agg = {k:v for k,v in {
        "games":("GAME_DATE","count"),"pts":("PTS","mean"),"reb":("REB","mean"),
        "ast":("AST","mean"),"stl":("STL","mean"),"blk":("BLK","mean"),
        "tov":("TOV","mean"),"fg3m":("FG3M","mean"),"fgm":("FGM","mean"),
        "fga":("FGA","mean"),"ftm":("FTM","mean"),"fta":("FTA","mean"),
        "dk_avg":("DK_PTS","mean"),"dk_std":("DK_PTS","std"),"min_avg":("MIN","mean"),
        "pir_avg":("PIR","mean"),
    }.items() if v[0] in el_df.columns}
    avgs = el_df.groupby("PLAYER_NAME").agg(**agg).reset_index().round(2)
    if "fgm" in avgs.columns and "fga" in avgs.columns:
        avgs["fg_pct"] = (avgs["fgm"] / avgs["fga"].replace(0,1)).round(3)
    if "ftm" in avgs.columns and "fta" in avgs.columns:
        avgs["ft_pct"] = (avgs["ftm"] / avgs["fta"].replace(0,1)).round(3)
    avgs.rename(columns={"PLAYER_NAME":"name"}, inplace=True)
    return avgs

# =============================================================================
# DRAFT PLAYER POOL
# =============================================================================
_pool_cache = {}   # cleared on each deploy; league -> [player, ...]

def _infer_pos(pts, reb, ast, blk, fg3m):
    if ast >= 5.0 and pts >= 10:   return "PG"
    if fg3m >= 1.5 and pts >= 12:  return "SG"
    if blk >= 1.0 and reb >= 7:    return "C"
    if reb >= 6 and blk >= 0.5:    return "PF"
    return "SF"

def _pct(made, att):
    return round(made / att, 3) if att > 0 else 0.0

def build_player_pool(league="nba"):
    global _pool_cache
    if league in _pool_cache:
        return _pool_cache[league]
    players = []
    if league == "nba":
        proj = get_projections(); avgs = get_season_avgs()
        nba  = proj.merge(avgs, on="name", how="left")
        for _, r in nba.iterrows():
            pts  = float(r.get("pts")  or 0)
            reb  = float(r.get("reb")  or 0)
            ast  = float(r.get("ast")  or 0)
            stl  = float(r.get("stl")  or 0)
            blk  = float(r.get("blk")  or 0)
            tov  = float(r.get("tov")  or 0)
            fg3m = float(r.get("fg3m") or 0)
            fgm  = float(r.get("fgm")  or 0)
            fga  = float(r.get("fga")  or 0)
            ftm  = float(r.get("ftm")  or 0)
            fta  = float(r.get("fta")  or 0)
            players.append({
                "id":      f"nba_{r['name']}",
                "name":    r["name"],
                "league":  "NBA",
                "team":    str(r.get("team") or "—"),
                "opp":     str(r.get("opp")  or "—"),
                "pos":     _infer_pos(pts, reb, ast, blk, fg3m),
                "proj_dk": round(float(r.get("proj_dk") or 0), 1),
                "dk_avg":  round(float(r.get("dk_avg")  or 0), 1),
                "pts":  round(pts,  1), "reb": round(reb, 1),
                "ast":  round(ast,  1), "stl": round(stl, 1),
                "blk":  round(blk,  1), "tov": round(tov, 1),
                "fg3m": round(fg3m, 1),
                "fg_pct": _pct(fgm, fga),
                "ft_pct": _pct(ftm, fta),
            })
    elif league == "el" and el_df is not None:
        el_p = get_el_projections(); el_a = get_el_season_avgs()
        el   = el_p.merge(el_a, on="name", how="left")
        for _, r in el.iterrows():
            pts  = float(r.get("pts")  or 0)
            reb  = float(r.get("reb")  or 0)
            ast  = float(r.get("ast")  or 0)
            stl  = float(r.get("stl")  or 0)
            blk  = float(r.get("blk")  or 0)
            tov  = float(r.get("tov")  or 0)
            fg3m = float(r.get("fg3m") or 0)
            fgm  = float(r.get("fgm")  or 0)
            fga  = float(r.get("fga")  or 0)
            ftm  = float(r.get("ftm")  or 0)
            fta  = float(r.get("fta")  or 0)
            players.append({
                "id":      f"el_{r['name']}",
                "name":    r["name"],
                "league":  "EL",
                "team":    str(r.get("team") or "—"),
                "opp":     str(r.get("opp")  or "—"),
                "pos":     _infer_pos(pts, reb, ast, blk, fg3m),
                "proj_dk": round(float(r.get("proj_dk") or 0), 1),
                "dk_avg":  round(float(r.get("dk_avg")  or 0), 1),
                "pts":  round(pts,  1), "reb": round(reb, 1),
                "ast":  round(ast,  1), "stl": round(stl, 1),
                "blk":  round(blk,  1), "tov": round(tov, 1),
                "fg3m": round(fg3m, 1),
                "fg_pct": _pct(fgm, fga),
                "ft_pct": _pct(ftm, fta),
            })
    # Add ranks: overall proj rank + per-league rank
    players.sort(key=lambda p: p["proj_dk"], reverse=True)
    for i, p in enumerate(players):
        p["proj_rank"] = i + 1
    nba_players = [p for p in players if p["league"] == "NBA"]
    el_players  = [p for p in players if p["league"] == "EL"]
    for i, p in enumerate(sorted(nba_players, key=lambda x: x["proj_dk"], reverse=True)):
        p["league_rank"] = i + 1
    for i, p in enumerate(sorted(el_players, key=lambda x: x["proj_dk"], reverse=True)):
        p["league_rank"] = i + 1
    _pool_cache[league] = players
    return players

# =============================================================================
# DRAFT ROOM STATE
# =============================================================================
rooms      = {}
PICK_TIMER = 90
COUNTDOWN  = 30
WAIVER_SECS = 48 * 3600   # 48 hours in seconds

def make_code():
    while True:
        c = "".join(random.choices(string.ascii_uppercase, k=5))
        if c not in rooms:
            return c

def snake_idx(pick_num, n):
    r = pick_num // n
    p = pick_num  % n
    return p if r % 2 == 0 else (n - 1 - p)

def best_available(room):
    pool    = build_player_pool(room.get("league","nba"))
    drafted = rostered_ids(room)
    for p in pool:
        if p["id"] not in drafted:
            return p
    return None

def best_from_rankings(room, team):
    rankings = team.get("rankings", [])
    drafted  = rostered_ids(room)
    pool     = build_player_pool(room.get("league","nba"))
    for pid in rankings:
        if pid not in drafted:
            p = next((x for x in pool if x["id"] == pid), None)
            if p: return p
    return best_available(room)

def rostered_ids(room):
    """All player IDs currently on any roster OR in waiver period."""
    ids = {p["id"] for p in room["drafted"]}
    for w in room["waivers"].values():
        ids.add(w["player"]["id"])
    return ids

def process_pick(room_code, player_id, sid=None):
    room = rooms.get(room_code)
    if not room or room["status"] != "drafting":
        return
    pool   = build_player_pool(room.get("league","nba"))
    player = next((p for p in pool if p["id"] == player_id), None)
    if not player: return
    if player_id in rostered_ids(room): return
    n        = len(room["teams"])
    pick_num = room["pick_num"]
    tidx     = snake_idx(pick_num, n)
    team     = room["teams"][tidx]
    entry    = {
        "pick": pick_num+1, "round": pick_num//n+1,
        "team": team["name"], "team_sid": team["sid"],
        "player": player, "auto": sid is None,
    }
    room["drafted"].append(player)
    room["log"].append(entry)
    team["roster"].append(player)
    room["pick_num"] += 1
    total = n * room["rounds"]
    if room["pick_num"] >= total:
        room["status"] = "complete"
        socketio.emit("draft_complete", {"log": room["log"]}, room=room_code)
    else:
        nidx  = snake_idx(room["pick_num"], n)
        nteam = room["teams"][nidx]
        socketio.emit("pick_made", {
            "entry":     entry,
            "pick_num":  room["pick_num"],
            "next_team": nteam["name"],
            "next_sid":  nteam["sid"],
        }, room=room_code)
        start_pick_timer(room_code)

def start_pick_timer(room_code):
    pick_snap = rooms[room_code]["pick_num"]
    def _t():
        gevent.sleep(PICK_TIMER)
        r = rooms.get(room_code)
        if r and r["status"] == "drafting" and r["pick_num"] == pick_snap:
            n    = len(r["teams"])
            tidx = snake_idx(r["pick_num"], n)
            team = r["teams"][tidx]
            p    = best_from_rankings(r, team)
            if p: process_pick(room_code, p["id"])
    gevent.spawn(_t)

def run_countdown(room_code):
    room = rooms.get(room_code)
    if not room: return
    room["status"] = "countdown"
    for i in range(COUNTDOWN, 0, -1):
        r = rooms.get(room_code)
        if not r or r["status"] != "countdown": return
        socketio.emit("countdown", {"seconds": i}, room=room_code)
        gevent.sleep(1)
    r = rooms.get(room_code)
    if r and r["status"] == "countdown":
        _start_draft(room_code)

def _start_draft(room_code):
    room = rooms.get(room_code)
    if not room: return
    room["status"]     = "drafting"
    room["pick_num"]   = 0
    room["week_start"] = time.time()
    room["slots"]      = get_slots(room["rounds"])
    generate_matchups(room)
    n     = len(room["teams"])
    first = room["teams"][snake_idx(0, n)]
    socketio.emit("draft_started", {
        "teams":      [{"name":t["name"],"manager":t["manager"],"sid":t["sid"],
                        "auction_budget":t.get("auction_budget",200),
                        "auction_spent":t.get("auction_spent",0)}
                       for t in room["teams"]],
        "rounds":     room["rounds"],
        "league":     room["league"],
        "draft_type": room.get("draft_type","snake"),
        "bid_timer":  room.get("bid_timer",30),
        "next_team":  first["name"],
        "next_sid":   first["sid"],
    }, room=room_code)
    if room.get("draft_type") == "auction":
        start_nomination_phase(room_code)
    else:
        start_pick_timer(room_code)

def room_state(room):
    return {
        "code":       room["code"],
        "is_public":  room["is_public"],
        "max_teams":  room["max_teams"],
        "rounds":     room["rounds"],
        "league":     room["league"],
        "format":     room.get("format","points"),
        "draft_type": room.get("draft_type","snake"),
        "bid_timer":  room.get("bid_timer",30),
        "status":     room["status"],
        "pick_num":   room["pick_num"],
        "current_week": room.get("current_week",1),
        "teams":      [{"name":t["name"],"manager":t["manager"],
                        "roster_count":len(t["roster"]),"sid":t["sid"],
                        "auction_budget": t.get("auction_budget",200),
                        "auction_spent":  t.get("auction_spent",0)}
                       for t in room["teams"]],
        "log":        room["log"],
        "slots":      room.get("slots") or get_slots(room.get("rounds",10)),
    }

# =============================================================================
# WAIVER WIRE HELPERS
# =============================================================================
def waiver_state(room):
    """Return the full waiver wire state for a room."""
    now = time.time()
    pool = build_player_pool(room.get("league","nba"))
    pool_map = {p["id"]: p for p in pool}

    # Current waivers (players dropped, still in 48hr window)
    waivers = []
    for pid, w in room["waivers"].items():
        expires = w["dropped_at"] + WAIVER_SECS
        remaining = max(0, expires - now)
        bids = w.get("bids", {})
        waivers.append({
            "player":       w["player"],
            "dropped_by":   w["dropped_by"],
            "dropped_at":   w["dropped_at"],
            "expires_at":   expires,
            "remaining_secs": int(remaining),
            "bid_count":    len(bids),
        })
    waivers.sort(key=lambda x: x["expires_at"])

    # Free agents: in pool, not rostered, not on waivers
    rostered = rostered_ids(room)
    free_agents = [p for p in pool if p["id"] not in rostered]

    # Team FAAB and priority
    teams_info = [
        {
            "name":     t["name"],
            "manager":  t["manager"],
            "sid":      t["sid"],
            "faab":     t.get("faab", 100),
            "priority": t.get("waiver_priority", i+1),
            "roster":   t["roster"],
        }
        for i, t in enumerate(
            sorted(room["teams"], key=lambda t: t.get("waiver_priority", 999))
        )
    ]

    return {
        "code":        room["code"],
        "league":      room["league"],
        "waivers":     waivers,
        "free_agents": free_agents,
        "teams":       teams_info,
    }

def process_waiver_expiry(room_code, player_id):
    """Called when a player's waiver period expires. Awards to highest bidder."""
    room = rooms.get(room_code)
    if not room: return
    w = room["waivers"].get(player_id)
    if not w: return

    bids = w.get("bids", {})   # {team_sid: amount}

    if not bids:
        # No bids — player becomes a free agent (remove from waivers)
        del room["waivers"][player_id]
        socketio.emit("waiver_resolved", {
            "player":  w["player"],
            "winner":  None,
            "bid":     0,
            "reason":  "no_bids",
        }, room=room_code)
        return

    # Find highest bid; tie-break by waiver priority (lower = better)
    priority_map = {t["sid"]: t.get("waiver_priority", 999)
                    for t in room["teams"]}
    best_sid = max(
        bids,
        key=lambda sid: (bids[sid], -priority_map.get(sid, 999))
    )
    best_bid = bids[best_sid]
    winner   = next((t for t in room["teams"] if t["sid"] == best_sid), None)
    if not winner:
        del room["waivers"][player_id]
        return

    # Deduct FAAB
    winner["faab"] = max(0, winner.get("faab", 100) - best_bid)

    # Add to winner's roster
    winner["roster"].append(w["player"])
    room["drafted"].append(w["player"])

    # Drop winner to last waiver priority
    max_pri = max((t.get("waiver_priority",1) for t in room["teams"]), default=1)
    winner["waiver_priority"] = max_pri + 1

    # Re-normalize priorities
    sorted_teams = sorted(room["teams"], key=lambda t: t.get("waiver_priority",999))
    for i, t in enumerate(sorted_teams):
        t["waiver_priority"] = i + 1

    # Remove from waivers
    del room["waivers"][player_id]

    # Log it
    room["waiver_log"].append({
        "player":    w["player"],
        "winner":    winner["name"],
        "winner_sid":winner["sid"],
        "bid":       best_bid,
        "resolved_at": time.time(),
    })

    socketio.emit("waiver_resolved", {
        "player":    w["player"],
        "winner":    winner["name"],
        "winner_sid":winner["sid"],
        "bid":       best_bid,
        "reason":    "bid_won",
        "faab_left": winner["faab"],
    }, room=room_code)

def schedule_waiver_expiry(room_code, player_id, delay_secs):
    def _run():
        gevent.sleep(delay_secs)
        process_waiver_expiry(room_code, player_id)
    gevent.spawn(_run)

# =============================================================================
# MATCHUP & SCORING HELPERS
# =============================================================================

# Yahoo points scoring weights
YAHOO_WEIGHTS = {
    "pts": 1.0, "reb": 1.2, "ast": 1.5,
    "stl": 3.0, "blk": 3.0, "fg3m": 1.0, "tov": -1.0,
}
CATS = ["pts","reb","ast","stl","blk","fg3m","fg_pct","ft_pct","tov"]

# =============================================================================
# ROSTER SLOT CONFIGURATION
# =============================================================================

ROSTER_SLOTS = {
    6:  ["PG","SG","SF","PF","C","UTIL"],
    8:  ["PG","SG","G","SF","PF","F","C","C"],
    10: ["PG","SG","G","SF","PF","F","C","C","UTIL","UTIL"],
    13: ["PG","SG","G","SF","PF","F","C","C","UTIL","UTIL","BN","BN","BN"],
    15: ["PG","SG","G","SF","PF","F","C","C","UTIL","UTIL","BN","BN","BN","BN","BN"],
}

# Which positions can fill each slot type
SLOT_ELIGIBILITY = {
    "PG":   ["PG"],
    "SG":   ["SG"],
    "G":    ["PG","SG"],
    "SF":   ["SF"],
    "PF":   ["PF"],
    "F":    ["SF","PF"],
    "C":    ["C"],
    "UTIL": ["PG","SG","SF","PF","C","G","F"],
    "BN":   ["PG","SG","SF","PF","C","G","F"],
}

def get_slots(rounds):
    """Return the slot list for a given number of rounds."""
    # Find closest defined config at or below rounds
    defined = sorted(ROSTER_SLOTS.keys())
    best = defined[0]
    for r in defined:
        if r <= rounds:
            best = r
    return ROSTER_SLOTS[best]

def fill_lineup(roster, rounds):
    """
    Optimally assign players to roster slots.
    Returns list of {slot, player|None} in slot order.
    Priority: specific slots first (PG,SG,SF,PF,C), then G,F, then UTIL, then BN.
    """
    slots    = get_slots(rounds)
    used     = [False] * len(roster)
    assigned = [None]  * len(slots)

    def infer_pos(p):
        return p.get("pos") or _infer_pos_from_stats(p)

    def _infer_pos_from_stats(p):
        ast_  = float(p.get("ast",  0))
        pts_  = float(p.get("pts",  0))
        reb_  = float(p.get("reb",  0))
        blk_  = float(p.get("blk",  0))
        fg3m_ = float(p.get("fg3m", 0))
        if ast_ >= 5.0 and pts_ >= 10:  return "PG"
        if fg3m_ >= 1.5 and pts_ >= 12: return "SG"
        if blk_ >= 1.0 and reb_ >= 7:   return "C"
        if reb_ >= 6   and blk_ >= 0.5: return "PF"
        return "SF"

    # Fill in slot priority order: specific before flex before UTIL/BN
    priority = ["PG","SG","SF","PF","C","G","F","UTIL","BN"]
    slot_indices_by_priority = sorted(
        range(len(slots)),
        key=lambda i: priority.index(slots[i]) if slots[i] in priority else 99
    )

    for si in slot_indices_by_priority:
        slot    = slots[si]
        eligible = SLOT_ELIGIBILITY.get(slot, [])
        # Find best available player for this slot (highest proj_dk)
        best_pi   = None
        best_proj = -1
        for pi, p in enumerate(roster):
            if used[pi]: continue
            pos = infer_pos(p)
            if pos in eligible:
                proj = float(p.get("proj_dk", 0))
                if proj > best_proj:
                    best_proj = proj
                    best_pi   = pi
        if best_pi is not None:
            assigned[si] = roster[best_pi]
            used[best_pi] = True

    return [{"slot": slots[i], "player": assigned[i]} for i in range(len(slots))]

def team_totals_lineup(roster, rounds):
    """
    Compute team totals using only players in active (non-BN) slots.
    BN players don't count toward matchup scores.
    """
    slots_config = get_slots(rounds)
    lineup       = fill_lineup(roster, rounds)
    active       = [
        entry["player"]
        for entry in lineup
        if entry["player"] and entry["slot"] != "BN"
    ]
    # Use same pool-based stat lookup as team_totals
    totals = {s: 0.0 for s in CATS}
    fgm = fga = ftm = fta = 0.0
    for p in active:
        pool  = build_player_pool(p.get("league","nba").lower())
        match = next((x for x in pool if x["id"] == p["id"]), None)
        if not match: continue
        for s in ["pts","reb","ast","stl","blk","fg3m","tov"]:
            totals[s] += match.get(s, 0.0)
        fgm += match.get("fg_pct", 0.0) * match.get("fga", 10.0)
        fga += match.get("fga", 10.0)
        ftm += match.get("ft_pct", 0.0) * match.get("fta", 4.0)
        fta += match.get("fta", 4.0)
    totals["fg_pct"] = round(fgm / fga, 3) if fga > 0 else 0.0
    totals["ft_pct"] = round(ftm / fta, 3) if fta > 0 else 0.0
    return {k: round(v, 2) for k, v in totals.items()}


def player_stats(p):
    """Return stats dict for a player from pool data."""
    pool = build_player_pool(p.get("league","nba").lower())
    match = next((x for x in pool if x["id"] == p["id"]), None)
    if not match:
        return {s: 0.0 for s in CATS}
    return {s: match.get(s, 0.0) for s in CATS}

def team_totals(roster, stat_source="proj"):
    """Aggregate stats across a team's roster.
    stat_source: "proj" = use projected stats from pool
    Returns totals dict + fg_pct and ft_pct computed from makes/attempts.
    """
    totals = {s: 0.0 for s in CATS}
    fgm = fga = ftm = fta = 0.0
    for p in roster:
        pool = build_player_pool(p.get("league","nba").lower())
        match = next((x for x in pool if x["id"] == p["id"]), None)
        if not match:
            continue
        for s in ["pts","reb","ast","stl","blk","fg3m","tov"]:
            totals[s] += match.get(s, 0.0)
        fgm += match.get("fg_pct", 0.0) * match.get("fga", 10.0)
        fga += match.get("fga", 10.0)
        ftm += match.get("ft_pct", 0.0) * match.get("fta", 4.0)
        fta += match.get("fta", 4.0)
    totals["fg_pct"] = round(fgm / fga, 3) if fga > 0 else 0.0
    totals["ft_pct"] = round(ftm / fta, 3) if fta > 0 else 0.0
    return {k: round(v, 2) for k, v in totals.items()}

def yahoo_score(totals):
    score = 0.0
    for stat, weight in YAHOO_WEIGHTS.items():
        score += totals.get(stat, 0.0) * weight
    return round(score, 2)

def generate_matchups(room):
    """Generate a round-robin schedule for the season (up to 20 weeks)."""
    teams = [t["sid"] for t in room["teams"]]
    n = len(teams)
    if n < 2:
        return
    # Add bye if odd number
    if n % 2 == 1:
        teams.append("BYE")
    half = len(teams) // 2
    schedule = {}
    for week in range(1, 21):
        pairs = []
        for i in range(half):
            home = teams[i]
            away = teams[len(teams)-1-i]
            if home != "BYE" and away != "BYE":
                pairs.append({"home_sid": home, "away_sid": away})
        schedule[str(week)] = pairs
        # Rotate (keep teams[0] fixed, rotate the rest)
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]
    room["matchups"] = schedule

def matchup_result(room, week=None):
    """Return matchup data for a given week (default: current week)."""
    if week is None:
        week = room.get("current_week", 1)
    pairs = room["matchups"].get(str(week), [])
    fmt   = room.get("format", "points")
    result = []
    for pair in pairs:
        home_team = next((t for t in room["teams"] if t["sid"]==pair["home_sid"]), None)
        away_team = next((t for t in room["teams"] if t["sid"]==pair["away_sid"]), None)
        if not home_team or not away_team:
            continue
        rounds   = room.get("rounds", 10)
        home_tot = team_totals_lineup(home_team["roster"], rounds)
        away_tot = team_totals_lineup(away_team["roster"], rounds)
        if fmt == "points":
            home_score = yahoo_score(home_tot)
            away_score = yahoo_score(away_tot)
            winner = "home" if home_score > away_score else "away" if away_score > home_score else "tie"
            result.append({
                "home": {"name": home_team["name"], "sid": home_team["sid"],
                         "score": home_score, "totals": home_tot,
                         "roster": home_team["roster"],
                         "lineup": fill_lineup(home_team["roster"], room.get("rounds",10))},
                "away": {"name": away_team["name"], "sid": away_team["sid"],
                         "score": away_score, "totals": away_tot,
                         "roster": away_team["roster"],
                         "lineup": fill_lineup(away_team["roster"], room.get("rounds",10))},
                "winner": winner, "format": "points",
            })
        else:
            # Categories: compare each cat, count wins
            cat_results = {}
            home_wins = away_wins = ties = 0
            for cat in CATS:
                hv = home_tot.get(cat, 0.0)
                av = away_tot.get(cat, 0.0)
                # TOV: lower is better
                if cat == "tov":
                    if hv < av:   w = "home"
                    elif av < hv: w = "away"
                    else:         w = "tie"
                else:
                    if hv > av:   w = "home"
                    elif av > hv: w = "away"
                    else:         w = "tie"
                cat_results[cat] = {"home": hv, "away": av, "winner": w}
                if w == "home":   home_wins += 1
                elif w == "away": away_wins += 1
                else:             ties += 1
            winner = "home" if home_wins > away_wins else "away" if away_wins > home_wins else "tie"
            result.append({
                "home": {"name": home_team["name"], "sid": home_team["sid"],
                         "wins": home_wins, "roster": home_team["roster"],
                         "lineup": fill_lineup(home_team["roster"], room.get("rounds",10))},
                "away": {"name": away_team["name"], "sid": away_team["sid"],
                         "wins": away_wins, "roster": away_team["roster"],
                         "lineup": fill_lineup(away_team["roster"], room.get("rounds",10))},
                "categories": cat_results,
                "ties": ties, "winner": winner, "format": "categories",
            })
    return result

def standings(room):
    """Compute W/L/T record and points scored for each team."""
    fmt = room.get("format","points")
    records = {t["sid"]: {"name":t["name"],"manager":t["manager"],
                           "wins":0,"losses":0,"ties":0,"pts_for":0.0,"pts_against":0.0,
                           "cats_won":0,"cats_lost":0}
               for t in room["teams"]}
    for week_str, pairs in room["matchups"].items():
        week = int(week_str)
        if week >= room.get("current_week",1):
            break   # only count completed weeks
        for pair in pairs:
            hsid = pair["home_sid"]; asid = pair["away_sid"]
            if hsid not in records or asid not in records:
                continue
            hteam = next((t for t in room["teams"] if t["sid"]==hsid), None)
            ateam = next((t for t in room["teams"] if t["sid"]==asid), None)
            if not hteam or not ateam: continue
            htot = team_totals(hteam["roster"])
            atot = team_totals(ateam["roster"])
            if fmt == "points":
                hs = yahoo_score(htot); as_ = yahoo_score(atot)
                records[hsid]["pts_for"]     += hs
                records[hsid]["pts_against"] += as_
                records[asid]["pts_for"]     += as_
                records[asid]["pts_against"] += hs
                if hs > as_:
                    records[hsid]["wins"] += 1; records[asid]["losses"] += 1
                elif as_ > hs:
                    records[asid]["wins"] += 1; records[hsid]["losses"] += 1
                else:
                    records[hsid]["ties"] += 1; records[asid]["ties"] += 1
            else:
                hw = aw = 0
                for cat in CATS:
                    hv = htot.get(cat,0); av = atot.get(cat,0)
                    if cat == "tov":
                        if hv < av: hw += 1
                        elif av < hv: aw += 1
                    else:
                        if hv > av: hw += 1
                        elif av > hv: aw += 1
                records[hsid]["cats_won"]  += hw; records[hsid]["cats_lost"] += aw
                records[asid]["cats_won"]  += aw; records[asid]["cats_lost"] += hw
                if hw > aw:   records[hsid]["wins"]+=1; records[asid]["losses"]+=1
                elif aw > hw: records[asid]["wins"]+=1; records[hsid]["losses"]+=1
                else:         records[hsid]["ties"]+=1; records[asid]["ties"]+=1
    result = sorted(records.values(), key=lambda r: (-r["wins"], -r.get("pts_for",0)))
    for i, r in enumerate(result):
        r["rank"] = i + 1
        r["pts_for"]     = round(r["pts_for"],     1)
        r["pts_against"] = round(r["pts_against"],  1)
    return result

# =============================================================================
# REST ROUTES — PROJECTIONS
# =============================================================================
@app.route("/players")
def players():
    return jsonify(get_projections().merge(get_season_avgs(),on="name",how="left").to_dict("records"))

@app.route("/player/<name>")
def player(name):
    avgs = get_season_avgs()
    pa   = avgs[avgs["name"].str.lower()==name.lower()]
    if pa.empty: return jsonify({"error":"Player not found"}),404
    proj = get_projections()
    pp   = proj[proj["name"].str.lower()==name.lower()]
    proj_dk = float(pp["proj_dk"].values[0]) if not pp.empty else None
    team    = str(pp["team"].values[0]) if not pp.empty else "—"
    games = (df[df["PLAYER_NAME"].str.lower()==name.lower()]
             .sort_values("GAME_DATE").tail(10)
             [["GAME_DATE","OPP","HOME","MIN","PTS","REB","AST","STL","BLK","TOV","DK_PTS","DAYS_REST"]])
    games["GAME_DATE"] = games["GAME_DATE"].dt.strftime("%Y-%m-%d")
    return jsonify({"name":name,"team":team,"proj_dk":proj_dk,
                    "season":pa.to_dict("records")[0],"last10":games.to_dict("records")})

@app.route("/top")
def top():
    limit = int(request.args.get("limit",30))
    m = get_projections().merge(get_season_avgs(),on="name",how="left")
    return jsonify(m.sort_values("proj_dk",ascending=False).head(limit).to_dict("records"))

@app.route("/matchups")
def matchups():
    opp = (df.groupby("OPP")["DK_PTS"].agg(["mean","count"]).reset_index()
           .rename(columns={"mean":"avg_dk_allowed","count":"games"})
           .sort_values("avg_dk_allowed",ascending=False).round(2))
    return jsonify(opp.to_dict("records"))

@app.route("/euroleague/players")
def el_players():
    if el_df is None: return jsonify({"error":"EL data not loaded"}),503
    return jsonify(get_el_projections().merge(get_el_season_avgs(),on="name",how="left").to_dict("records"))

@app.route("/euroleague/player/<name>")
def el_player(name):
    if el_df is None: return jsonify({"error":"EL data not loaded"}),503
    avgs = get_el_season_avgs()
    pa   = avgs[avgs["name"].str.lower()==name.lower()]
    if pa.empty: return jsonify({"error":"Player not found"}),404
    proj = get_el_projections()
    pp   = proj[proj["name"].str.lower()==name.lower()]
    proj_dk = float(pp["proj_dk"].values[0]) if not pp.empty else None
    gc = ["GAME_DATE","OPP","HOME","MIN","PTS","REB","AST","STL","BLK","TOV","DK_PTS","PIR","DAYS_REST"]
    gc = [c for c in gc if c in el_df.columns]
    games = (el_df[el_df["PLAYER_NAME"].str.lower()==name.lower()]
             .sort_values("GAME_DATE").tail(10)[gc].copy())
    games["GAME_DATE"] = games["GAME_DATE"].dt.strftime("%Y-%m-%d")
    return jsonify({"name":name,"league":"euroleague","proj_dk":proj_dk,
                    "season":pa.to_dict("records")[0],"last10":games.to_dict("records")})

@app.route("/euroleague/top")
def el_top():
    if el_df is None: return jsonify({"error":"EL data not loaded"}),503
    limit = int(request.args.get("limit",30))
    m = get_el_projections().merge(get_el_season_avgs(),on="name",how="left")
    return jsonify(m.sort_values("proj_dk",ascending=False).head(limit).to_dict("records"))

@app.route("/euroleague/matchups")
def el_matchups():
    if el_df is None: return jsonify({"error":"EL data not loaded"}),503
    opp = (el_df.groupby("OPP")["DK_PTS"].agg(["mean","count"]).reset_index()
           .rename(columns={"mean":"avg_dk_allowed","count":"games"})
           .sort_values("avg_dk_allowed",ascending=False).round(2))
    return jsonify(opp.to_dict("records"))

@app.route("/draft/pool")
def draft_pool():
    league = request.args.get("league","nba").lower()
    if league not in ("nba","el"): league = "nba"
    return jsonify(build_player_pool(league))

# =============================================================================
# REST ROUTES — WAIVER WIRE
# =============================================================================
@app.route("/room/<code>/waivers")
def get_waivers(code):
    room = rooms.get(code.upper())
    if not room: return jsonify({"error":"Room not found"}), 404
    return jsonify(waiver_state(room))

@app.route("/health")
def health():
    return jsonify({
        "status":"ok",
        "nba":{"players":int(df["PLAYER_NAME"].nunique()),"records":len(df)},
        "euroleague":{"loaded":el_df is not None,
                      "players":int(el_df["PLAYER_NAME"].nunique()) if el_df is not None else 0,
                      "records":len(el_df) if el_df is not None else 0},
        "active_rooms":len(rooms),
    })
@app.route("/room/<code>/matchup")
def get_matchup(code):
    room = rooms.get(code.upper())
    if not room: return jsonify({"error":"Room not found"}),404
    week = request.args.get("week", None)
    week = int(week) if week else None
    return jsonify({
        "week":     week or room.get("current_week",1),
        "total_weeks": len(room["matchups"]),
        "format":   room.get("format","points"),
        "matchups": matchup_result(room, week),
    })

@app.route("/room/<code>/standings")
def get_standings(code):
    room = rooms.get(code.upper())
    if not room: return jsonify({"error":"Room not found"}),404
    return jsonify({
        "format":    room.get("format","points"),
        "week":      room.get("current_week",1),
        "standings": standings(room),
    })

@app.route("/room/<code>/info")
def get_room_info(code):
    room = rooms.get(code.upper())
    if not room: return jsonify({"error":"Room not found"}),404
    return jsonify({
        "code":    room["code"],
        "league":  room["league"],
        "format":  room.get("format","points"),
        "rounds":  room["rounds"],
        "status":  room["status"],
        "current_week": room.get("current_week",1),
        "teams":   [{"name":t["name"],"manager":t["manager"],"sid":t["sid"],
                     "roster_count":len(t["roster"])} for t in room["teams"]],
    })


# =============================================================================
# AUCTION DRAFT HELPERS
# =============================================================================

def auction_max_bid(team, room):
    """Max a team can bid: budget - $1 per remaining roster spot (excluding current)."""
    roster_size   = len(team["roster"])
    spots_left    = room["rounds"] - roster_size - 1  # -1 for the player being bid on
    spots_left    = max(0, spots_left)
    budget_left   = team.get("auction_budget", 200) - team.get("auction_spent", 0)
    return max(1, budget_left - spots_left)

def nom_team(room):
    """Return the team whose turn it is to nominate."""
    n   = len(room["teams"])
    idx = room["auction"]["nom_idx"] % n
    return room["teams"][idx]

def auction_state_payload(room):
    """Full auction state for broadcast."""
    auc = room["auction"]
    nom = auc.get("nomination")
    remaining = 0
    if auc["timer_snap"] and auc["status"] == "bidding":
        elapsed   = time.time() - auc["timer_snap"]
        remaining = max(0, room.get("bid_timer", 30) - elapsed)
    return {
        "status":         auc["status"],
        "nomination":     nom,
        "high_bid":       auc["high_bid"],
        "high_team":      auc["high_team"],
        "high_sid":       auc["high_sid"],
        "bids":           {sid: amt for sid, amt in auc["bids"].items()},
        "timer_remaining": round(remaining, 1),
        "nom_idx":        auc["nom_idx"],
        "nom_team":       nom_team(room)["name"] if room["teams"] else "",
        "nom_sid":        nom_team(room)["sid"]  if room["teams"] else "",
        "teams": [{
            "name":   t["name"], "sid": t["sid"],
            "budget": t.get("auction_budget", 200),
            "spent":  t.get("auction_spent", 0),
            "roster": t["roster"],
        } for t in room["teams"]],
        "log":    room["log"],
        "pick_num": room["pick_num"],
        "rounds": room["rounds"],
    }

def start_nomination_phase(room_code):
    """Move auction to nominating state — prompt the next team to nominate."""
    room = rooms.get(room_code)
    if not room or room["status"] != "drafting": return
    total_picks = len(room["teams"]) * room["rounds"]
    if room["pick_num"] >= total_picks:
        finish_auction(room_code)
        return
    auc = room["auction"]
    auc["status"]     = "nominating"
    auc["nomination"] = None
    auc["bids"]       = {}
    auc["high_bid"]   = 0
    auc["high_sid"]   = None
    auc["high_team"]  = None
    auc["timer_snap"] = None
    nt = nom_team(room)
    socketio.emit("auction_nominate", {
        "nom_team": nt["name"],
        "nom_sid":  nt["sid"],
        "state":    auction_state_payload(room),
    }, room=room_code)
    # Auto-nominate after 30s if team doesn't act
    snap = room["pick_num"]
    def _auto_nom():
        gevent.sleep(30)
        r = rooms.get(room_code)
        if not r or r["pick_num"] != snap: return
        if r["auction"]["status"] != "nominating": return
        pool = build_player_pool(r.get("league","nba"))
        drafted = {p["id"] for p in r["drafted"]}
        player  = next((p for p in pool if p["id"] not in drafted), None)
        if player:
            _do_nominate(room_code, nt["sid"], player["id"])
    gevent.spawn(_auto_nom)

def _do_nominate(room_code, sid, player_id):
    """Execute a nomination — start the bidding clock."""
    room = rooms.get(room_code)
    if not room or room["auction"]["status"] != "nominating": return
    pool   = build_player_pool(room.get("league","nba"))
    player = next((p for p in pool if p["id"] == player_id), None)
    if not player: return
    if player_id in {p["id"] for p in room["drafted"]}: return
    team = next((t for t in room["teams"] if t["sid"] == sid), None)
    if not team: return
    auc = room["auction"]
    auc["status"]     = "bidding"
    auc["nomination"] = player
    auc["bids"]       = {sid: 1}   # nominating team auto-bids $1
    auc["high_bid"]   = 1
    auc["high_sid"]   = sid
    auc["high_team"]  = team["name"]
    auc["timer_snap"] = time.time()
    socketio.emit("auction_bid_update", auction_state_payload(room), room=room_code)
    _schedule_auction_timer(room_code, room.get("bid_timer", 30))

def _schedule_auction_timer(room_code, duration):
    """Schedule auction resolution after duration seconds."""
    snap_time = rooms[room_code]["auction"]["timer_snap"]
    def _run():
        gevent.sleep(duration + 0.5)
        r = rooms.get(room_code)
        if not r or r["auction"]["status"] != "bidding": return
        if r["auction"]["timer_snap"] != snap_time: return  # timer was reset
        _resolve_auction(room_code)
    gevent.spawn(_run)

def _resolve_auction(room_code):
    """Award player to highest bidder."""
    room = rooms.get(room_code)
    if not room or room["auction"]["status"] != "bidding": return
    auc    = room["auction"]
    player = auc["nomination"]
    if not player: return
    winner_sid  = auc["high_sid"]
    winner_team = next((t for t in room["teams"] if t["sid"] == winner_sid), None)
    if not winner_team: return
    winning_bid = auc["high_bid"]
    # Add to winner's roster
    winner_team["roster"].append(player)
    winner_team["auction_spent"] = winner_team.get("auction_spent", 0) + winning_bid
    room["drafted"].append(player)
    entry = {
        "pick":       room["pick_num"] + 1,
        "team":       winner_team["name"],
        "team_sid":   winner_team["sid"],
        "player":     player,
        "price":      winning_bid,
        "draft_type": "auction",
    }
    room["log"].append(entry)
    room["pick_num"] += 1
    # Advance nomination rotation
    auc["nom_idx"] += 1
    auc["status"]   = "idle"
    socketio.emit("auction_won", {
        "entry":  entry,
        "winner": winner_team["name"],
        "price":  winning_bid,
        "state":  auction_state_payload(room),
    }, room=room_code)
    # Check if draft complete
    total = len(room["teams"]) * room["rounds"]
    if room["pick_num"] >= total:
        finish_auction(room_code)
    else:
        gevent.sleep(2)
        start_nomination_phase(room_code)

def finish_auction(room_code):
    room = rooms.get(room_code)
    if not room: return
    room["status"] = "complete"
    socketio.emit("draft_complete", {"log": room["log"]}, room=room_code)

# =============================================================================
# WEBSOCKET — DRAFT
# =============================================================================
@socketio.on("connect")
def on_connect():
    emit("connected", {"sid": request.sid})

@socketio.on("create_room")
def on_create_room(data):
    code   = make_code()
    league = data.get("league","nba").lower()
    if league not in ("nba","el"): league = "nba"
    fmt = data.get("format","points")
    if fmt not in ("points","categories"): fmt = "points"
    draft_type = data.get("draft_type","snake")
    if draft_type not in ("snake","auction"): draft_type = "snake"
    bid_timer  = max(10, min(60, int(data.get("bid_timer", 30))))
    room = {
        "code":        code,
        "is_public":   bool(data.get("is_public",False)),
        "max_teams":   min(int(data.get("max_teams",8)),20),
        "rounds":      max(1,int(data.get("rounds",10))),
        "league":      league,
        "format":      fmt,
        "draft_type":  draft_type,
        "bid_timer":   bid_timer,
        "slots":       None,   # set when draft starts (depends on final rounds)
        "status":      "waiting",
        "teams":       [],
        "drafted":     [],
        "log":         [],
        "pick_num":    0,
        # Auction state
        "auction": {
            "status":      "idle",     # idle | nominating | bidding
            "nomination":  None,       # {player, nominated_by_sid, nominated_by}
            "bids":        {},         # sid -> amount
            "high_bid":    0,
            "high_sid":    None,
            "high_team":   None,
            "nom_idx":     0,          # which team nominates next
            "timer_snap":  None,       # timestamp when current timer started
        },
        "waivers":     {},
        "waiver_log":  [],
        "current_week": 1,
        "matchups":    {},
        "week_start":  None,
    }
    rooms[code] = room
    team = {
        "sid":             request.sid,
        "name":            data.get("team_name","Team 1"),
        "manager":         data.get("manager_name","Manager"),
        "roster":          [],
        "rankings":        [],
        "faab":            100,
        "waiver_priority": 1,
        "auction_budget":  200,   # $200 for auction draft
        "auction_spent":   0,
    }
    room["teams"].append(team)
    join_room(code)
    emit("room_created", {"code":code,"room":room_state(room),"your_sid":request.sid})

@socketio.on("join_room_draft")
def on_join_room(data):
    code = data.get("code","").upper().strip()
    room = rooms.get(code)
    if not room:
        emit("error",{"msg":f"Room '{code}' not found."}); return
    if room["status"] not in ("waiting","countdown","drafting","complete"):
        emit("error",{"msg":"Room not found."}); return

    manager = data.get("manager_name","Manager")
    tname   = data.get("team_name","Team")

    # Rejoin: find existing team by name match and update SID
    existing = next((t for t in room["teams"]
                     if t["name"]==tname and t["manager"]==manager), None)
    if existing:
        existing["sid"] = request.sid
        join_room(code)
        emit("joined_ok", {"room":room_state(room),"your_sid":request.sid})
        socketio.emit("team_rejoined",{
            "team":{"name":existing["name"],"manager":existing["manager"],"sid":existing["sid"]},
            "room":room_state(room),
        }, room=code)
        return

    if room["status"] != "waiting":
        emit("error",{"msg":"Draft already started — use your original team name to rejoin."}); return
    if len(room["teams"]) >= room["max_teams"]:
        emit("error",{"msg":"Room is full."}); return

    n_teams = len(room["teams"]) + 1
    team = {
        "sid":             request.sid,
        "name":            tname,
        "manager":         manager,
        "roster":          [],
        "rankings":        [],
        "faab":            100,
        "waiver_priority": n_teams,
    }
    room["teams"].append(team)
    join_room(code)
    socketio.emit("team_joined",{
        "team":{"name":team["name"],"manager":team["manager"],"sid":team["sid"]},
        "room":room_state(room),
    }, room=code)
    emit("joined_ok",{"room":room_state(room),"your_sid":request.sid})
    if len(room["teams"]) == room["max_teams"]:
        gevent.spawn(run_countdown, code)

@socketio.on("join_public_lobby")
def on_join_public(data):
    available = [r for r in rooms.values()
                 if r["is_public"] and r["status"]=="waiting"
                 and len(r["teams"]) < r["max_teams"]]
    if available:
        data["code"] = available[0]["code"]
        on_join_room(data)
    else:
        data["is_public"] = True
        on_create_room(data)

@socketio.on("start_now")
def on_start_now(data):
    code = data.get("code"); room = rooms.get(code)
    if room and room["teams"] and room["teams"][0]["sid"]==request.sid:
        if room["status"] in ("waiting","countdown"):
            room["status"] = "waiting"
            gevent.spawn(run_countdown, code)

@socketio.on("make_pick")
def on_make_pick(data):
    code = data.get("code"); room = rooms.get(code)
    if not room or room["status"]!="drafting":
        emit("error",{"msg":"Not currently drafting."}); return
    n    = len(room["teams"])
    tidx = snake_idx(room["pick_num"],n)
    if room["teams"][tidx]["sid"] != request.sid:
        emit("error",{"msg":"Not your pick."}); return
    process_pick(code, data.get("player_id"), sid=request.sid)

@socketio.on("set_rankings")
def on_set_rankings(data):
    code = data.get("code"); room = rooms.get(code)
    if not room: return
    for t in room["teams"]:
        if t["sid"]==request.sid:
            t["rankings"] = data.get("rankings",[])
            emit("rankings_saved",{"count":len(t["rankings"])}); return

@socketio.on("get_room_state")
def on_get_state(data):
    code = data.get("code"); room = rooms.get(code)
    if room:
        join_room(code)
        emit("room_state", room_state(room))
    else:
        emit("error",{"msg":"Room not found."})

@socketio.on("nominate_player")
def on_nominate_player(data):
    """Team nominates a player to be auctioned."""
    code = data.get("code","").upper()
    room = rooms.get(code)
    if not room:
        emit("error",{"msg":"Room not found."}); return
    if room.get("draft_type") != "auction":
        emit("error",{"msg":"Not an auction draft."}); return
    if room["auction"]["status"] != "nominating":
        emit("error",{"msg":"Not nomination phase."}); return
    nt = nom_team(room)
    if nt["sid"] != request.sid:
        emit("error",{"msg":"Not your turn to nominate."}); return
    _do_nominate(code, request.sid, data.get("player_id"))

@socketio.on("place_bid")
def on_place_bid(data):
    """Team places or raises a bid on the current nomination."""
    code = data.get("code","").upper()
    room = rooms.get(code)
    if not room:
        emit("error",{"msg":"Room not found."}); return
    if room["auction"]["status"] != "bidding":
        emit("error",{"msg":"No active auction."}); return
    team = next((t for t in room["teams"] if t["sid"] == request.sid), None)
    if not team:
        emit("error",{"msg":"Not in this room."}); return
    auc     = room["auction"]
    amount  = int(data.get("amount", 1))
    max_bid = auction_max_bid(team, room)
    if amount > max_bid:
        emit("error",{"msg":f"Max bid is ${max_bid}."}); return
    if amount <= auc["high_bid"]:
        emit("error",{"msg":f"Bid must be above ${auc['high_bid']}."}); return
    # Place bid
    auc["bids"][request.sid] = amount
    auc["high_bid"]   = amount
    auc["high_sid"]   = request.sid
    auc["high_team"]  = team["name"]
    # Reset timer to 10 seconds
    auc["timer_snap"] = time.time()
    socketio.emit("auction_bid_update", auction_state_payload(room), room=code)
    _schedule_auction_timer(code, 10)

@socketio.on("get_auction_state")
def on_get_auction_state(data):
    """Return full auction state for a room."""
    code = data.get("code","").upper()
    room = rooms.get(code)
    if not room:
        emit("error",{"msg":"Room not found."}); return
    join_room(code)
    emit("auction_state", auction_state_payload(room))

@socketio.on("list_public_rooms")
def on_list_public(data):
    pub = [{"code":r["code"],"teams":len(r["teams"]),
            "max_teams":r["max_teams"],"rounds":r["rounds"],
            "league":r["league"],"status":r["status"]}
           for r in rooms.values() if r["is_public"]]
    emit("public_rooms",{"rooms":pub})

@socketio.on("disconnect")
def on_disconnect():
    for code,room in rooms.items():
        for t in room["teams"]:
            if t["sid"]==request.sid:
                socketio.emit("team_disconnected",{"team":t["name"]},room=code)
                return

# =============================================================================
# WEBSOCKET — WAIVER WIRE
# =============================================================================
@socketio.on("join_waiver_room")
def on_join_waiver_room(data):
    """Join the socket room for waiver updates."""
    code = data.get("code","").upper().strip()
    room = rooms.get(code)
    if not room:
        emit("error",{"msg":"Room not found."}); return
    join_room(code)
    emit("waiver_state", waiver_state(room))

@socketio.on("drop_player")
def on_drop_player(data):
    """
    Drop a player from your roster.
    data: {code, player_id}
    Player goes to 48hr waiver period.
    """
    code = data.get("code","").upper()
    room = rooms.get(code)
    if not room:
        emit("error",{"msg":"Room not found."}); return

    team = next((t for t in room["teams"] if t["sid"]==request.sid), None)
    if not team:
        emit("error",{"msg":"You are not in this room."}); return

    player_id = data.get("player_id")
    player = next((p for p in team["roster"] if p["id"]==player_id), None)
    if not player:
        emit("error",{"msg":"Player not on your roster."}); return

    # Remove from team roster and drafted list
    team["roster"] = [p for p in team["roster"] if p["id"]!=player_id]
    # Keep in room["drafted"] so draft log stays intact — just move to waivers
    now = time.time()
    room["waivers"][player_id] = {
        "player":     player,
        "dropped_by": team["name"],
        "dropped_at": now,
        "bids":       {},
    }
    # Schedule resolution in 48 hours
    schedule_waiver_expiry(code, player_id, WAIVER_SECS)

    socketio.emit("player_dropped", {
        "player":     player,
        "dropped_by": team["name"],
        "expires_in": WAIVER_SECS,
    }, room=code)
    emit("drop_ok", {"player": player})

@socketio.on("submit_waiver_bid")
def on_submit_waiver_bid(data):
    """
    Submit or update a FAAB bid on a waivered player.
    data: {code, player_id, amount}
    """
    code = data.get("code","").upper()
    room = rooms.get(code)
    if not room:
        emit("error",{"msg":"Room not found."}); return

    team = next((t for t in room["teams"] if t["sid"]==request.sid), None)
    if not team:
        emit("error",{"msg":"Not in this room."}); return

    player_id = data.get("player_id")
    w = room["waivers"].get(player_id)
    if not w:
        emit("error",{"msg":"Player not on waivers."}); return

    amount = int(data.get("amount", 0))
    amount = max(0, min(amount, team.get("faab",100)))

    w["bids"][request.sid] = amount
    emit("bid_submitted", {
        "player_id": player_id,
        "amount":    amount,
        "faab_left": team.get("faab",100),
    })

@socketio.on("claim_free_agent")
def on_claim_free_agent(data):
    """
    Instantly claim a free agent (not on waivers).
    data: {code, player_id, drop_player_id}
    Optionally drop a player at the same time.
    """
    code = data.get("code","").upper()
    room = rooms.get(code)
    if not room:
        emit("error",{"msg":"Room not found."}); return

    team = next((t for t in room["teams"] if t["sid"]==request.sid), None)
    if not team:
        emit("error",{"msg":"Not in this room."}); return

    player_id = data.get("player_id")
    if player_id in rostered_ids(room):
        emit("error",{"msg":"Player is not available."}); return

    pool   = build_player_pool(room.get("league","nba"))
    player = next((p for p in pool if p["id"]==player_id), None)
    if not player:
        emit("error",{"msg":"Player not found."}); return

    # Optionally drop a player first
    drop_id = data.get("drop_player_id")
    if drop_id:
        drop_player = next((p for p in team["roster"] if p["id"]==drop_id), None)
        if drop_player:
            team["roster"] = [p for p in team["roster"] if p["id"]!=drop_id]
            now = time.time()
            room["waivers"][drop_id] = {
                "player":     drop_player,
                "dropped_by": team["name"],
                "dropped_at": now,
                "bids":       {},
            }
            schedule_waiver_expiry(code, drop_id, WAIVER_SECS)

    # Add player to roster
    team["roster"].append(player)
    room["drafted"].append(player)
    room["waiver_log"].append({
        "player":      player,
        "winner":      team["name"],
        "winner_sid":  team["sid"],
        "bid":         0,
        "resolved_at": time.time(),
        "type":        "free_agent",
    })

    socketio.emit("free_agent_claimed", {
        "player":   player,
        "by_team":  team["name"],
        "by_sid":   team["sid"],
    }, room=code)
    emit("claim_ok", {"player": player})
