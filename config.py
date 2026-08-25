"""League settings, model parameters, and draft configuration."""

# ---------------------------------------------------------------- season
SEASON = 2026
# Seasons of *actual* results used to estimate durability and volatility.
HISTORY_SEASONS = [2025, 2024]
REGULAR_SEASON_WEEKS = 18
GAMES_PER_TEAM = 17  # 18 weeks, one bye
# Fantasy regular season vs. fantasy playoffs (championship weighting)
FANTASY_REGULAR_WEEKS = list(range(1, 15))
FANTASY_PLAYOFF_WEEKS = [15, 16, 17]

# ---------------------------------------------------------------- scoring
SCORING = {
    "pass_yds": 1 / 25,
    "pass_td": 4,
    "pass_int": -2,
    "rush_yds": 1 / 10,
    "rush_td": 6,
    "rec": 1,
    "rec_yds": 1 / 10,
    "rec_td": 5,
    "ret_yds": 1 / 25,
    "ret_td": 6,
    "two_pt": 2,
    "fum_lost": -2,
    "off_fum_td": 6,
    "fg_miss": -1,          # league gives -1 for a miss at every distance
    "pat_made": 1,
    "pat_miss": -1,
    "fg_yds": 1 / 10,
    "sack": 1,
    "dst_int": 2,
    "dst_fum_rec": 2,
    "dst_td": 6,
    "dst_safety": 2,
    "dst_block_kick": 2,
    "dst_ret_td": 6,
    "dst_pa_0": 10,
    "dst_pa_1_6": 7,
    "dst_pa_7_13": 4,
    "dst_pa_14_20": 1,
    "dst_pa_21_27": 0,
    "dst_pa_28_34": -1,
    "dst_pa_35_plus": -4,
    "dst_xp_ret": 2,
}

LINEUP = [
    ("QB", 1), ("RB", 2), ("WR", 2), ("TE", 1),
    ("FLEX", 1), ("K", 1), ("DEF", 1), ("BN", 5),
]
STARTERS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DEF": 1}
FLEX_POSITIONS = ["RB", "WR", "TE"]
BENCH_SLOTS = 5
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]

# ---------------------------------------------------------------- league
LEAGUE_TEAMS = 12
DRAFT_ROUNDS = 15
DRAFT_SNAKE = True
# None => build a plan for every slot (read your row on draft day).
DRAFT_SLOT = None

# ---------------------------------------------------------------- risk model
# Baseline per-game availability by position, before player-specific evidence.
# Derived from the historical games-played rates the pipeline measures.
POS_BASE_AVAILABILITY = {
    "QB": 0.90, "RB": 0.84, "WR": 0.87, "TE": 0.86, "K": 0.97, "DEF": 1.00,
}

# Expected games MISSED given a preseason designation, and a per-game
# efficiency multiplier for the rust/limited-snaps period after returning.
INJURY_STATUS_EFFECT = {
    "IR":           {"games_missed": 11.0, "rust": 0.85},
    "PUP":          {"games_missed": 5.0,  "rust": 0.88},
    "NA":           {"games_missed": 4.0,  "rust": 0.90},
    "Out":          {"games_missed": 3.0,  "rust": 0.92},
    "Doubtful":     {"games_missed": 1.8,  "rust": 0.95},
    "Questionable": {"games_missed": 0.8,  "rust": 0.97},
    "Sus":          {"games_missed": 3.0,  "rust": 1.00},  # suspension, not injury
    "DNR":          {"games_missed": 2.0,  "rust": 0.95},
    "COV":          {"games_missed": 1.0,  "rust": 1.00},
}

# Severity of the specific injury. Matched as substrings against
# `injury_body_part` / `injury_notes`. extra_missed is ADDED to the status
# effect; rust is multiplied in. This is the "coming off injury" correction.
INJURY_SEVERITY = {
    "acl":        {"extra_missed": 4.0, "rust": 0.80},
    "achilles":   {"extra_missed": 5.0, "rust": 0.78},
    "lisfranc":   {"extra_missed": 3.5, "rust": 0.82},
    "patellar":   {"extra_missed": 4.0, "rust": 0.82},
    "fracture":   {"extra_missed": 2.5, "rust": 0.90},
    "broken":     {"extra_missed": 2.5, "rust": 0.90},
    "surgery":    {"extra_missed": 2.0, "rust": 0.88},
    "concussion": {"extra_missed": 0.8, "rust": 0.97},
    "hamstring":  {"extra_missed": 1.2, "rust": 0.93},
    "knee":       {"extra_missed": 1.5, "rust": 0.92},
    "shoulder":   {"extra_missed": 1.0, "rust": 0.94},
    "back":       {"extra_missed": 1.2, "rust": 0.93},
    "foot":       {"extra_missed": 1.2, "rust": 0.93},
    "ankle":      {"extra_missed": 0.8, "rust": 0.95},
    "calf":       {"extra_missed": 0.8, "rust": 0.95},
    "groin":      {"extra_missed": 0.8, "rust": 0.95},
    "quad":       {"extra_missed": 0.8, "rust": 0.95},
    "hip":        {"extra_missed": 1.0, "rust": 0.94},
}

# Age at which production/availability starts declining, and the per-year
# multiplier applied past that age.
AGE_CLIFF = {"QB": 34, "RB": 27, "WR": 29, "TE": 29, "K": 38, "DEF": 99}
AGE_DECAY_PER_YEAR = {"QB": 0.030, "RB": 0.075, "WR": 0.040, "TE": 0.040,
                      "K": 0.02, "DEF": 0.0}
# How much of the age curve is charged against availability. Age is NOT charged
# against per-game production, because the projections already reflect it --
# doing both would count the same decline twice.
AGE_AVAILABILITY_PENALTY = 0.45

# Shrinkage: how many "prior games" of the positional base rate to blend into
# each player's measured durability. Higher = trust the player's own history less.
DURABILITY_PRIOR_GAMES = 20
# A season only counts toward durability if the player was a real contributor;
# otherwise "inactive backup" is confused with "injured starter".
MIN_GAMES_FOR_DURABILITY_SEASON = 5
# Shrinkage weight (in games) for per-game volatility toward the positional mean.
VOLATILITY_PRIOR_GAMES = 10

# Share of a player's expected missed games that comes from a SEASON-ENDING
# injury rather than week-to-week absences. Modelling every absence as an
# independent coin flip preserves the mean but erases the tail: a torn ACL in
# week 3 costs the rest of the year, it does not scatter itself over 17 weeks.
SEASON_ENDING_SHARE = {
    "QB": 0.35, "RB": 0.45, "WR": 0.40, "TE": 0.40, "K": 0.15, "DEF": 0.0,
}

# Projection uncertainty (lognormal sigma on a player's true per-game rate).
# This dominates week-to-week noise: the real question is whether the role and
# the projection are right at all, not how one Sunday bounces.
PROJECTION_SIGMA_BASE = {
    "QB": 0.22, "RB": 0.32, "WR": 0.32, "TE": 0.30, "K": 0.18, "DEF": 0.20,
}
# Extra uncertainty for players with little or no NFL track record.
PROJECTION_SIGMA_ROOKIE = 0.20
# Extra uncertainty when the model and the market disagree sharply.
PROJECTION_SIGMA_MARKET_GAP = 0.12

# ---------------------------------------------------------------- market
# How much to trust consensus ADP vs. the projection model when they disagree.
# 0 = ignore the market, 1 = draft strictly to ADP.
MARKET_WEIGHT = 0.35
# The market is trusted more when it is far BELOW the model (it usually knows
# about a situation the box score can't see); this is the extra asymmetric pull.
MARKET_FADE_ASYMMETRY = 0.20

# ---------------------------------------------------------------- simulation
N_SIMS = 4000
RANDOM_SEED = 17
# "Championship-optimized": weight expected value, upside, and bust risk.
# Upside and bust are deliberately close in magnitude. Projection uncertainty
# widens BOTH tails, so rewarding ceiling without charging for the downside
# would just rank the least-known players highest.
CHAMP_WEIGHTS = {"vorp": 0.58, "upside": 0.27, "bust": 0.22}
# Early rounds chase ceiling; middle rounds want floor. Round -> upside tilt.
ROUND_UPSIDE_TILT = {1: 1.25, 2: 1.20, 3: 1.10, 4: 1.00, 5: 0.90, 6: 0.85,
                     7: 0.85, 8: 0.90, 9: 1.00, 10: 1.10, 11: 1.20,
                     12: 1.35, 13: 1.45, 14: 1.55, 15: 1.60}

# ---------------------------------------------------------------- draft rules
TIER_DROP = 8.0
QB_EARLIEST_ROUND = 4
TE_EARLIEST_ROUND = 3
K_EARLIEST_ROUND = 15
DEF_EARLIEST_ROUND = 14
# Max rostered per position (stops the plan hoarding one position).
POSITION_LIMITS = {"QB": 2, "RB": 6, "WR": 7, "TE": 2, "K": 1, "DEF": 1}
# ADP noise (in picks) when simulating what the other 11 managers do.
ADP_NOISE_SD = 8.0

OUTPUT_DIR = "output"
