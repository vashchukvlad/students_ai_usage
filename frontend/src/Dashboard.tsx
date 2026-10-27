import { useEffect, useState } from 'react'
import { getDashboard, SessionExpired } from './api'
import type { DashboardData, DashboardFilters, User } from './api'

const initial: DashboardFilters = { major: '', year: '', burnout: '', metric: 'Weekly_GenAI_Hours', group_by: 'Major_Category', page: 1 }
const titles: Record<string, string> = {
  Student_ID: 'Student ID', Major_Category: 'Major', Year_of_Study: 'Year of study',
  Pre_Semester_GPA: 'GPA before semester', Post_Semester_GPA: 'GPA after semester',
  Weekly_GenAI_Hours: 'Weekly GenAI hours', Primary_Use_Case: 'Primary use case',
  Prompt_Engineering_Skill: 'Prompt engineering skill', Tool_Diversity: 'Tools used',
  Paid_Subscription: 'Paid subscription', Traditional_Study_Hours: 'Traditional study hours',
  Perceived_AI_Dependency: 'Perceived AI dependency', Institutional_Policy: 'Institutional policy',
  Anxiety_Level_During_Exams: 'Exam anxiety', Skill_Retention_Score: 'Skill retention score',
  Burnout_Risk_Level: 'Burnout risk',
}
const title = (name: string) => titles[name] ?? name.replaceAll('_', ' ')
const label = (value: string | null) => value?.replaceAll('_', ' ') ?? 'Missing'
const number = (value: number | null, digits = 2) => value === null ? '—' : value.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: digits })
const integer = (value: number) => value.toLocaleString('en-US')

export default function Dashboard({ user, busy, signOut, onExpired }: { user: User; busy: boolean; signOut: () => void; onExpired: (message: string) => void }) {
  const [filters, setFilters] = useState<DashboardFilters>(initial)
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [empty, setEmpty] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let active = true
    setLoading(true); setError('')
    getDashboard(filters).then((result) => {
      if (!active) return
      setEmpty(result.status === 'empty')
      setData(result.status === 'ready' ? result : null)
    }).catch((cause: unknown) => {
      if (!active) return
      setData(null)
      if (cause instanceof SessionExpired) onExpired(cause.message)
      else setError(cause instanceof Error ? cause.message : 'Unable to load the dashboard.')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [filters, retry, onExpired])

  function update(key: keyof DashboardFilters, value: string) {
    setFilters((previous) => ({ ...previous, [key]: value, page: 1 }))
  }
  const summary = data?.summary
  const groups = data?.groups ?? []
  const histogram = data?.histogram ?? []
  const peak = Math.max(1, ...histogram.map((bin) => bin.count))
  const filtered = !!(filters.major || filters.year || filters.burnout)

  return <main className="dashboard" aria-busy={loading}>
    <div className="dashboard-heading">
      <div><span className="eyebrow"><span className="dot" /> THE STUDENT AI OBSERVATORY</span><h1>Learning, in perspective.</h1><p className="intro">Welcome, {user.name.split(' ')[0]}. Explore the relationship between AI and student life.</p></div>
      <div className="dashboard-account"><span className="mini-avatar" aria-hidden="true">{user.name.slice(0, 1).toUpperCase()}</span><div><strong>{user.name}</strong><span>{user.email}</span></div><button className="text-button" onClick={signOut} disabled={busy}>Sign out ↗</button></div>
    </div>
    {loading && <p role="status" className="dashboard-status">Loading student insights…</p>}
    {error && <div role="alert" className="message error">{error} <button className="text-button" onClick={() => setRetry((value) => value + 1)}>Try again</button></div>}
    {empty && !loading && <section className="empty-panel"><h2>The observatory is ready for data.</h2><p>The survey dataset has not been imported yet. Ask your administrator to load it, then try again.</p><button className="secondary" onClick={() => setRetry((value) => value + 1)}>Refresh dashboard</button></section>}
    {data && <>
      <section className="filter-panel" aria-label="Filter student records">
        <div className="filter-title"><span className="filter-symbol" aria-hidden="true">☷</span><strong>Explore a group</strong><span>{integer(data.dataset.row_count)} records available</span></div>
        <div className="filter-controls">
          {([['major', 'Major_Category', 'Major', 'All majors'], ['year', 'Year_of_Study', 'Year of study', 'All years'], ['burnout', 'Burnout_Risk_Level', 'Burnout risk', 'All risk levels']] as const).map(([key, column, name, all]) =>
            <label key={key}>{name}<select aria-label={name} value={filters[key]} onChange={(event) => update(key, event.target.value)}><option value="">{all}</option>{data.dataset.columns.find((item) => item.name === column)?.values.map((value) => <option key={value} value={value}>{label(value)}</option>)}</select></label>)}
          <button className="reset-button" onClick={() => setFilters(initial)} disabled={!filtered && filters.metric === initial.metric && filters.group_by === initial.group_by && filters.page === 1}>Reset view ↺</button>
        </div>
      </section>
      <div className="section-caption"><span><strong>{integer(summary!.count)}</strong> responses {filtered ? 'in your selection' : 'across the dataset'}</span><span>{filtered ? 'Filtered view' : 'Complete dataset'} <span className="dot" /></span></div>
      {!summary!.count ? <section className="empty-panel"><h2>No students in this selection.</h2><p>Try another combination of filters to explore a different group.</p><button className="secondary" onClick={() => setFilters(initial)}>Clear filters</button></section> : <>
        <section className="metrics" aria-label="Key student metrics">
          <article className="metric-card featured"><span>Survey responses</span><strong>{integer(summary!.count)}</strong><small>{number(summary!.count / data.dataset.row_count * 100, 1)}% of all records</small></article>
          <article className="metric-card"><span>Weekly GenAI use</span><strong>{number(summary!.ai_hours, 1)}<em> hrs</em></strong><small>Average hours per student</small></article>
          <article className="metric-card"><span>Post-semester GPA</span><strong>{number(summary!.post_gpa)}</strong><small>Before semester: {number(summary!.pre_gpa)}</small></article>
          <article className="metric-card"><span>Average GPA change</span><strong>{summary!.gpa_change !== null && summary!.gpa_change >= 0 ? '+' : ''}{number(summary!.gpa_change)}</strong><small>Paired before / after records</small></article>
          <article className="metric-card"><span>High burnout risk</span><strong>{number(summary!.high_burnout / summary!.count * 100, 1)}<em>%</em></strong><small>{integer(summary!.high_burnout)} student records</small></article>
        </section>
        <section className="charts-grid" aria-label="Student survey charts">
          <article className="chart-panel">
            <div className="panel-heading"><div><span className="card-kicker">ACADEMIC PERFORMANCE</span><h2>Before & after the semester</h2></div><label className="chart-select">Compare groups<select aria-label="Compare groups" value={filters.group_by} onChange={(event) => update('group_by', event.target.value)}>{data.dataset.columns.filter((column) => column.kind === 'category').map((column) => <option key={column.name} value={column.name}>{title(column.name)}</option>)}</select></label></div>
            <div className="legend"><span><i className="before-key" /> GPA before</span><span><i className="after-key" /> GPA after</span></div>
            <div className="group-chart" role="img" aria-label={`Average GPA before and after the semester, grouped by ${title(data.group_by)}`}>
              {groups.map((group) => <div className="group-row" key={group.name ?? '__missing'}><div className="group-label"><strong>{label(group.name)}</strong><span>{integer(group.count)} records · {number(group.ai_hours, 1)} AI hrs/week</span></div><div className="paired-bars">{([['before', group.pre_gpa], ['after', group.post_gpa]] as const).map(([kind, value]) => <div className="bar-track" key={kind}><span className={`data-bar ${kind}`} style={{ width: `${Math.max(0, Math.min(100, (value ?? 0) / 4 * 100))}%` }} /><b>{number(value)}</b></div>)}</div></div>)}
            </div><p className="chart-note">Average GPA · scale 0–4 · missing values excluded</p>
          </article>
          <article className="chart-panel">
            <div className="panel-heading"><div><span className="card-kicker">PATTERNS IN THE DATA</span><h2>A closer look at the spread</h2></div><label className="chart-select">Measurement<select aria-label="Measurement" value={filters.metric} onChange={(event) => update('metric', event.target.value)}>{data.dataset.columns.filter((column) => column.kind === 'number').map((column) => <option key={column.name} value={column.name}>{title(column.name)}</option>)}</select></label></div>
            <div className="distribution-summary"><strong>{number(summary!.average)}</strong><span>average {title(data.metric).toLowerCase()}<br />{integer(summary!.measured)} measured records</span></div>
            {summary!.measured ? <><div className="histogram" role="img" aria-label={`Distribution of ${title(data.metric)} in ${histogram.length} equal-width bins`}>{histogram.map((bin, index) => <div className="histogram-column" key={index} title={`${number(bin.from, 1)}–${number(bin.to, 1)}: ${integer(bin.count)} records`}><span className="bin-count">{integer(bin.count)}</span><div className="histogram-track"><div style={{ height: `${bin.count / peak * 100}%` }} /></div><span className="bin-label">{number(bin.from, 1)}</span></div>)}</div><div className="histogram-axis"><span>{title(data.metric)}</span><span>Max {number(summary!.maximum, 1)}</span></div></> : <p className="chart-note">No measured values for this selection.</p>}
            <p className="chart-note">Equal-width bins · {integer(summary!.count - summary!.measured)} missing measurements · hover for counts</p>
          </article>
        </section>
        <section className="records-panel" aria-label="Survey records">
          <div className="panel-heading"><div><span className="card-kicker">BEHIND THE CHARTS</span><h2>Explore the student records</h2><p>Original survey fields for the current selection.</p></div><span className="record-badge">{data.dataset.columns.length} fields</span></div>
          <div className="table-scroll" tabIndex={0} role="region" aria-label="Scrollable student data table"><table><thead><tr>{data.dataset.columns.map((column) => <th key={column.name} scope="col">{title(column.name)}</th>)}</tr></thead><tbody>{data.rows.map((row) => <tr key={row.row_number}>{data.dataset.columns.map((column) => <td key={column.name}>{row.data[column.name] === null ? '—' : typeof row.data[column.name] === 'number' ? number(row.data[column.name] as number, column.name.includes('GPA') ? 3 : Number.isInteger(row.data[column.name]) ? 0 : 2) : label(String(row.data[column.name]))}</td>)}</tr>)}</tbody></table></div>
          <div className="pagination"><span>Showing {(data.page - 1) * 25 + 1}–{Math.min(data.page * 25, summary!.count)} of {integer(summary!.count)} records</span><div><button disabled={loading || data.page <= 1} onClick={() => setFilters((previous) => ({ ...previous, page: data.page - 1 }))}>← Previous</button><span>Page {data.page} of {data.pages}</span><button disabled={loading || data.page >= data.pages} onClick={() => setFilters((previous) => ({ ...previous, page: data.page + 1 }))}>Next →</button></div></div>
        </section>
      </>}
      <aside className="source-note"><span aria-hidden="true">✦</span><p><strong>Context matters.</strong> These records support exploratory analysis. Associations between AI use, GPA, and well-being do not establish cause and effect.<br /><a href={data.dataset.source_url} target="_blank" rel="noreferrer">View dataset on Kaggle ↗</a><span className="source-meta"> · {integer(data.dataset.row_count)} records · Imported {new Date(data.dataset.imported_at).toLocaleDateString('en-GB')} · SHA-256 {data.dataset.checksum.slice(0, 12)}</span></p></aside>
    </>}
  </main>
}
