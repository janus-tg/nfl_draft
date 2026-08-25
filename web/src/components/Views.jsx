import { Pos, PlayerCell, Edge, MiniTable } from './Table'
import { pct, n0, n1, n2 } from '../lib/format'

/* ------------------------------------------------ draft plan ------------ */
export function PlanView({ plans, slot, setSlot }) {
  const rows = plans[slot] || []
  const slots = Object.keys(plans)
    .map(Number)
    .sort((a, b) => a - b)

  return (
    <section>
      <p className="snote">
        You don&apos;t know your seat yet, so here is every one. Each card is the
        pick that survived most often across 250 simulated drafts from that slot,
        against eleven opponents drafting to ADP. <b>Still there</b> is how often
        that player was actually on the board at that pick — under 40%, treat the
        fallbacks as the real plan.
      </p>

      <div className="slotbar" role="group" aria-label="Draft slot">
        <span className="lbl">Your slot</span>
        {slots.map((s) => (
          <button
            key={s}
            className="slot"
            aria-pressed={s === slot}
            aria-label={`Draft slot ${s}`}
            onClick={() => setSlot(s)}
          >
            {s}
          </button>
        ))}
      </div>

      <div className="rounds">
        {rows.map((r) => {
          const low = (r.pAvail ?? 1) < 0.4
          return (
            <article className={`rd${r.round <= 4 ? ' key' : ''}`} key={r.round}>
              <div className="rd-top">
                <span>
                  Rd {r.round} · Pick {r.pick}
                </span>
                <span>ADP {n0(r.adp)}</span>
              </div>
              <div className="rd-name">
                {r.player}
                {r.injury ? <span className="flag">{r.injury}</span> : null}
              </div>
              <div className="rd-meta">
                <Pos p={r.pos} />
                <span className="tm">{r.team}</span>
                <span className="tier">Tier {r.tier}</span>
              </div>
              <div className="rd-stats">
                <div>
                  <span>Proj</span>
                  <b>{n0(r.proj)}</b>
                </div>
                <div>
                  <span>VORP</span>
                  <b>{n0(r.vorp)}</b>
                </div>
                <div>
                  <span>Elite</span>
                  <b>{pct(r.pElite)}</b>
                </div>
                <div>
                  <span>Bust</span>
                  <b>{pct(r.pBust)}</b>
                </div>
              </div>
              <div className={`meter${low ? ' low' : ''}`}>
                <i style={{ width: `${Math.round((r.pAvail ?? 0) * 100)}%` }} />
              </div>
              <div className="rd-stats" style={{ marginTop: 5 }}>
                <div>
                  <span>Still there at your pick</span>
                  <b>{pct(r.pAvail)}</b>
                </div>
              </div>
              {r.alts?.length ? (
                <div className="alts">
                  <span className="k">If he&apos;s gone</span>
                  {r.alts.map((a, i) => (
                    <span className="a" key={i}>
                      <Pos p={a.pos} /> {a.player}{' '}
                      <span className="tm">{pct(a.pAvail)} avail</span>
                    </span>
                  ))}
                </div>
              ) : null}
            </article>
          )
        })}
      </div>
    </section>
  )
}

/* ------------------------------------------------ edges ---------------- */
export function EdgesView({ targets, fades }) {
  return (
    <section>
      <p className="snote">
        <b>Edge</b> is market rank minus model rank. Positive means the room lets
        him fall past where he&apos;s worth taking; negative means he goes earlier
        than the risk-adjusted value can justify.
      </p>
      <div className="twoup">
        <div className="panel good">
          <header>
            <h3>Draft these</h3>
            <p>Model well above draft cost, with a real role behind it</p>
          </header>
          <MiniTable
            headers={[
              { label: 'Player', align: 'l' },
              { label: 'Pos' },
              { label: 'ADP' },
              { label: 'Edge' },
              { label: 'Proj' },
              { label: 'VORP' },
              { label: 'Elite' },
            ]}
            rows={targets.map((t) => [
              <PlayerCell name={t.Player} team={t.Tm} />,
              <Pos p={t.Pos} />,
              n0(t.ADP),
              <Edge v={t.Edge} />,
              n0(t.ProjPts),
              n0(t.VORP),
              pct(t['P(elite)']),
            ])}
          />
        </div>
        <div className="panel bad">
          <header>
            <h3>Let these go</h3>
            <p>Name worth more than the projection once availability is priced</p>
          </header>
          <MiniTable
            headers={[
              { label: 'Player', align: 'l' },
              { label: 'Pos' },
              { label: 'ADP' },
              { label: 'Edge' },
              { label: 'Games' },
              { label: 'Bust' },
            ]}
            rows={fades.map((f) => [
              <PlayerCell name={f.Player} team={f.Tm} injury={f.Injury} />,
              <Pos p={f.Pos} />,
              n0(f.ADP),
              <Edge v={f.Edge} />,
              n1(f.ExpGames),
              pct(f['P(bust)']),
            ])}
          />
        </div>
      </div>
    </section>
  )
}

/* ------------------------------------------------ injury --------------- */
export function InjuryView({ injury }) {
  const max = Math.max(...injury.map((r) => r.RiskCost || 0), 1)
  return (
    <section>
      <p className="snote">
        <b>Naive</b> is the full-17-game number the old method showed. <b>Adj</b>{' '}
        prices in the current designation, the specific injury, this
        player&apos;s own games-played history, and an age curve. The gap is the
        mistake that was being made.
      </p>
      <div className="panel">
        <MiniTable
          headers={[
            { label: 'Player', align: 'l' },
            { label: 'Pos' },
            { label: 'ADP' },
            { label: 'Naive' },
            { label: 'Adj' },
            { label: 'Cost of risk', align: 'l' },
            { label: 'Games' },
            { label: 'SeasonEnd' },
            { label: 'Flag', align: 'l' },
          ]}
          rows={injury.map((r) => [
            <PlayerCell name={r.Player} team={r.Tm} />,
            <Pos p={r.Pos} />,
            n0(r.ADP),
            <span className="dim">{n0(r.NaivePts)}</span>,
            n0(r.ProjPts),
            <span className="bar">
              <span className="t">
                <i style={{ width: `${Math.round((100 * (r.RiskCost || 0)) / max)}%` }} />
              </span>
              <span className="v">−{n0(r.RiskCost)}</span>
            </span>,
            n1(r.ExpGames),
            pct(r['P(seasonEnd)']),
            <span style={{ fontSize: 12, color: 'var(--text-2)' }}>
              {r.InjuryDetail || r.Injury || '—'}
            </span>,
          ])}
        />
      </div>
    </section>
  )
}

/* ------------------------------------------------ runs ----------------- */
const RUN_POS = ['RB', 'WR', 'TE', 'QB']
const VAR_OF = { RB: '--rb', WR: '--wr', TE: '--te', QB: '--qb' }

export function RunsView({ runs }) {
  return (
    <section>
      <p className="snote">
        Expected players gone by the end of each round. Read it against your own
        pick numbers: the round a position&apos;s band widens is the round you
        stop waiting on it.
      </p>
      <div className="runs">
        {runs.map((r) => {
          const total = RUN_POS.reduce((s, p) => s + (r[p] || 0), 0) || 1
          return (
            <div className="runrow" key={r.Round}>
              <span className="rl">Rd {r.Round}</span>
              <span
                className="stack"
                title={RUN_POS.map((p) => `${p} ${r[p] ?? 0}`).join(' · ')}
              >
                {RUN_POS.map((p) => (
                  <i
                    key={p}
                    style={{
                      width: `${((100 * (r[p] || 0)) / total).toFixed(1)}%`,
                      background: `var(${VAR_OF[p]})`,
                    }}
                  />
                ))}
              </span>
            </div>
          )
        })}
        <div className="legend">
          {RUN_POS.map((p) => (
            <span key={p}>
              <i style={{ background: `var(${VAR_OF[p]})` }} />
              {p}
            </span>
          ))}
          <span className="dim">
            Band width = share of picks spent at each position through that round
          </span>
        </div>
      </div>
    </section>
  )
}

/* ------------------------------------------------ validation ----------- */
export function ValidationView({ validation }) {
  const bt = validation.backtest || []
  const all = bt.find((r) => r.pos === 'ALL')
  const vs = validation.vsExperts || []

  const improvement =
    all && all.naive_MAE ? (100 * (all.naive_MAE - all.risk_MAE)) / all.naive_MAE : null

  return (
    <section>
      <div className="callout">
        <h2>Does the model actually work?</h2>
        <p>
          <strong>Agreement with experts is a sanity check, not a score.</strong>{' '}
          A model that matches consensus everywhere has no edge; one that
          disagrees everywhere is broken. The test that matters is the backtest:
          rebuild the board using only information available before the 2025
          season, then score it against what actually happened.
        </p>
        <p>
          <strong>The naive method was systematically optimistic.</strong> It
          over-predicted by {all ? n0(all.naive_bias) : '—'} points per player on
          average — that is the &ldquo;everyone plays 17 games&rdquo; assumption
          showing up as pure bias. The availability adjustment cuts that to{' '}
          {all ? n0(all.risk_bias) : '—'}.
        </p>
      </div>

      {all ? (
        <div className="metrics">
          <div className="metric good">
            <b>{improvement != null ? `${improvement.toFixed(1)}%` : '—'}</b>
            <span>MAE improvement</span>
            <small>Mean absolute error, 2025 backtest, all positions</small>
          </div>
          <div className="metric">
            <b>{n1(all.naive_MAE)} → {n1(all.risk_MAE)}</b>
            <span>MAE naive → adjusted</span>
            <small>Points of error per player over the season</small>
          </div>
          <div className="metric good">
            <b>+{n1(all.naive_bias)} → +{n1(all.risk_bias)}</b>
            <span>Systematic bias</span>
            <small>How much each method over-predicts on average</small>
          </div>
          <div className="metric">
            <b>{all.n}</b>
            <span>Players scored</span>
            <small>With both a 2025 projection and 2025 results</small>
          </div>
        </div>
      ) : null}

      <div className="panel" style={{ marginBottom: 22 }}>
        <header>
          <h3>Backtest by position</h3>
          <p>2025 preseason forecast scored against 2025 actual results — lower is better</p>
        </header>
        <MiniTable
          headers={[
            { label: 'Pos', align: 'l' },
            { label: 'N' },
            { label: 'Naive MAE' },
            { label: 'Adj MAE' },
            { label: 'Naive RMSE' },
            { label: 'Adj RMSE' },
            { label: 'Naive bias' },
            { label: 'Adj bias' },
          ]}
          rows={bt.map((r) => [
            r.pos,
            r.n,
            n1(r.naive_MAE),
            <b style={{ color: 'var(--good)' }}>{n1(r.risk_MAE)}</b>,
            n1(r.naive_RMSE),
            n1(r.risk_RMSE),
            n1(r.naive_bias),
            <b style={{ color: 'var(--good)' }}>{n1(r.risk_bias)}</b>,
          ])}
        />
      </div>

      <div className="panel">
        <header>
          <h3>Biggest disagreements with FantasyPros consensus</h3>
          <p>
            Positive delta = model ranks him higher than the experts. Negative =
            experts rank him higher than the model.
          </p>
        </header>
        <MiniTable
          headers={[
            { label: 'Player', align: 'l' },
            { label: 'Pos' },
            { label: 'Expert' },
            { label: 'Model' },
            { label: 'Delta' },
            { label: 'ADP' },
            { label: 'Games' },
            { label: 'Bust' },
            { label: 'Flag', align: 'l' },
          ]}
          rows={[...vs]
            .sort((a, b) => Math.abs(b.delta ?? 0) - Math.abs(a.delta ?? 0))
            .slice(0, 24)
            .map((r) => [
              <PlayerCell name={r.player} />,
              <Pos p={r.pos} />,
              n0(r.fp_rank_j),
              n0(r.model_rank_j),
              <Edge v={r.delta} />,
              n0(r.adp_filled),
              n1(r.ExpGames),
              pct(r['P(bust)']),
              <span style={{ fontSize: 12, color: 'var(--text-2)' }}>
                {r.Injury || '—'}
              </span>,
            ])}
        />
      </div>
    </section>
  )
}
