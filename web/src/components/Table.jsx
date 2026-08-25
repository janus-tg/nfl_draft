import { pct, n0, n1 } from '../lib/format'

export function Pos({ p }) {
  return <span className={`pos ${p}`}>{p}</span>
}

export function PlayerCell({ name, team, injury }) {
  return (
    <>
      <span className="pname">{name}</span>
      {team ? <span className="tm">{team}</span> : null}
      {injury ? <span className="flag">{injury}</span> : null}
    </>
  )
}

export function Edge({ v }) {
  if (v == null) return <>—</>
  const cls = v > 0 ? 'up' : v < 0 ? 'dn' : ''
  return (
    <span className={`edge ${cls}`}>
      {v > 0 ? '+' : ''}
      {Math.round(v)}
    </span>
  )
}

/** Sortable table driven by the shared column contract. */
export default function Table({ rows, columns, sort, onSort, tierBreaks }) {
  return (
    <div className="tw">
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className={c.align === 'l' ? 'l' : ''}
                onClick={() => onSort(c.key)}
                title={`Sort by ${c.label}`}
                scope="col"
              >
                {c.label}
                {sort.key === c.key ? (
                  <span className="ind">{sort.dir === 'asc' ? '▲' : '▼'}</span>
                ) : null}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const next = rows[i + 1]
            const brk =
              tierBreaks && next && next.Pos === r.Pos && next.Tier !== r.Tier
            return (
              <tr key={`${r.Player}-${r.Rank}-${i}`} className={brk ? 'tierbreak' : ''}>
                {columns.map((c) => {
                  if (c.special === 'player')
                    return (
                      <td key={c.key} className="l">
                        <PlayerCell name={r.Player} team={r.Tm} injury={r.Injury} />
                      </td>
                    )
                  if (c.special === 'pos')
                    return (
                      <td key={c.key}>
                        <Pos p={r.Pos} />
                      </td>
                    )
                  if (c.special === 'edge')
                    return (
                      <td key={c.key}>
                        <Edge v={r.Edge} />
                      </td>
                    )
                  const cls = [
                    c.align === 'l' ? 'l' : 'n',
                    c.cls || '',
                    c.dim ? 'dim' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')
                  return (
                    <td key={c.key} className={cls}>
                      {c.fmt ? c.fmt(r[c.key]) : r[c.key]}
                    </td>
                  )
                })}
              </tr>
            )
          })}
          {rows.length === 0 ? (
            <tr>
              <td className="l dim" colSpan={columns.length}>
                No players match these filters.
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  )
}

/** Compact table for the target / fade / injury panels. */
export function MiniTable({ headers, rows }) {
  return (
    <div className="tw">
      <table>
        <thead>
          <tr>
            {headers.map((h) => (
              <th key={h.label} className={h.align === 'l' ? 'l' : ''} scope="col">
                {h.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((cells, i) => (
            <tr key={i}>
              {cells.map((c, j) => (
                <td key={j} className={headers[j].align === 'l' ? 'l' : 'n'}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export { pct, n0, n1 }
