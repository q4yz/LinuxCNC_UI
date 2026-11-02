// Source filter of the machine log.
//
// The backend serves ONE log (GET /api/v1/system/machine/log) with
// every line tagged by its source — "LinuxCNC: " or "UI: " (the
// machine backend runs inside LinuxCNC, so its output cannot be kept
// out of LinuxCNC's log files). Section headers ("--- <file> ---") stay
// in front of the lines they own; a section left empty by the filter
// is dropped.

export const LOG_FILTERS = ['all', 'linuxcnc', 'ui'] as const
export type LogFilter = (typeof LOG_FILTERS)[number]

export const LOG_FILTER_LABELS: Readonly<Record<LogFilter, string>> = Object.freeze({
  all: 'All',
  linuxcnc: 'LinuxCNC',
  ui: 'UI',
})

const PREFIXES: Readonly<Record<Exclude<LogFilter, 'all'>, string>> = Object.freeze({
  linuxcnc: 'LinuxCNC: ',
  ui: 'UI: ',
})

const SECTION_HEADER = /^--- .* ---$/

export function filterLog(text: string, filter: LogFilter): string {
  if (filter === 'all') return text
  const prefix = PREFIXES[filter]
  const sections: string[][] = []
  let header: string | null = null
  for (const line of text.split('\n')) {
    if (SECTION_HEADER.test(line)) {
      header = line
    } else if (line.startsWith(prefix)) {
      if (header !== null) {
        sections.push([header])
        header = null
      }
      if (sections.length === 0) sections.push([])
      sections[sections.length - 1].push(line)
    }
  }
  return sections.length > 0
    ? sections.map((lines) => lines.join('\n')).join('\n\n')
    : `(no ${LOG_FILTER_LABELS[filter]} lines in this log)`
}
