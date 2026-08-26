/** Shared formatters and the column contract used by both the tables and the
 *  Excel export, so what you see is exactly what gets exported. */

export const POSITIONS = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF']

export const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`)
export const n0 = (v) => (v == null ? '—' : Math.round(v).toLocaleString())
export const n1 = (v) => (v == null ? '—' : (Math.round(v * 10) / 10).toFixed(1))
export const n2 = (v) => (v == null ? '—' : (Math.round(v * 100) / 100).toFixed(2))

/** Column definitions drive rendering, sorting, and export together.
 *  key      - field on the row
 *  label    - header text
 *  align    - 'l' for left
 *  fmt      - display formatter
 *  raw      - value used for the Excel export (numbers stay numbers there) */
export const BOARD_COLUMNS = [
  { key: 'Rank', label: '#', fmt: (v) => v, cls: 'rk' },
  { key: 'Player', label: 'Player', align: 'l', special: 'player' },
  { key: 'Pos', label: 'Pos', special: 'pos' },
  { key: 'PosRank', label: 'PosRk', fmt: n0 },
  { key: 'Tier', label: 'Tier', fmt: (v) => v },
  { key: 'ADP', label: 'ADP', fmt: n0 },
  { key: 'Edge', label: 'Edge', special: 'edge' },
  { key: 'ProjPts', label: 'Proj', fmt: n0 },
  { key: 'VORP', label: 'VORP', fmt: n0 },
  { key: 'Floor', label: 'Floor', fmt: n0, dim: true },
  { key: 'Median', label: 'Median', fmt: n0 },
  { key: 'Ceiling', label: 'Ceiling', fmt: n0 },
  { key: 'P(elite)', label: 'Elite', fmt: pct },
  { key: 'P(starter)', label: 'Starter', fmt: pct },
  { key: 'P(bust)', label: 'Bust', fmt: pct },
  { key: 'ExpGames', label: 'Games', fmt: n1 },
  { key: 'P(seasonEnd)', label: 'SeasonEnd', fmt: pct },
  { key: 'RiskCost', label: 'RiskCost', fmt: n0 },
  { key: 'Durability', label: 'Durab', fmt: n2 },
  { key: 'Age', label: 'Age', fmt: (v) => (v == null ? '—' : v) },
  { key: 'OLRating', label: 'OLine', fmt: (v) => (v == null ? '—' : Math.round(v)) },
  { key: 'CV', label: 'CV', fmt: n2 },
  { key: 'Injury', label: 'Injury', align: 'l', fmt: (v) => v || '—' },
]

/** Sort a row set by a column, nulls always last regardless of direction. */
export function sortRows(rows, key, dir) {
  const sign = dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const x = a[key]
    const y = b[key]
    if (x == null && y == null) return 0
    if (x == null) return 1
    if (y == null) return -1
    if (typeof x === 'number' && typeof y === 'number') return (x - y) * sign
    return String(x).localeCompare(String(y)) * sign
  })
}

export function filterRows(rows, { query, pos, maxAdp, hideInjured }) {
  const q = query.trim().toLowerCase()
  return rows.filter((r) => {
    if (pos !== 'ALL' && r.Pos !== pos) return false
    if (q && !`${r.Player} ${r.Tm ?? ''}`.toLowerCase().includes(q)) return false
    if (maxAdp && r.ADP != null && r.ADP > maxAdp) return false
    if (hideInjured && r.Injury) return false
    return true
  })
}
