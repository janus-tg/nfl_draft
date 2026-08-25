/** Excel export.
 *
 *  Exports what is currently on screen -- the same rows, the same order, after
 *  the same filters. An export that silently dumps the unfiltered table is the
 *  quickest way to make someone distrust the whole tool.
 */

/** SheetJS is ~430 KB minified and is only needed the moment someone clicks
 *  Export, so it is loaded on demand rather than shipped in the initial bundle. */
let xlsxPromise = null
const loadXLSX = () => (xlsxPromise ??= import('xlsx'))

/** Column widths from content, so the file opens readable instead of needing
 *  every column dragged out by hand. */
function autoWidth(rows, headers) {
  return headers.map((h) => {
    const longest = rows.reduce((max, r) => {
      const v = r[h]
      return Math.max(max, v == null ? 0 : String(v).length)
    }, h.length)
    return { wch: Math.min(Math.max(longest + 2, 7), 42) }
  })
}

function sheetFrom(XLSX, rows, headers) {
  const ws = XLSX.utils.json_to_sheet(rows, { header: headers })
  ws['!cols'] = autoWidth(rows, headers)
  ws['!freeze'] = { xSplit: 0, ySplit: 1 }
  if (rows.length) {
    ws['!autofilter'] = {
      ref: XLSX.utils.encode_range({
        s: { r: 0, c: 0 },
        e: { r: rows.length, c: headers.length - 1 },
      }),
    }
  }
  return ws
}

/** Build export rows straight from the column contract, so the spreadsheet
 *  carries the same columns the table shows -- as real numbers, not strings. */
export function rowsForExport(rows, columns) {
  const headers = columns.map((c) => c.label)
  const out = rows.map((r) =>
    Object.fromEntries(
      columns.map((c) => {
        const v = r[c.key]
        return [c.label, typeof v === 'number' ? Math.round(v * 1000) / 1000 : v ?? '']
      })
    )
  )
  return { rows: out, headers }
}

export async function exportBoard({ view, columns, plans, slot, extras, filename }) {
  const XLSX = await loadXLSX()
  const wb = XLSX.utils.book_new()

  const { rows, headers } = rowsForExport(view, columns)
  XLSX.utils.book_append_sheet(wb, sheetFrom(XLSX, rows, headers), 'Board')

  if (plans && plans[slot]?.length) {
    const planRows = plans[slot].map((p) => ({
      Round: p.round,
      Pick: p.pick,
      Player: p.player,
      Team: p.team,
      Pos: p.pos,
      Tier: p.tier,
      ADP: p.adp,
      'P(available)': p.pAvail,
      ProjPts: p.proj,
      VORP: p.vorp,
      Floor: p.floor,
      Ceiling: p.ceiling,
      'P(elite)': p.pElite,
      'P(bust)': p.pBust,
      Injury: p.injury || '',
      Fallbacks: (p.alts || []).map((a) => `${a.player} (${a.pos})`).join(', '),
    }))
    XLSX.utils.book_append_sheet(
      wb,
      sheetFrom(XLSX, planRows, Object.keys(planRows[0])),
      `Plan_Slot${slot}`
    )
  }

  for (const [name, data] of Object.entries(extras || {})) {
    if (!data?.length) continue
    XLSX.utils.book_append_sheet(wb, sheetFrom(XLSX, data, Object.keys(data[0])), name)
  }

  XLSX.writeFile(wb, filename)
}
