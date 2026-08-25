/** Live draft tracker: snake-order turn tracking, roster bookkeeping, and a
 *  pick recommender ported from the offline draft.py simulator.
 *
 *  The offline planner (draft.py) runs 250 simulated drafts per slot ahead of
 *  time; that can't happen live in a browser mid-draft, so this reimplements
 *  its scoring rule -- need, scarcity, and opportunity cost -- as a single-shot
 *  evaluation over whoever is actually still on the board right now.
 */

export const POSITIONS = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF']
const STORAGE_KEY = 'nfl-draft-live-v1'

// ---------------------------------------------------------------- snake math
export function pickNumber(slot, round, teams) {
  return round % 2 === 1 ? (round - 1) * teams + slot : (round - 1) * teams + (teams - slot + 1)
}

export function slotOnClock(overall, teams) {
  const round = Math.ceil(overall / teams)
  const posInRound = overall - (round - 1) * teams
  return round % 2 === 1 ? posInRound : teams - posInRound + 1
}

export function roundOf(overall, teams) {
  return Math.ceil(overall / teams)
}

/** The next overall pick number >= fromOverall that belongs to `slot`. */
export function nextPickForSlot(slot, fromOverall, teams, rounds) {
  const fromRound = Math.max(1, Math.ceil(fromOverall / teams))
  for (let r = fromRound; r <= rounds; r++) {
    const pn = pickNumber(slot, r, teams)
    if (pn >= fromOverall) return pn
  }
  return null
}

// ---------------------------------------------------------------- erf / survival
// Abramowitz & Stegun 7.1.26 -- close enough for a draft-day probability, and
// avoids pulling in a math library for one function.
function erf(x) {
  const sign = x < 0 ? -1 : 1
  const ax = Math.abs(x)
  const a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741
  const a4 = -1.453152027, a5 = 1.061405429, p = 0.3275911
  const t = 1 / (1 + p * ax)
  const y = 1 - ((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t * Math.exp(-ax * ax)
  return sign * y
}

/** P(a player with this ADP is still available at `pick`), from a normal tail
 *  around ADP. Mirrors the same closed-form approximation draft.py uses inside
 *  its pick loop. */
export function survivalProbability(adp, pick, noiseSd) {
  if (adp == null || pick == null) return 1
  const z = (adp - pick) / (noiseSd * Math.SQRT2)
  return 0.5 * (1 + erf(z))
}

// ---------------------------------------------------------------- roster state
export function emptyRoster() {
  return { counts: {}, picks: [] }
}

export function addPick(roster, pick) {
  const counts = { ...roster.counts, [pick.pos]: (roster.counts[pick.pos] || 0) + 1 }
  return { counts, picks: [...roster.picks, pick] }
}

export function buildRosters(picks, teams) {
  const rosters = {}
  for (let s = 1; s <= teams; s++) rosters[s] = emptyRoster()
  for (const pk of picks) {
    rosters[pk.slot] = addPick(rosters[pk.slot], pk)
  }
  return rosters
}

function startersMissing(roster, starters) {
  const out = {}
  for (const pos of Object.keys(starters)) {
    out[pos] = Math.max(0, starters[pos] - (roster.counts[pos] || 0))
  }
  return out
}

function flexFilled(roster, starters, flexPositions) {
  const surplus = flexPositions.reduce(
    (sum, pos) => sum + Math.max(0, (roster.counts[pos] || 0) - (starters[pos] || 0)),
    0
  )
  return surplus >= 1
}

/** How much this roster wants another player at `pos` right now. Diminishing
 *  bench value is what stops the recommender stacking five backup RBs in a
 *  row once the starting lineup is set. */
export function needMultiplier(roster, pos, round, roundsTotal, league) {
  const missing = startersMissing(roster, league.starters)
  if ((missing[pos] || 0) > 0) return 1.3
  if (league.flexPositions.includes(pos) && !flexFilled(roster, league.starters, league.flexPositions)) {
    return pos === 'TE' ? 0.95 : 1.12
  }
  if (pos === 'K' || pos === 'DEF') {
    return (roster.counts[pos] || 0) >= 1 ? 0 : 1.0
  }
  if ((pos === 'QB' || pos === 'TE') && (roster.counts[pos] || 0) >= 1) {
    if ((roster.counts[pos] || 0) >= 2 || round < roundsTotal - 2) return 0
    return 0.45
  }
  const extra = (roster.counts[pos] || 0) - (league.starters[pos] || 0)
  return Math.max(0.3, 1.05 * Math.pow(0.72, Math.max(extra, 0)))
}

export function canTake(roster, pos, round, league) {
  const limit = league.positionLimits[pos] ?? 99
  if ((roster.counts[pos] || 0) >= limit) return false
  if (round < (league.earliestRound[pos] ?? 0)) return false
  return true
}

// ---------------------------------------------------------------- scoring helpers
function mean(arr) {
  return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0
}
function std(arr) {
  if (arr.length < 2) return 0
  const m = mean(arr)
  return Math.sqrt(mean(arr.map((v) => (v - m) ** 2)))
}
function zscores(arr) {
  const m = mean(arr)
  const sd = std(arr) || 1
  return arr.map((v) => (v - m) / sd)
}

/** Value lost by waiting one round at this position: best available minus
 *  roughly the `teams`-th best remaining. A big gap means the position is
 *  about to break. */
function scarcityByPos(available, teams) {
  const out = {}
  for (const pos of POSITIONS) {
    const vals = available
      .filter((p) => p.Pos === pos)
      .map((p) => p.VORP ?? 0)
      .sort((a, b) => b - a)
    if (vals.length < 2) {
      out[pos] = 0
      continue
    }
    const next = vals[Math.min(teams, vals.length - 1)]
    out[pos] = Math.max(vals[0] - next, 0)
  }
  return out
}

/** Rank `available` for `myRoster` right now: value (VORP + ceiling upside -
 *  bust risk, all scored relative to what's actually still on the board) times
 *  roster need, nudged by scarcity and by how likely the player is to survive
 *  to your next pick. */
export function recommend(available, myRoster, round, league, myNextPick, topN = 10) {
  if (!available.length) return []
  const vorps = available.map((p) => p.VORP ?? 0)
  const ceilings = available.map((p) => p.Ceiling ?? 0)
  const busts = available.map((p) => p['P(bust)'] ?? 0)
  const zV = zscores(vorps)
  const zC = zscores(ceilings)
  const zB = zscores(busts)
  const scarcity = scarcityByPos(available, league.teams)
  const maxScarcity = Math.max(...Object.values(scarcity), 1)

  const scored = available
    .map((p, i) => {
      if (!canTake(myRoster, p.Pos, round, league)) return null
      const need = needMultiplier(myRoster, p.Pos, round, league.rounds, league)
      if (need <= 0) return null
      const survive = survivalProbability(p.ADP, myNextPick, league.adpNoiseSd)
      const urgency = 1 - survive
      const value = 0.55 * zV[i] + 0.27 * zC[i] - 0.22 * zB[i] + 0.3 * (scarcity[p.Pos] / maxScarcity)
      const score = value * (0.6 + 0.4 * urgency) * need
      return { ...p, _score: score, _urgency: urgency, _need: need }
    })
    .filter(Boolean)

  scored.sort((a, b) => b._score - a._score)
  return scored.slice(0, topN)
}

/** Best-effort lineup assignment for the "my roster" display: fill starters by
 *  value, then the flex, then bench. Display only -- it doesn't gate picks. */
export function assignLineup(myPicks, league) {
  const sorted = [...myPicks].sort((a, b) => (b.VORP ?? 0) - (a.VORP ?? 0))
  const used = new Set()
  const starters = {}
  for (const pos of Object.keys(league.starters)) {
    const chosen = sorted.filter((p) => p.pos === pos && !used.has(p.playerId)).slice(0, league.starters[pos])
    chosen.forEach((p) => used.add(p.playerId))
    starters[pos] = chosen
  }
  const flexPool = sorted.filter((p) => league.flexPositions.includes(p.pos) && !used.has(p.playerId))
  const flex = flexPool.slice(0, 1)
  flex.forEach((p) => used.add(p.playerId))
  const bench = sorted.filter((p) => !used.has(p.playerId))
  return { starters, flex, bench }
}

// ---------------------------------------------------------------- persistence
export function loadDraftState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed.picks)) return null
    return parsed
  } catch {
    return null
  }
}

export function saveDraftState(state) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    // Private browsing / storage disabled -- the draft still works in-memory
    // for this tab, it just won't survive a refresh.
  }
}

export function clearDraftState() {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* ignore */
  }
}
