import { useEffect, useMemo, useState } from 'react'

import { Pos, PlayerCell } from './Table'
import { pct, n0, POSITIONS } from '../lib/format'
import {
  buildRosters,
  assignLineup,
  clearDraftState,
  loadDraftState,
  nextPickForSlot,
  recommend,
  roundOf,
  saveDraftState,
  slotOnClock,
} from '../lib/liveDraft'

const DEFAULT_LEAGUE = {
  teams: 12,
  rounds: 15,
  starters: { QB: 1, RB: 2, WR: 3, TE: 1, K: 1, DEF: 1 },
  flexPositions: ['RB', 'WR', 'TE'],
  benchSlots: 5,
  positionLimits: { QB: 1, RB: 6, WR: 7, TE: 2, K: 1, DEF: 1 },
  // K and DEF are the last two picks of the draft; DEF goes dead last.
  earliestRound: { QB: 4, TE: 3, K: 14, DEF: 15 },
  adpNoiseSd: 8.0,
}

const saved = loadDraftState()

export default function LiveDraft({ board, league: leagueIn }) {
  const league = leagueIn || DEFAULT_LEAGUE
  const [mySlot, setMySlot] = useState(saved?.mySlot ?? null)
  const [picks, setPicks] = useState(saved?.picks ?? [])
  const [query, setQuery] = useState('')
  const [posFilter, setPosFilter] = useState('ALL')
  const [confirmReset, setConfirmReset] = useState(false)

  useEffect(() => {
    saveDraftState({ mySlot, picks })
  }, [mySlot, picks])

  const byId = useMemo(() => new Map(board.map((r) => [r.Id, r])), [board])
  const draftedIds = useMemo(() => new Set(picks.map((p) => p.playerId)), [picks])
  const available = useMemo(() => board.filter((r) => !draftedIds.has(r.Id)), [board, draftedIds])
  const rosters = useMemo(() => buildRosters(picks, league.teams), [picks, league.teams])

  const currentOverall = picks.length + 1
  const currentRound = roundOf(currentOverall, league.teams)
  const onClockSlot = slotOnClock(currentOverall, league.teams)
  const draftDone = currentRound > league.rounds
  const isMyTurn = mySlot != null && onClockSlot === mySlot && !draftDone

  const myRoster = mySlot != null ? rosters[mySlot] : null
  const myNextPick =
    mySlot != null ? nextPickForSlot(mySlot, currentOverall, league.teams, league.rounds) : null

  const recommendations = useMemo(() => {
    if (mySlot == null || draftDone) return []
    return recommend(available, myRoster, currentRound, league, myNextPick, 10)
  }, [available, myRoster, currentRound, league, myNextPick, mySlot, draftDone])

  const visibleAvailable = useMemo(() => {
    const q = query.trim().toLowerCase()
    let rows = available.filter((r) => {
      if (posFilter !== 'ALL' && r.Pos !== posFilter) return false
      if (q && !`${r.Player} ${r.Tm ?? ''}`.toLowerCase().includes(q)) return false
      return true
    })
    // Default order: by recommendation when we have one for this player, else
    // by champ rank -- so the list stays useful even before mySlot is set.
    const scoreOf = new Map(recommendations.map((r) => [r.Id, r._score]))
    rows = [...rows].sort((a, b) => {
      const sa = scoreOf.get(a.Id)
      const sb = scoreOf.get(b.Id)
      if (sa != null || sb != null) return (sb ?? -1e9) - (sa ?? -1e9)
      return (a.Rank ?? 9999) - (b.Rank ?? 9999)
    })
    return rows.slice(0, 150)
  }, [available, posFilter, query, recommendations])

  function draftPlayer(row) {
    const pick = {
      overall: currentOverall,
      round: currentRound,
      slot: onClockSlot,
      playerId: row.Id,
      player: row.Player,
      team: row.Tm,
      pos: row.Pos,
      VORP: row.VORP,
      ADP: row.ADP,
    }
    setPicks((p) => [...p, pick])
  }

  function undoLast() {
    setPicks((p) => p.slice(0, -1))
  }

  function resetDraft() {
    setPicks([])
    clearDraftState()
    setConfirmReset(false)
  }

  if (mySlot == null) {
    return (
      <section>
        <div className="callout">
          <h2>Set your draft slot</h2>
          <p>
            Pick your seat in the snake order. As the draft happens, click each
            player as they&apos;re taken — whether it&apos;s an opponent or you —
            and this tracks every roster and tells you the best pick for yours
            whenever it&apos;s your turn.
          </p>
        </div>
        <div className="slotbar" role="group" aria-label="Choose your draft slot">
          <span className="lbl">Your slot</span>
          {Array.from({ length: league.teams }, (_, i) => i + 1).map((s) => (
            <button key={s} className="slot" onClick={() => setMySlot(s)} aria-label={`Slot ${s}`}>
              {s}
            </button>
          ))}
        </div>
      </section>
    )
  }

  return (
    <section>
      <ClockBanner
        draftDone={draftDone}
        currentOverall={currentOverall}
        currentRound={currentRound}
        rounds={league.rounds}
        onClockSlot={onClockSlot}
        isMyTurn={isMyTurn}
        picksCount={picks.length}
        undoLast={undoLast}
        confirmReset={confirmReset}
        setConfirmReset={setConfirmReset}
        resetDraft={resetDraft}
        changeSlot={() => setMySlot(null)}
      />

      {!draftDone && (
        <RecommendPanel
          recommendations={recommendations}
          isMyTurn={isMyTurn}
          onDraft={draftPlayer}
          myNextPick={myNextPick}
        />
      )}

      <div className="twoup" style={{ alignItems: 'start', marginTop: 22 }}>
        <div className="panel">
          <header>
            <h3>Available players</h3>
            <p>Click a player to log the pick for whoever is on the clock</p>
          </header>
          <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--line)' }}>
            <div className="toolbar" style={{ marginBottom: 0 }}>
              <div className="grow">
                <input
                  type="search"
                  placeholder="Search player or team…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  aria-label="Search available players"
                />
              </div>
              <div className="chipset">
                {['ALL', ...POSITIONS].map((p) => (
                  <button
                    key={p}
                    className="btn"
                    aria-pressed={posFilter === p}
                    onClick={() => setPosFilter(p)}
                  >
                    {p === 'ALL' ? 'All' : p}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <AvailableTable rows={visibleAvailable} draftDone={draftDone} onDraft={draftPlayer} />
        </div>

        <MyTeamPanel roster={myRoster} league={league} mySlot={mySlot} />
      </div>

      <AllTeamsGrid rosters={rosters} teams={league.teams} mySlot={mySlot} onClockSlot={draftDone ? null : onClockSlot} />
    </section>
  )
}

function ClockBanner({
  draftDone, currentOverall, currentRound, rounds, onClockSlot, isMyTurn,
  picksCount, undoLast, confirmReset, setConfirmReset, resetDraft, changeSlot,
}) {
  return (
    <div className={`callout${isMyTurn ? '' : ''}`} style={isMyTurn ? { borderLeftColor: 'var(--good)' } : undefined}>
      {draftDone ? (
        <>
          <h2>Draft complete</h2>
          <p>All {rounds} rounds are in. Check your roster below, or reset to run a mock.</p>
        </>
      ) : (
        <>
          <h2>
            {isMyTurn ? 'Your pick' : `Team ${onClockSlot} is on the clock`} — Round{' '}
            {currentRound}, Pick {currentOverall}
          </h2>
          <p>
            {isMyTurn
              ? 'Recommendations below are ranked for your roster right now.'
              : 'Click whoever they take in the list below to keep the tracker in sync.'}
          </p>
        </>
      )}
      <div className="toolbar" style={{ marginTop: 4, marginBottom: 0 }}>
        <button className="btn" onClick={undoLast} disabled={picksCount === 0}>
          ↺ Undo last pick
        </button>
        <button className="btn" onClick={changeSlot}>
          Change my slot
        </button>
        {confirmReset ? (
          <>
            <span className="count">Discard all {picksCount} picks?</span>
            <button className="btn" style={{ borderColor: 'var(--danger)', color: 'var(--danger)' }} onClick={resetDraft}>
              Confirm reset
            </button>
            <button className="btn" onClick={() => setConfirmReset(false)}>
              Cancel
            </button>
          </>
        ) : (
          <button className="btn" onClick={() => setConfirmReset(true)} disabled={picksCount === 0}>
            Reset draft
          </button>
        )}
      </div>
    </div>
  )
}

function RecommendPanel({ recommendations, isMyTurn, onDraft, myNextPick }) {
  if (!recommendations.length) {
    return (
      <div className="panel">
        <header>
          <h3>Best available for your roster</h3>
          <p>No eligible players right now — your positional limits or round rules exclude what&apos;s left.</p>
        </header>
      </div>
    )
  }
  return (
    <div className={`panel${isMyTurn ? ' good' : ''}`}>
      <header>
        <h3>Best available for your roster</h3>
        <p>
          Ranked by value, roster need, and how likely each player is to survive
          to your next pick{myNextPick ? ` (pick ${myNextPick})` : ''}.
        </p>
      </header>
      <div className="rounds" style={{ padding: 13 }}>
        {recommendations.slice(0, 8).map((r, i) => (
          <article className={`rd${i === 0 ? ' key' : ''}`} key={r.Id}>
            <div className="rd-top">
              <span>#{i + 1} suggestion</span>
              <span>ADP {n0(r.ADP)}</span>
            </div>
            <div className="rd-name">
              {r.Player}
              {r.Injury ? <span className="flag">{r.Injury}</span> : null}
            </div>
            <div className="rd-meta">
              <Pos p={r.Pos} />
              <span className="tm">{r.Tm}</span>
              <span className="tier">Tier {r.Tier}</span>
            </div>
            <div className="rd-stats">
              <div>
                <span>VORP</span>
                <b>{n0(r.VORP)}</b>
              </div>
              <div>
                <span>Ceiling</span>
                <b>{n0(r.Ceiling)}</b>
              </div>
              <div>
                <span>Bust</span>
                <b>{pct(r['P(bust)'])}</b>
              </div>
              <div>
                <span>Survives to next</span>
                <b>{pct(1 - r._urgency)}</b>
              </div>
            </div>
            <button className="btn primary" style={{ width: '100%', marginTop: 9 }} onClick={() => onDraft(r)}>
              Draft {r.Player}
            </button>
          </article>
        ))}
      </div>
    </div>
  )
}

function AvailableTable({ rows, draftDone, onDraft }) {
  return (
    <div className="tw" style={{ maxHeight: '58vh' }}>
      <table>
        <thead>
          <tr>
            <th className="l">Player</th>
            <th>Pos</th>
            <th>Tier</th>
            <th>ADP</th>
            <th>VORP</th>
            <th>Bust</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.Id}>
              <td className="l">
                <PlayerCell name={r.Player} team={r.Tm} injury={r.Injury} />
              </td>
              <td>
                <Pos p={r.Pos} />
              </td>
              <td className="n">{r.Tier}</td>
              <td className="n">{n0(r.ADP)}</td>
              <td className="n">{n0(r.VORP)}</td>
              <td className="n">{pct(r['P(bust)'])}</td>
              <td className="n">
                <button className="btn" disabled={draftDone} onClick={() => onDraft(r)}>
                  Draft
                </button>
              </td>
            </tr>
          ))}
          {rows.length === 0 ? (
            <tr>
              <td className="l dim" colSpan={7}>
                No players match this filter.
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  )
}

function MyTeamPanel({ roster, league, mySlot }) {
  const lineup = assignLineup(roster?.picks ?? [], league)
  const starterOrder = Object.keys(league.starters)

  return (
    <div className="panel">
      <header>
        <h3>Your roster — Slot {mySlot}</h3>
        <p>{roster?.picks.length ?? 0} players drafted</p>
      </header>
      <div style={{ padding: 13, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {starterOrder.map((pos) => (
          <LineupRow key={pos} label={pos} slots={league.starters[pos]} filled={lineup.starters[pos]} />
        ))}
        <LineupRow label="FLEX" slots={1} filled={lineup.flex} />
        <div style={{ borderTop: '1px solid var(--line-soft)', paddingTop: 8, marginTop: 4 }}>
          <span className="count" style={{ display: 'block', marginBottom: 6 }}>
            BENCH ({lineup.bench.length}/{league.benchSlots})
          </span>
          {lineup.bench.length === 0 ? (
            <span className="dim" style={{ fontSize: 12.5 }}>
              —
            </span>
          ) : (
            lineup.bench.map((p) => (
              <div key={p.playerId} style={{ display: 'flex', gap: 7, alignItems: 'center', padding: '3px 0' }}>
                <Pos p={p.pos} />
                <span style={{ fontSize: 13 }}>{p.player}</span>
                <span className="tm">{n0(p.VORP)} VORP</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

function LineupRow({ label, slots, filled }) {
  const empties = Math.max(0, slots - (filled?.length ?? 0))
  return (
    <div>
      <span className="count" style={{ display: 'block', marginBottom: 4 }}>
        {label}
      </span>
      {(filled ?? []).map((p) => (
        <div key={p.playerId} style={{ display: 'flex', gap: 7, alignItems: 'center', padding: '3px 0' }}>
          <Pos p={p.pos} />
          <span style={{ fontSize: 13.5, fontWeight: 500 }}>{p.player}</span>
          <span className="tm">{n0(p.VORP)} VORP</span>
        </div>
      ))}
      {Array.from({ length: empties }, (_, i) => (
        <div key={i} className="dim" style={{ fontSize: 12.5, padding: '3px 0' }}>
          — empty —
        </div>
      ))}
    </div>
  )
}

function AllTeamsGrid({ rosters, teams, mySlot, onClockSlot }) {
  return (
    <section style={{ marginTop: 24 }}>
      <div className="shead">
        <h2>All teams</h2>
        <div className="rule" />
      </div>
      <p className="snote">Every roster so far, in draft order. Your team is highlighted.</p>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(auto-fill, minmax(150px, 1fr))`,
          gap: 10,
        }}
      >
        {Array.from({ length: teams }, (_, i) => i + 1).map((s) => {
          const r = rosters[s]
          const mine = s === mySlot
          const onClock = s === onClockSlot
          return (
            <div
              key={s}
              className="panel"
              style={{
                padding: 10,
                boxShadow: mine ? '0 0 0 1px var(--accent)' : onClock ? '0 0 0 1px var(--good)' : undefined,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <span className="disp" style={{ fontSize: 16 }}>
                  Team {s}
                  {mine ? ' (you)' : ''}
                </span>
                {onClock ? <span className="flag" style={{ background: 'var(--good-soft)', color: 'var(--good)' }}>ON CLOCK</span> : null}
              </div>
              {r.picks.length === 0 ? (
                <span className="dim" style={{ fontSize: 12 }}>
                  No picks yet
                </span>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  {r.picks.map((p) => (
                    <div key={p.playerId} style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 12 }}>
                      <Pos p={p.pos} />
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {p.player}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
