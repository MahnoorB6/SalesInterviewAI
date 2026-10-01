import { useEffect, useMemo, useState } from "react"
import {
  Bar, BarChart, CartesianGrid, Line, LineChart, PolarAngleAxis, PolarGrid,
  Radar, RadarChart, ResponsiveContainer, Tooltip, XAxis, YAxis
} from "recharts"
import "./App.css"

type AnyRow = Record<string, any>

const API = "http://127.0.0.1:8000/api"

const criteria = [
  ["Communication", "Clarity, listening, articulation and professional dialogue.", "communication"],
  ["Confidence", "Composure, ownership of answers and professional presence.", "confidence"],
  ["Sales Knowledge", "Understanding of sales process, discovery, qualification and pipeline.", "sales_knowledge"],
  ["Lead Qualification", "Ability to identify needs, fit, intent, budget and buying signals.", "lead_qualification"],
  ["Objection Handling", "Ability to acknowledge, diagnose and respond to customer objections.", "objection_handling"],
  ["Persuasion", "Ability to communicate value and influence a prospect appropriately.", "persuasion"],
  ["Closing Ability", "Ability to create next steps, ask for commitment and move toward close.", "closing_ability"],
] as const

const nav = [
  ["Dashboard", "dashboard"],
  ["Candidates", "candidates"],
  ["Interviews", "interviews"],
  ["Calendar", "schedule"],
  ["Evaluations", "evaluations"],
]

const token = () => localStorage.getItem("access_token") || ""

function authHeaders(extra: Record<string, string> = {}) {
  const t = token()
  return t ? { ...extra, Authorization: \`Bearer \${t}\` } : extra
}

async function get(path: string) {
  const r = await fetch(\`\${API}\${path}\`, { headers: authHeaders() })
  if (r.status === 401) {
    localStorage.removeItem("access_token")
    window.dispatchEvent(new Event("auth-expired"))
  }
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}

async function post(path: string, body: any) {
  const r = await fetch(\`\${API}\${path}\`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  })
  if (r.status === 401) {
    localStorage.removeItem("access_token")
    window.dispatchEvent(new Event("auth-expired"))
  }
  if (!r.ok) {
    let detail = \`Request failed (\${r.status})\`
    try { detail = (await r.json()).detail || detail } catch {}
    throw new Error(detail)
  }
  return r.json()
}

function navigate(page: string, params = "") {
  const target = page === "dashboard" ? "/" : \`/?page=\${page}\${params}\`
  window.history.pushState({}, "", target)
  window.dispatchEvent(new PopStateEvent("popstate"))
}

function currentPage() {
  return new URLSearchParams(window.location.search).get("page") || "dashboard"
}

function Login({ onLogin }: { onLogin: () => void }) {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError("")
    try {
      const body = new URLSearchParams()
      body.set("username", email)
      body.set("password", password)

      const response = await fetch(\`\${API}/auth/login\`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
      })

      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || "Invalid email or password")

      localStorage.setItem("access_token", data.access_token)
      onLogin()
    } catch (e: any) {
      setError(e.message || "Unable to sign in.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-glow glow-one" />
      <div className="login-glow glow-two" />
      <section className="login-card">
        <div className="login-logo">S</div>
        <div className="login-brand">SalesInterviewAI</div>
        <p className="login-kicker">AI-POWERED SALES INTERVIEW PLATFORM</p>
        <h1>Welcome back</h1>
        <p className="login-subtitle">Sign in to your recruiter workspace and manage interviews with Alena.</p>

        <form onSubmit={submit} className="login-form">
          <label>Email
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" required />
          </label>
          <label>Password
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Enter your password" required />
          </label>
          {error && <div className="login-error">{error}</div>}
          <button className="primary-button login-submit" disabled={busy}>
            {busy ? "Signing in..." : "Sign in"}
          </button>
        </form>
        <div className="login-footer">Secure recruiter workspace · SalesInterviewAI</div>
      </section>
    </div>
  )
}

function Layout({ page, children, onLogout }: { page: string, children: React.ReactNode, onLogout: () => void }) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand brand-button" onClick={() => navigate("dashboard")}>
          <div className="brand-mark">S</div>
          <div><b>SalesInterviewAI</b><small>AI-powered hiring</small></div>
        </button>

        <div className="workspace-label">WORKSPACE</div>
        <nav>
          {nav.map(([label, id]) => (
            <button key={id} onClick={() => navigate(id)} className={page === id ? "active" : ""}>
              <span className="nav-dot" />{label}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="alena-card">
            <div><span className="online" /> Alena is ready</div>
            <p>AI interviewer connected to the interview workflow.</p>
          </div>
          <button className="logout-button" onClick={onLogout}>Sign out</button>
          <small>SalesInterviewAI · Recruiter workspace</small>
        </div>
      </aside>
      <main className="main-content page-transition" key={page}>{children}</main>
    </div>
  )
}

function Header({ eyebrow, title, subtitle, action }: { eyebrow: string, title: string, subtitle: string, action?: React.ReactNode }) {
  return <header className="topbar">
    <div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p className="page-subtitle">{subtitle}</p></div>
    {action && <div className="topbar-actions">{action}</div>}
  </header>
}

function Button({ children, secondary = false, onClick }: { children: React.ReactNode, secondary?: boolean, onClick?: () => void }) {
  return <button className={secondary ? "secondary-button" : "primary-button"} onClick={onClick}>{children}</button>
}

function Status({ value }: { value: string }) {
  const s = String(value || "pending").toLowerCase()
  return <span className={\`status \${s.replaceAll("_", "-")}\`}>{s.replaceAll("_", " ")}</span>
}

function PanelTitle({ title, sub }: { title: string, sub: string }) {
  return <div className="panel-header"><div><h2>{title}</h2><p>{sub}</p></div></div>
}

function Chart({ children, h = 250 }: { children: React.ReactElement, h?: number }) {
  return <div className="chart-wrap"><ResponsiveContainer width="100%" height={h}>{children}</ResponsiveContainer></div>
}

function Dashboard() {
  const [stats, setStats] = useState<AnyRow | null>(null)
  const [ints, setInts] = useState<AnyRow[]>([])
  const [evals, setEvals] = useState<AnyRow[]>([])
  const [error, setError] = useState("")

  useEffect(() => {
    Promise.all([get("/dashboard/stats"), get("/dashboard/interviews"), get("/evaluations/")])
      .then(([a, b, c]) => { setStats(a); setInts(Array.isArray(b) ? b : []); setEvals(Array.isArray(c) ? c : []) })
      .catch(e => setError(e.message === "401" ? "Your session has expired. Please sign in again." : "Unable to load dashboard data."))
  }, [])

  const vals = {
    c: stats?.total_candidates || 0,
    s: stats?.scheduled_interviews || 0,
    i: stats?.in_progress_interviews || 0,
    d: stats?.completed_interviews || 0,
    score: stats?.average_score || 0
  }

  const monthly = useMemo(() => {
    const m = new Map<string, AnyRow>()
    ints.forEach(x => {
      const d = new Date(x.scheduled_at)
      if (isNaN(d.getTime())) return
      const k = d.toLocaleDateString("en-US", { month: "short" })
      const r = m.get(k) || { month: k, interviews: 0, completed: 0 }
      r.interviews++
      if (x.status === "completed") r.completed++
      m.set(k, r)
    })
    return [...m.values()].slice(-8)
  }, [ints])

  const radar = criteria.map(([name, , key]) => {
    const scores = evals.map(x => Number(x[key])).filter(Number.isFinite)
    return { subject: name, score: scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : 0 }
  })

  return <>
    <Header eyebrow="RECRUITER ANALYTICS" title="Dashboard" subtitle="A visual overview of your hiring pipeline and candidate performance."
      action={<><Button secondary onClick={() => navigate("schedule")}>View calendar</Button><Button onClick={() => navigate("candidates")}>+ New candidate</Button></>} />
    {error && <div className="notice">{error}</div>}
    <section className="stats-grid">
      {[[ "Candidates", vals.c, "Pipeline" ], [ "Scheduled", vals.s, "Upcoming" ], [ "Completed", vals.d, "Completed" ], [ "Average score", vals.score ? Number(vals.score).toFixed(1) : "—", "Performance" ]].map(x =>
        <article className="stat-card" key={x[0]}><div className="stat-card-top"><span className="stat-icon">◆</span><span className="trend">{x[2]}</span></div><div className="stat-value">{x[1]}</div><div className="stat-label">{x[0]}</div><div className="stat-helper">Live database metric</div></article>
      )}
    </section>
    <section className="chart-grid">
      <article className="panel chart-panel wide"><PanelTitle title="Interview activity" sub="Scheduled and completed interviews over time."/><Chart h={270}><LineChart data={monthly}><CartesianGrid stroke="#eee9ef" strokeDasharray="4 4" vertical={false}/><XAxis dataKey="month" axisLine={false} tickLine={false}/><YAxis allowDecimals={false} axisLine={false} tickLine={false}/><Tooltip/><Line dataKey="interviews" stroke="#8b62a1" strokeWidth={3}/><Line dataKey="completed" stroke="#d786a2" strokeWidth={3}/></LineChart></Chart></article>
      <article className="panel chart-panel"><PanelTitle title="Interview pipeline" sub="Current status distribution."/><Chart h={270}><BarChart data={[{name:"Scheduled",v:vals.s},{name:"In progress",v:vals.i},{name:"Completed",v:vals.d}]}><CartesianGrid stroke="#eee9ef" strokeDasharray="4 4" vertical={false}/><XAxis dataKey="name" axisLine={false} tickLine={false}/><YAxis allowDecimals={false} axisLine={false} tickLine={false}/><Tooltip/><Bar dataKey="v" fill="#9b70b4" radius={[7,7,2,2]}/></BarChart></Chart></article>
      <article className="panel chart-panel wide"><PanelTitle title="Sales competency profile" sub="Average score by evaluation criterion."/><Chart h={300}><RadarChart data={radar}><PolarGrid/><PolarAngleAxis dataKey="subject" tick={{fontSize:9}}/><Radar dataKey="score" stroke="#9b70b4" fill="#c9a6d7" fillOpacity={.55}/><Tooltip/></RadarChart></Chart></article>
      <article className="panel"><PanelTitle title="Evaluation criteria" sub="The standardized sales interview rubric."/><div className="criteria-list">{criteria.map(([n,d])=><div className="criteria-row" key={n}><b>{n}</b><span>{d}</span></div>)}</div></article>
    </section>
  </>
}

function Candidates() {
  const [rows, setRows] = useState<AnyRow[]>([])
  const [q, setQ] = useState("")
  useEffect(() => { get("/candidates/").then(x => setRows(Array.isArray(x) ? x : x?.items || [])).catch(() => setRows([])) }, [])
  const filtered = rows.filter(x => JSON.stringify(x).toLowerCase().includes(q.toLowerCase()))
  return <>
    <Header eyebrow="TALENT PIPELINE" title="Candidates" subtitle="Manage candidates, resumes and interview readiness." action={<Button onClick={() => navigate("schedule")}>Schedule interview</Button>} />
    <section className="stats-grid mini">{[["Total", rows.length], ["With resume", rows.filter(x => x.resume_path || x.resume_text).length], ["Roles", new Set(rows.map(x => x.latest_role).filter(Boolean)).size], ["Ready", "AI"]].map(x => <article className="stat-card" key={String(x[0])}><div className="stat-label">{x[0]}</div><div className="stat-value small">{x[1]}</div></article>)}</section>
    <article className="panel table-panel"><div className="panel-header"><div><h2>Candidate directory</h2><p>Search and review your candidate pipeline.</p></div><input className="search" placeholder="Search candidates..." value={q} onChange={e => setQ(e.target.value)} /></div>
      <div className="table-scroll"><table><thead><tr><th>Candidate</th><th>Latest role</th><th>Company</th><th>Resume</th><th>Action</th></tr></thead><tbody>{filtered.map(x => <tr key={x.id}><td><b>{x.name || x.full_name || \`Candidate #\${x.id}\`}</b><small>{x.email || "No email"}</small></td><td>{x.latest_role || "—"}</td><td>{x.latest_company || "—"}</td><td>{x.resume_path || x.resume_text ? <span className="pill good">Available</span> : <span className="pill">Missing</span>}</td><td><Button secondary onClick={() => navigate("schedule", \`&candidate=\${x.id}\`)}>Schedule</Button></td></tr>)}</tbody></table>{!filtered.length && <Empty text="No candidates found."/>}</div>
    </article>
  </>
}

function Interviews() {
  const [rows, setRows] = useState<AnyRow[]>([])
  const [filter, setFilter] = useState("all")
  useEffect(() => { get("/interviews/").then(x => setRows(Array.isArray(x) ? x : x?.items || [])).catch(() => {}) }, [])
  const data = filter === "all" ? rows : rows.filter(x => x.status === filter)
  return <>
    <Header eyebrow="INTERVIEW OPERATIONS" title="Interviews" subtitle="Monitor every scheduled and completed AI interview." action={<Button onClick={() => navigate("schedule")}>+ Schedule interview</Button>} />
    <div className="filter-tabs">{["all","scheduled","in_progress","completed","cancelled"].map(x => <button className={filter === x ? "selected" : ""} onClick={() => setFilter(x)} key={x}>{x.replace("_"," ")}</button>)}</div>
    <article className="panel table-panel"><PanelTitle title="Interview pipeline" sub={\`\${data.length} interviews in this view.\`} />
      <div className="table-scroll"><table><thead><tr><th>Candidate</th><th>Scheduled</th><th>Status</th><th>Meet</th><th>Evaluation</th></tr></thead><tbody>{data.map(x => <tr key={x.id}><td><b>{x.candidate_name || x.candidate?.name || \`Candidate #\${x.candidate_id}\`}</b><small>Interview #{x.id}</small></td><td>{x.scheduled_at ? new Date(x.scheduled_at).toLocaleString() : "—"}</td><td><Status value={x.status}/></td><td>{x.meet_link ? <a className="link" href={x.meet_link} target="_blank" rel="noreferrer">Open Meet</a> : "—"}</td><td><Button secondary onClick={() => navigate("evaluations", \`&interview=\${x.id}\`)}>Evaluate</Button></td></tr>)}</tbody></table>{!data.length && <Empty text="No interviews in this status."/>}</div>
    </article>
  </>
}

function Schedule() {
  const [cands, setCands] = useState<AnyRow[]>([])
  const [candidate, setCandidate] = useState(new URLSearchParams(location.search).get("candidate") || "")
  const [date, setDate] = useState("")
  const [time, setTime] = useState("10:00")
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")
  useEffect(() => { get("/candidates/").then(x => setCands(Array.isArray(x) ? x : x?.items || [])).catch(() => {}) }, [])
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setMsg("")
    try { await post("/interviews/", { candidate_id: Number(candidate), scheduled_at: \`\${date}T\${time}:00\` }); setMsg("Interview scheduled successfully.") }
    catch (e: any) { setMsg(e.message || "Could not schedule the interview.") }
    finally { setBusy(false) }
  }
  return <>
    <Header eyebrow="INTERVIEW CALENDAR" title="Calendar" subtitle="Create an interview and let the workflow handle the Google Meet session."/>
    <div className="schedule-layout"><article className="panel form-panel"><PanelTitle title="New interview" sub="Choose a candidate and interview time."/>
      <form onSubmit={submit}><label>Candidate<select value={candidate} onChange={e => setCandidate(e.target.value)} required><option value="">Select candidate</option>{cands.map(x => <option value={x.id} key={x.id}>{x.name || x.full_name || \`Candidate #\${x.id}\`}</option>)}</select></label>
      <label>Date<input type="date" value={date} onChange={e => setDate(e.target.value)} required/></label><label>Time<input type="time" value={time} onChange={e => setTime(e.target.value)} required/></label>
      <div className="schedule-summary"><b>Workflow</b><span>Google Calendar → Meet link → Alena interview → evaluation</span></div>
      <button className="primary-button full" disabled={busy}>{busy ? "Scheduling..." : "Schedule interview"}</button>{msg && <div className="notice">{msg}</div>}</form>
    </article><article className="panel"><PanelTitle title="Scheduling checklist" sub="What happens after you schedule."/><div className="steps">{["Candidate is attached to the interview","Calendar event and Meet link are created","Scheduler starts the Meet bot at interview time","Alena conducts the interview","Transcript and evaluation become available"].map((x,i) => <div className="step" key={x}><span>{i+1}</span><div><b>{x}</b><small>Automated workflow</small></div></div>)}</div></article></div>
  </>
}

function Evaluations() {
  const [evaluations, setEvaluations] = useState<AnyRow[]>([])
  const [interviews, setInterviews] = useState<AnyRow[]>([])
  const [selected, setSelected] = useState<AnyRow | null>(null)
  const [mode, setMode] = useState<"pending" | "history">("pending")
  const [message, setMessage] = useState("")

  async function load() {
    try {
      const [e, i] = await Promise.all([get("/evaluations/"), get("/interviews/")])
      setEvaluations(Array.isArray(e) ? e : [])
      setInterviews(Array.isArray(i) ? i : i?.items || [])
    } catch {}
  }

  useEffect(() => {
    load()
    const requested = new URLSearchParams(location.search).get("interview")
    if (requested) setSelected({ interview_id: Number(requested), pending: true })
  }, [])

  const evaluatedIds = new Set(evaluations.map(x => Number(x.interview_id)))
  const pending = interviews.filter(x => x.status === "completed" && !evaluatedIds.has(Number(x.id)))
  const avg = (key: string) => {
    const a = evaluations.map(x => Number(x[key])).filter(Number.isFinite)
    return a.length ? Math.round(a.reduce((s,n) => s+n, 0) / a.length) : 0
  }

  async function generate(interviewId: number) {
    setMessage("")
    try {
      setMessage("Generating evaluation from the interview transcript...")
      const result = await post(\`/evaluations/\${interviewId}/generate\`, {})
      await load()
      setSelected(result)
      setMode("history")
      setMessage("Evaluation generated successfully.")
    } catch (e: any) {
      setMessage(e.message || "Evaluation could not be generated.")
    }
  }

  async function openDetails(evaluation: AnyRow) {
    try {
      const detail = await get(\`/evaluations/interview/\${evaluation.interview_id}/details\`)
      setSelected({ ...detail.evaluation, interview: detail.interview, candidate: detail.candidate, interview_id: evaluation.interview_id })
    } catch { setSelected(evaluation) }
  }

  return <>
    <Header eyebrow="AI ASSESSMENT" title="Evaluations" subtitle="Evaluate completed interviews using the standardized SalesInterviewAI rubric." />
    <div className="evaluation-tabs">
      <button className={mode === "pending" ? "selected" : ""} onClick={() => setMode("pending")}>Pending evaluation <b>{pending.length}</b></button>
      <button className={mode === "history" ? "selected" : ""} onClick={() => setMode("history")}>Evaluation history <b>{evaluations.length}</b></button>
    </div>

    {message && <div className="notice">{message}</div>}

    {mode === "pending" ? <article className="panel table-panel">
      <PanelTitle title="Interviews awaiting evaluation" sub="Completed interviews without an evaluation are shown here."/>
      <div className="table-scroll"><table><thead><tr><th>Candidate</th><th>Interview</th><th>Completed</th><th>Action</th></tr></thead><tbody>
        {pending.map(x => <tr key={x.id}><td><b>{x.candidate_name || x.candidate?.name || \`Candidate #\${x.candidate_id}\`}</b><small>Interview #{x.id}</small></td><td>{x.position || "Sales interview"}</td><td>{x.completed_at ? new Date(x.completed_at).toLocaleString() : "Completed"}</td><td><Button onClick={() => generate(Number(x.id))}>Evaluate</Button></td></tr>)}
      </tbody></table>{!pending.length && <Empty text="No interviews are waiting for evaluation."/>}</div>
    </article> : <article className="panel table-panel">
      <PanelTitle title="Evaluation history" sub="Open any completed evaluation for the full report."/>
      <div className="table-scroll"><table><thead><tr><th>Interview</th><th>Candidate</th><th>Score</th><th>Result</th><th>Recruiter review</th><th>Action</th></tr></thead><tbody>
        {evaluations.map(x => <tr key={x.id}><td>#{x.interview_id}</td><td><b>{x.candidate_name || "Candidate evaluation"}</b></td><td><strong>{x.overall_score ?? "—"}/100</strong></td><td><Status value={x.result || "pending"}/></td><td>{x.recruiter_status || "pending"}</td><td><Button secondary onClick={() => openDetails(x)}>View report</Button></td></tr>)}
      </tbody></table>{!evaluations.length && <Empty text="No evaluations available yet."/>}</div>
    </article>}

    <section className="evaluation-bottom">
      <article className="panel"><PanelTitle title="Evaluation criteria" sub="Every interview is assessed against the same seven sales competencies."/>
        <div className="criteria-list">{criteria.map(([n,d]) => <div className="criteria-row" key={n}><b>{n}</b><span>{d}</span></div>)}</div>
      </article>
      <article className="panel"><PanelTitle title="Competency averages" sub="Average score across evaluation history."/>
        <Chart h={330}><RadarChart data={criteria.map(([name,,key]) => ({subject:name, score:avg(key)}))}><PolarGrid/><PolarAngleAxis dataKey="subject" tick={{fontSize:9}}/><Radar dataKey="score" stroke="#9b70b4" fill="#c9a6d7" fillOpacity={.55}/><Tooltip/></RadarChart></Chart>
      </article>
    </section>

    {selected && <EvaluationModal data={selected} onClose={() => setSelected(null)} />}
  </>
}

function EvaluationModal({ data, onClose }: { data: AnyRow, onClose: () => void }) {
  const [busy, setBusy] = useState(false)
  const [review, setReview] = useState("")
  async function recruiterAction(action: "approve" | "reject") {
    if (!data.id) return
    setBusy(true)
    try {
      const result = await post(\`/evaluations/\${data.id}/\${action}\`, {})
      setReview(result.message || \`Evaluation \${action}d.\`)
    } catch (e: any) { setReview(e.message || "Unable to update recruiter review.") }
    finally { setBusy(false) }
  }

  return <div className="modal-backdrop" onClick={onClose}><div className="modal large-modal" onClick={e => e.stopPropagation()}>
    <div className="modal-head"><div><span className="eyebrow">EVALUATION REPORT</span><h2>{data.candidate?.name || \`Interview #\${data.interview_id}\`}</h2><p className="modal-subtitle">Interview #{data.interview_id}</p></div><button onClick={onClose}>×</button></div>
    <div className="score-hero"><strong>{data.overall_score ?? "—"}</strong><span>/ 100</span><Status value={data.result || "pending"}/></div>
    <div className="detail-grid">{criteria.map(([n,,k]) => <div className="detail-score" key={k}><span>{n}</span><b>{data[k] ?? "—"}</b><div className="bar"><i style={{width:\`\${Math.min(Number(data[k]) || 0, 100)}%\`}}/></div></div>)}</div>
    <div className="report-grid"><div><h3>Strengths</h3><p>{data.strengths || "Not provided."}</p></div><div><h3>Weaknesses</h3><p>{data.weaknesses || "Not provided."}</p></div><div><h3>Recommendation</h3><p>{data.recommendation || "Not provided."}</p></div></div>
    <div className="review-actions"><span>Recruiter decision: <b>{data.recruiter_status || "pending"}</b></span><div><button className="secondary-button" disabled={busy} onClick={() => recruiterAction("reject")}>Reject</button><button className="primary-button" disabled={busy} onClick={() => recruiterAction("approve")}>Approve</button></div></div>
    {review && <div className="notice">{review}</div>}
  </div></div>
}

function Empty({ text }: { text: string }) {
  return <div className="empty"><div>◎</div><b>{text}</b><span>Data will appear here when the workflow has records.</span></div>
}

export default function App() {
  const [loggedIn, setLoggedIn] = useState(Boolean(token()))
  const [page, setPage] = useState(currentPage())

  useEffect(() => {
    const sync = () => setPage(currentPage())
    const expired = () => { setLoggedIn(false); setPage("dashboard") }
    window.addEventListener("popstate", sync)
    window.addEventListener("auth-expired", expired)
    return () => { window.removeEventListener("popstate", sync); window.removeEventListener("auth-expired", expired) }
  }, [])

  function logout() {
    localStorage.removeItem("access_token")
    setLoggedIn(false)
    window.history.replaceState({}, "", "/")
  }

  if (!loggedIn) return <Login onLogin={() => { setLoggedIn(true); navigate("dashboard") }} />

  const body =
    page === "candidates" ? <Candidates/> :
    page === "interviews" ? <Interviews/> :
    page === "schedule" ? <Schedule/> :
    page === "evaluations" ? <Evaluations/> :
    <Dashboard/>

  return <Layout page={page} onLogout={logout}>{body}</Layout>
}
