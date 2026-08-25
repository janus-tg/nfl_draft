import { useMemo, useState } from 'react'

import data from './data/board.json'
import Table from './components/Table'
import LiveDraft from './components/LiveDraft'
import { PlanView, EdgesView, InjuryView, RunsView, ValidationView } from './components/Views'
import { BOARD_COLUMNS, POSITIONS, filterRows, sortRows } from './lib/format'
import { exportBoard, rowsForExport } from './lib/exportExcel'

const TABS = [
  { id: 'live', label: 'Live draft' },
  { id: 'board', label: 'Board' },
  { id: 'plan', label: 'Draft plan' },
  { id: 'edges', label: 'Targets & fades' },
  { id: 'injury', label: 'Injury risk' },
  { id: 'runs', label: 'Position runs' },
  { id: 'validation', label: 'Validation' },
]

export default function App() {
  const [tab, setTab] = useState('live')
  const [slot, setSlot] = useState(1)
  const [query, setQuery] = useState('')
  const [pos, setPos] = useState('ALL')
  const [maxAdp, setMaxAdp] = useState(0)
  const [hideInjured, setHideInjured] = useState(false)
  const [sort, setSort] = useState({ key: 'Rank', dir: 'asc' })
  const [exporting, setExporting] = useState(false)

  const view = useMemo(() => {
    const filtered = filterRows(data.board, { query, pos, maxAdp, hideInjured })
    return sortRows(filtered, sort.key, sort.dir)
  }, [query, pos, maxAdp, hideInjured, sort])

  function onSort(key) {
    setSort((s) =>
      s.key === key
        ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: key === 'Rank' || key === 'ADP' ? 'asc' : 'desc' }
    )
  }

  async function handleExport() {
    const stamp = new Date().toISOString().slice(0, 10)
    setExporting(true)
    try {
      await exportBoard({
        view,
        columns: BOARD_COLUMNS,
        plans: data.plans,
        slot,
        extras: {
          Targets: rowsForExport(data.targets, targetCols).rows,
          Fades: rowsForExport(data.fades, fadeCols).rows,
          InjuryRisk: rowsForExport(data.injury, injuryCols).rows,
          PositionRuns: data.runs,
          Backtest: data.validation.backtest,
        },
        filename: `draft_board_${data.season}_${stamp}.xlsx`,
      })
    } finally {
      setExporting(false)
    }
  }

  const activeFilters =
    (pos !== 'ALL' ? 1 : 0) + (query ? 1 : 0) + (maxAdp ? 1 : 0) + (hideInjured ? 1 : 0)

  return (
    <div className="wrap">
      <header className="mast">
        <div>
          <h1>Draft War Room</h1>
          <p className="sub">
            Risk-adjusted board for the {data.season} season. Every projection is
            priced for the games a player is actually expected to play.
          </p>
        </div>
        <div className="facts">
          <div className="fact">
            <b>12</b>
            <span>Teams</span>
          </div>
          <div className="fact">
            <b>Full PPR</b>
            <span>Scoring</span>
          </div>
          <div className="fact">
            <b>{data.board.length}</b>
            <span>Players</span>
          </div>
          <div className="fact">
            <b>4,000</b>
            <span>Sims / player</span>
          </div>
        </div>
      </header>

      <nav className="tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            className="tab"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === 'live' && <LiveDraft board={data.board} league={data.league} />}

      {tab === 'board' && (
        <section>
          <div className="toolbar">
            <div className="grow">
              <input
                type="search"
                placeholder="Search player or team…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="Search players"
              />
            </div>
            <div className="chipset">
              {['ALL', ...POSITIONS].map((p) => (
                <button
                  key={p}
                  className="btn"
                  aria-pressed={pos === p}
                  onClick={() => setPos(p)}
                >
                  {p === 'ALL' ? 'All' : p}
                </button>
              ))}
            </div>
            <select
              value={maxAdp}
              onChange={(e) => setMaxAdp(Number(e.target.value))}
              aria-label="Limit by ADP"
            >
              <option value={0}>Any ADP</option>
              <option value={60}>ADP ≤ 60</option>
              <option value={120}>ADP ≤ 120</option>
              <option value={180}>ADP ≤ 180 (drafted)</option>
            </select>
            <button
              className="btn"
              aria-pressed={hideInjured}
              onClick={() => setHideInjured((v) => !v)}
            >
              Hide injured
            </button>
            <button className="btn primary" onClick={handleExport} disabled={exporting}>
              {exporting ? 'Building…' : '↓ Export to Excel'}
            </button>
          </div>
          <div className="toolbar" style={{ marginTop: -6 }}>
            <span className="count">
              {view.length} of {data.board.length} players
              {activeFilters ? ` · ${activeFilters} filter${activeFilters > 1 ? 's' : ''} active` : ''}
              {' · export includes exactly these rows'}
            </span>
          </div>
          <div className="panel">
            <Table
              rows={view}
              columns={BOARD_COLUMNS}
              sort={sort}
              onSort={onSort}
              tierBreaks={sort.key === 'Rank' && sort.dir === 'asc'}
            />
          </div>
        </section>
      )}

      {tab === 'plan' && <PlanView plans={data.plans} slot={slot} setSlot={setSlot} />}
      {tab === 'edges' && <EdgesView targets={data.targets} fades={data.fades} />}
      {tab === 'injury' && <InjuryView injury={data.injury} />}
      {tab === 'runs' && <RunsView runs={data.runs} />}
      {tab === 'validation' && <ValidationView validation={data.validation} />}

      <footer>
        Built from Sleeper {data.season} weekly projections, actual 2024–25 game
        logs for durability and volatility, live injury designations, and
        consensus PPR ADP. Rebuild with <code>py main.py</code> then{' '}
        <code>py export_web.py</code>. ADP is Sleeper/DynastyDaddy consensus —
        directionally right for a Yahoo room, but verify against your own board
        if Yahoo publishes one before draft day.
      </footer>
    </div>
  )
}

const targetCols = [
  { key: 'Player', label: 'Player' },
  { key: 'Tm', label: 'Team' },
  { key: 'Pos', label: 'Pos' },
  { key: 'Tier', label: 'Tier' },
  { key: 'ADP', label: 'ADP' },
  { key: 'Rank', label: 'ModelRank' },
  { key: 'Edge', label: 'Edge' },
  { key: 'ProjPts', label: 'ProjPts' },
  { key: 'VORP', label: 'VORP' },
  { key: 'P(elite)', label: 'P(elite)' },
  { key: 'P(bust)', label: 'P(bust)' },
]

const fadeCols = [
  { key: 'Player', label: 'Player' },
  { key: 'Tm', label: 'Team' },
  { key: 'Pos', label: 'Pos' },
  { key: 'ADP', label: 'ADP' },
  { key: 'Rank', label: 'ModelRank' },
  { key: 'Edge', label: 'Edge' },
  { key: 'ProjPts', label: 'ProjPts' },
  { key: 'RiskCost', label: 'RiskCost' },
  { key: 'ExpGames', label: 'ExpGames' },
  { key: 'P(bust)', label: 'P(bust)' },
  { key: 'Injury', label: 'Injury' },
]

const injuryCols = [
  { key: 'Player', label: 'Player' },
  { key: 'Tm', label: 'Team' },
  { key: 'Pos', label: 'Pos' },
  { key: 'ADP', label: 'ADP' },
  { key: 'NaivePts', label: 'NaivePts' },
  { key: 'ProjPts', label: 'AdjPts' },
  { key: 'RiskCost', label: 'RiskCost' },
  { key: 'ExpGames', label: 'ExpGames' },
  { key: 'P(seasonEnd)', label: 'P(seasonEnd)' },
  { key: 'Injury', label: 'Injury' },
  { key: 'InjuryDetail', label: 'Detail' },
]
