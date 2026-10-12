import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { ReactElement, ReactNode } from "react"
import {
  Bar, BarChart, CartesianGrid, Line, LineChart, PolarAngleAxis, PolarGrid,
  Radar, RadarChart, ResponsiveContainer, Tooltip, XAxis, YAxis
} from "recharts"
import "./App.css"
import { INTERVIEW_STATUSES, type InterviewStatus } from "./types"

type AnyRow = Record<string, any>

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000/api"

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
  ["Schedule", "schedule"],
  ["Evaluations", "evaluations"],
]

const token = () => localStorage.getItem("access_token") || ""

function authHeaders(extra: Record<string, string> = {}) {
  const t = token()
  return t ? { ...extra, Authorization: `Bearer ${t}` } : extra
}

async function get(path: string) {
  const r = await fetch(`${API}${path}`, { headers: authHeaders() })
  if (r.status === 401) {
    localStorage.removeItem("access_token")
    window.dispatchEvent(new Event("auth-expired"))
  }
  if (!r.ok) throw new Error(String(r.status))
  return r.json()
}

async function post(path: string, body: any) {
  const r = await fetch(`${API}${path}`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  })
  if (r.status === 401) {
    localStorage.removeItem("access_token")
    window.dispatchEvent(new Event("auth-expired"))
  }
  if (!r.ok) {
    let detail = `Request failed (${r.status})`
    try {
      const body = await r.json()
      const value = body.detail
      detail = Array.isArray(value)
        ? value.map(item => [item.loc?.slice(-1)[0], item.msg].filter(Boolean).join(": ")).join("; ") || detail
        : typeof value === "string" ? value : detail
    } catch {}
    throw new Error(detail)
  }
  return r.json()
}

async function getText(path: string) {
  const r = await fetch(`${API}${path}`, { headers: authHeaders() })
  if (r.status === 401) {
    localStorage.removeItem("access_token")
    window.dispatchEvent(new Event("auth-expired"))
  }
  if (!r.ok) throw new Error(String(r.status))
  return r.text()
}

async function uploadCandidateResume(candidateId: number, file: File) {
  const form = new FormData()
  form.append("file", file)
  const response = await fetch(`${API}/candidates/${candidateId}/resume`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
  })
  if (response.status === 401) {
    localStorage.removeItem("access_token")
    window.dispatchEvent(new Event("auth-expired"))
  }
  if (!response.ok) {
    let message = `Resume upload failed (${response.status})`
    try {
      const body = await response.json()
      const detail = body.detail
      message = Array.isArray(detail)
        ? detail.map(item => [item.loc?.slice(-1)[0], item.msg].filter(Boolean).join(": ")).join("; ") || message
        : typeof detail === "string" ? detail : message
    } catch {}
    throw new Error(message)
  }
  return response.json()
}

function navigate(page: string, params = "") {
  const target = page === "dashboard" ? "/" : `/?page=${page}${params}`
  window.history.pushState({}, "", target)
  window.dispatchEvent(new PopStateEvent("popstate"))
}

function SplashScreen() {
  return (
    <div className="splash-screen">
      <div className="splash-name">SalesInterviewAI</div>
    </div>
  )
}

function currentPage() {
  return new URLSearchParams(window.location.search).get("page") || "dashboard"
}

function GoogleGate({ onConnected }: { onConnected: (accessToken: string) => void }) {
  const [busy, setBusy] = useState(false)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    const code = new URLSearchParams(window.location.hash.slice(1)).get("oauth_code")
    if (code) {
      window.history.replaceState({}, "", "/")
      fetch(`${API}/google/exchange`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }) })
        .then(async response => { if (!response.ok) throw new Error("Google sign-in code expired. Please connect again."); return response.json() })
        .then(data => onConnected(data.access_token))
        .catch(error => setError(error.message || "Google sign-in failed."))
      return
    }

    get("/google/status")
      .then(data => setConnected(Boolean(data.connected)))
      .catch(() => {})
  }, [onConnected])

  function connectGoogle() {
    setBusy(true)
    setError("")
    window.location.href = `${API}/google/login`
  }

  return (
    <div className="google-gate">
      <div className="google-gate-glow gate-glow-one" />
      <div className="google-gate-glow gate-glow-two" />
      <section className="google-gate-card">
        <div className="google-gate-brand">SalesInterviewAI</div>
        <p className="google-gate-kicker">RECRUITER WORKSPACE</p>
        <h1>Connect Google</h1>
        <p className="google-gate-subtitle">
          Use your Google account to access SalesInterviewAI. This connects Google Calendar for Meet scheduling and Gmail for interview, approval and rejection emails.
        </p>
        <button className="primary-button google-gate-button" onClick={connectGoogle} disabled={busy}>
          {busy ? "Connecting..." : connected ? "Continue with Google" : "Connect Google account"}
        </button>
        {error && <div className="login-error">{error}</div>}
        <div className="google-gate-note">One Google connection replaces the separate email/password login.</div>
      </section>
    </div>
  )
}

function Layout({ page, children, onLogout }: { page: string, children: ReactNode, onLogout: () => void }) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand brand-button" onClick={() => navigate("dashboard")}>
          <b>SalesInterviewAI</b>
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
  return <span className={`status ${s.replaceAll("_", "-")}`}>{s.replaceAll("_", " ")}</span>
}

function PanelTitle({ title, sub }: { title: string, sub: string }) {
  return <div className="panel-header"><div><h2>{title}</h2><p>{sub}</p></div></div>
}

function Chart({ children, h = 250 }: { children: ReactElement, h?: number }) {
  return <div className="chart-wrap"><ResponsiveContainer width="100%" height={h}>{children}</ResponsiveContainer></div>
}

function Dashboard() {
  const [stats, setStats] = useState<AnyRow | null>(null)
  const [ints, setInts] = useState<AnyRow[]>([])
  const [evals, setEvals] = useState<AnyRow[]>([])
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(true)

  const loadDashboard = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const [a, b, c] = await Promise.all([get("/dashboard/stats"), get("/dashboard/interviews"), get("/evaluations/")])
      setStats(a)
      setInts(Array.isArray(b) ? b : [])
      setEvals(Array.isArray(c) ? c : [])
    } catch (e: any) {
      setError(e.message === "401" ? "Your session has expired. Please sign in again." : "Unable to load dashboard data.")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void loadDashboard() }, [loadDashboard])

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
    const scores = evals.map(x => x[key]).filter(v => v !== null && v !== undefined && v !== "").map(Number).filter(Number.isFinite)
    return { subject: name, score: scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : null }
  })

  return <>
    <Header eyebrow="RECRUITER ANALYTICS" title="Dashboard" subtitle="A visual overview of your hiring pipeline and candidate performance."
      action={<><Button secondary onClick={() => navigate("schedule")}>View schedule</Button><Button onClick={() => navigate("candidates")}>+ New candidate</Button></>} />
    {loading && <div className="loading-state" role="status">Loading dashboard data...</div>}
    {error && <div className="error-state" role="alert">{error}<button className="secondary-button" onClick={() => void loadDashboard()}>Retry</button></div>}
    {!loading && !error && <>
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
    </>}
  </>
}

function Candidates() {
  const [rows, setRows] = useState<AnyRow[]>([])
  const [q, setQ] = useState("")
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState("")
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [resume, setResume] = useState<File | null>(null)
  const [resumeError, setResumeError] = useState("")
  const [createdCandidateId, setCreatedCandidateId] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState("")
  const [success, setSuccess] = useState("")

  const refreshCandidates = useCallback(async () => {
    setListLoading(true)
    setListError("")
    try {
      const result = await get("/candidates/")
      setRows(Array.isArray(result) ? result : result?.items || [])
    } catch (error) {
      setListError(error instanceof Error ? error.message : "Could not load candidates.")
    } finally {
      setListLoading(false)
    }
  }, [])

  useEffect(() => { void refreshCandidates() }, [refreshCandidates])

  function resetForm() {
    setName("")
    setEmail("")
    setResume(null)
    setResumeError("")
    setCreatedCandidateId(null)
    setFormError("")
    setShowForm(false)
  }

  function selectResume(file: File | null): boolean {
    setResumeError("")
    setFormError("")
    if (!file) {
      setResume(null)
      return true
    }
    const filename = file.name.toLowerCase()
    if (!filename.endsWith(".pdf") && !filename.endsWith(".docx")) {
      setResume(null)
      setResumeError("Choose a PDF or DOCX file. DOC files are not supported.")
      return false
    }
    if (!file.size) {
      setResume(null)
      setResumeError("The selected resume file is empty.")
      return false
    }
    if (file.size > 10 * 1024 * 1024) {
      setResume(null)
      setResumeError("The resume must be 10 MB or smaller.")
      return false
    }
    setResume(file)
    return true
  }

  async function submitCandidate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError("")
    setSuccess("")
    if (!name.trim() || !email.trim()) {
      setFormError("Enter the candidate’s name and email address.")
      return
    }
    if (resumeError) {
      setFormError(resumeError)
      return
    }
    if (createdCandidateId && !resume) {
      setFormError("Choose a PDF or DOCX resume to finish this candidate’s upload.")
      return
    }

    setBusy(true)
    try {
      let candidateId = createdCandidateId
      if (!candidateId) {
        const candidate = await post("/candidates/", { name: name.trim(), email: email.trim() })
        candidateId = Number(candidate.id)
        if (!candidateId) throw new Error("Candidate was created, but the API did not return its ID.")
      }

      if (resume) {
        setCreatedCandidateId(candidateId)
        try {
          await uploadCandidateResume(candidateId, resume)
        } catch (error) {
          await refreshCandidates()
          const message = error instanceof Error ? error.message : "Unknown upload error"
          setFormError(`Candidate created, but the resume upload failed: ${message} Select the file again and retry.`)
          return
        }
      }

      await refreshCandidates()
      setSuccess(resume ? "Candidate created and resume uploaded successfully." : "Candidate created successfully.")
      resetForm()
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Candidate creation failed. Please try again.")
    } finally {
      setBusy(false)
    }
  }

  const filtered = rows.filter(x => JSON.stringify(x).toLowerCase().includes(q.toLowerCase()))
  return <>
    <Header eyebrow="TALENT PIPELINE" title="Candidates" subtitle="Manage candidates, resumes and interview readiness." action={<><button className="secondary-button" onClick={() => navigate("schedule")}>Schedule interview</button><button className="primary-button" onClick={() => { setSuccess(""); setShowForm(true) }}>{createdCandidateId ? "Finish resume upload" : "+ Add Candidate"}</button></>} />
    {success && <div className="candidate-alert candidate-alert-success" role="status" aria-live="polite">{success}</div>}
    {showForm && <article className="panel form-panel candidate-form-panel">
      <div className="panel-header candidate-form-heading"><div><h2>{createdCandidateId ? "Finish resume upload" : "Add candidate"}</h2><p>{createdCandidateId ? "Candidate details are saved. Upload a resume to complete the process." : "Add a candidate to your talent pipeline."}</p></div><button className="secondary-button candidate-cancel" type="button" onClick={() => setShowForm(false)} disabled={busy}>Close</button></div>
      <form onSubmit={submitCandidate}>
        <div className="candidate-form-grid">
          <label>Candidate name<input value={name} onChange={event => setName(event.target.value)} placeholder="Full name" autoComplete="name" required maxLength={150} readOnly={Boolean(createdCandidateId)} /></label>
          <label>Candidate email<input type="email" value={email} onChange={event => setEmail(event.target.value)} placeholder="name@example.com" autoComplete="email" required readOnly={Boolean(createdCandidateId)} /></label>
        </div>
        <label>Resume <span className="candidate-optional">(optional)</span><input className="candidate-file-input" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" required={Boolean(createdCandidateId)} onChange={event => { const file = event.target.files?.[0]; if (!file) setResume(null); else if (!selectResume(file)) event.target.value = "" }} /></label>
        <p className="candidate-file-note">PDF or DOCX · maximum 10 MB. DOC files are not supported.</p>
        {resume && <p className="candidate-file-selected">Selected: {resume.name}</p>}
        {resumeError && <div className="candidate-alert candidate-alert-error" role="alert">{resumeError}{!createdCandidateId && <button className="candidate-clear-file" type="button" onClick={() => setResumeError("")}>Continue without a resume</button>}</div>}
        {formError && <div className="candidate-alert candidate-alert-error" role="alert">{formError}</div>}
        <div className="candidate-form-actions"><button className="primary-button" type="submit" disabled={busy}>{busy ? (createdCandidateId ? "Uploading resume…" : "Saving candidate…") : (createdCandidateId ? "Retry resume upload" : "Create candidate")}</button><button className="secondary-button" type="button" onClick={() => setShowForm(false)} disabled={busy}>Close</button></div>
      </form>
    </article>}
    <section className="stats-grid mini">{[["Total", rows.length], ["With resume", rows.filter(x => x.resume_uploaded).length], ["Roles", new Set(rows.map(x => x.latest_role).filter(Boolean)).size], ["Ready", "AI"]].map(x => <article className="stat-card" key={String(x[0])}><div className="stat-label">{x[0]}</div><div className="stat-value small">{x[1]}</div></article>)}</section>
    <article className="panel table-panel"><div className="panel-header"><div><h2>Candidate directory</h2><p>Search and review your candidate pipeline.</p></div><input className="search" placeholder="Search candidates..." value={q} onChange={e => setQ(e.target.value)} /></div>
      {listError && <div className="candidate-alert candidate-alert-error" role="alert">Could not load candidates: {listError}<button className="candidate-retry" onClick={() => void refreshCandidates()} disabled={listLoading}>{listLoading ? "Retrying…" : "Retry"}</button></div>}
      {listLoading && !rows.length ? <div className="candidate-list-loading" role="status">Loading candidates…</div> : <div className="table-scroll"><table><thead><tr><th>Candidate</th><th>Latest role</th><th>Company</th><th>Resume</th><th>Action</th></tr></thead><tbody>{filtered.map(x => <tr key={x.id}><td><b>{x.name || x.full_name || `Candidate #${x.id}`}</b><small>{x.email || "No email"}</small></td><td>{x.latest_role || "—"}</td><td>{x.latest_company || "—"}</td><td>{x.resume_uploaded ? <span className="pill good">Available</span> : <span className="pill">Missing</span>}</td><td><Button secondary onClick={() => navigate("schedule", `&candidate=${x.id}`)}>Schedule</Button></td></tr>)}</tbody></table>{!filtered.length && !listError && <Empty text={rows.length ? "No candidates match your search." : "No candidates yet. Add a candidate to start the pipeline."}/>}</div>}
    </article>
  </>
}

function Interviews() {
  const [rows, setRows] = useState<AnyRow[]>([])
  const [filter, setFilter] = useState<InterviewStatus | "all">("all")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [transcript, setTranscript] = useState<{ interviewId: number, content: string } | null>(null)
  const [transcriptLoading, setTranscriptLoading] = useState<number | null>(null)
  const [transcriptError, setTranscriptError] = useState("")
  const loadInterviews = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const result = await get("/interviews/")
      setRows(Array.isArray(result) ? result : result?.items || [])
    } catch (e: any) {
      setError(e.message === "401" ? "Your session has expired. Please sign in again." : "Could not load interviews. Please retry.")
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { void loadInterviews() }, [loadInterviews])
  async function viewTranscript(interviewId: number) {
    setTranscriptLoading(interviewId)
    setTranscriptError("")
    try {
      const content = await getText(`/interviews/${interviewId}/transcript`)
      setTranscript({ interviewId, content })
    } catch (e: any) {
      setTranscriptError(e.message === "404" ? "The transcript is no longer available." : e.message === "401" ? "Your session has expired. Please sign in again." : "Could not load this transcript.")
    } finally {
      setTranscriptLoading(null)
    }
  }
  const data = filter === "all" ? rows : rows.filter(x => x.status === filter)
  return <>
    <Header eyebrow="INTERVIEW OPERATIONS" title="Interviews" subtitle="Monitor every scheduled and completed AI interview." action={<Button onClick={() => navigate("schedule")}>+ Schedule interview</Button>} />
    <div className="filter-tabs">{["all", ...INTERVIEW_STATUSES].map(x => <button className={filter === x ? "selected" : ""} onClick={() => setFilter(x as InterviewStatus | "all")} key={x}>{x.replace("_"," ")}</button>)}</div>
    <article className="panel table-panel"><PanelTitle title="Interview pipeline" sub={`${data.length} interviews in this view.`} />
    {loading && <div className="loading-state" role="status">Loading interviews...</div>}
    {error && <div className="error-state" role="alert">{error}<button className="secondary-button" onClick={() => void loadInterviews()} disabled={loading}>Retry</button></div>}
    {!loading && !error && <div className="table-scroll"><table><thead><tr><th>Candidate</th><th>Scheduled</th><th>Status</th><th>Meet</th><th>Evaluation</th><th>Transcript</th></tr></thead><tbody>{data.map(x => <tr key={x.id}><td><b>{x.candidate_name || x.candidate?.name || `Candidate #${x.candidate_id}`}</b><small>Interview #{x.id}</small></td><td>{x.scheduled_at ? new Date(x.scheduled_at).toLocaleString() : "—"}</td><td><Status value={x.status}/></td><td>{x.meet_link ? <a className="link" href={x.meet_link} target="_blank" rel="noreferrer">Open Meet</a> : "—"}</td><td><Button secondary onClick={() => navigate("evaluations", `&interview=${x.id}`)}>Evaluate</Button></td><td>{x.transcript_available ? <button className="text-button" onClick={() => void viewTranscript(Number(x.id))} disabled={transcriptLoading === Number(x.id)}>{transcriptLoading === Number(x.id) ? "Loading..." : "View transcript"}</button> : "—"}</td></tr>)}</tbody></table>{!data.length && <Empty text="No interviews in this status."/>}</div>}
    {transcriptError && <div className="error-state" role="alert">{transcriptError}<button className="secondary-button" onClick={() => setTranscriptError("")}>Dismiss</button></div>}
    </article>
    {transcript && <div className="modal-backdrop" onClick={() => setTranscript(null)}><section className="modal transcript-modal" role="dialog" aria-modal="true" aria-labelledby="transcript-title" onClick={e => e.stopPropagation()}><div className="modal-head"><div><span className="eyebrow">INTERVIEW TRANSCRIPT</span><h2 id="transcript-title">Interview #{transcript.interviewId}</h2></div><button aria-label="Close transcript" onClick={() => setTranscript(null)}>×</button></div><pre className="transcript-body">{transcript.content || "The transcript is empty."}</pre></section></div>}
  </>
}

function Schedule() {
  const [cands, setCands] = useState<AnyRow[]>([])
  const [candidate, setCandidate] = useState(new URLSearchParams(location.search).get("candidate") || "")
  const [date, setDate] = useState("")
  const [time, setTime] = useState("10:00")
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")
  const [candidatesLoading, setCandidatesLoading] = useState(true)
  const [candidatesError, setCandidatesError] = useState("")
  const loadCandidates = useCallback(async () => {
    setCandidatesLoading(true)
    setCandidatesError("")
    try {
      const result = await get("/candidates/")
      setCands(Array.isArray(result) ? result : result?.items || [])
    } catch (e: any) {
      setCandidatesError(e.message === "401" ? "Your session has expired. Please sign in again." : "Could not load candidates. Retry before scheduling an interview.")
    } finally {
      setCandidatesLoading(false)
    }
  }, [])
  useEffect(() => { void loadCandidates() }, [loadCandidates])
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setMsg("")
    try { await post("/interviews/", { candidate_id: Number(candidate), scheduled_at: `${date}T${time}:00` }); setMsg("Interview scheduled successfully.") }
    catch (e: any) { setMsg(e.message || "Could not schedule the interview.") }
    finally { setBusy(false) }
  }
  return <>
    <Header eyebrow="INTERVIEW SCHEDULE" title="Schedule" subtitle="Create an interview and let the workflow handle the Google Meet session."/>
    <div className="schedule-layout"><article className="panel form-panel"><PanelTitle title="New interview" sub="Choose a candidate and interview time."/>
      {candidatesLoading && <div className="loading-state" role="status">Loading candidates...</div>}
      {candidatesError && <div className="error-state" role="alert">{candidatesError}<button className="secondary-button" type="button" onClick={() => void loadCandidates()} disabled={candidatesLoading}>Retry</button></div>}
      {!candidatesLoading && !candidatesError && !cands.length && <div className="notice">No candidates are available. Add a candidate before scheduling.</div>}
      <form onSubmit={submit}><label>Candidate<select value={candidate} onChange={e => setCandidate(e.target.value)} required disabled={candidatesLoading || Boolean(candidatesError) || !cands.length}><option value="">Select candidate</option>{cands.map(x => <option value={x.id} key={x.id}>{x.name || x.full_name || `Candidate #${x.id}`}</option>)}</select></label>
      <label>Date<input type="date" value={date} onChange={e => setDate(e.target.value)} required/></label><label>Time<input type="time" value={time} onChange={e => setTime(e.target.value)} required/></label>
      <div className="schedule-summary"><b>Workflow</b><span>Google Calendar → Meet link → Alena interview → evaluation</span></div>
      <button className="primary-button full" disabled={busy || candidatesLoading || Boolean(candidatesError) || !cands.length}>{busy ? "Scheduling..." : "Schedule interview"}</button>{msg && <div className="notice">{msg}</div>}</form>
    </article><article className="panel"><PanelTitle title="Scheduling checklist" sub="What happens after you schedule."/><div className="steps">{["Candidate is attached to the interview","Calendar event and Meet link are created","Scheduler starts the Meet bot at interview time","Alena conducts the interview","Transcript and evaluation become available"].map((x,i) => <div className="step" key={x}><span>{i+1}</span><div><b>{x}</b><small>Automated workflow</small></div></div>)}</div></article></div>
  </>
}

function Evaluations() {
  const [evaluations, setEvaluations] = useState<AnyRow[]>([])
  const [interviews, setInterviews] = useState<AnyRow[]>([])
  const [selected, setSelected] = useState<AnyRow | null>(null)
  const [pendingInterview, setPendingInterview] = useState<AnyRow | null>(null)
  const [mode, setMode] = useState<"pending" | "history">("pending")
  const [message, setMessage] = useState("")
  const [loading, setLoading] = useState(true)
  const [evaluationsError, setEvaluationsError] = useState("")
  const [interviewsError, setInterviewsError] = useState("")
  const [generatingId, setGeneratingId] = useState<number | null>(null)
  const requestedInterviewId = useMemo(() => {
    const value = Number(new URLSearchParams(location.search).get("interview"))
    return Number.isInteger(value) && value > 0 ? value : null
  }, [])
  const requestedInterviewHandled = useRef(false)

  const load = useCallback(async () => {
    setLoading(true)
    setEvaluationsError("")
    setInterviewsError("")
    const [evaluationResult, interviewResult] = await Promise.allSettled([get("/evaluations/"), get("/interviews/")])
    if (evaluationResult.status === "fulfilled") {
      const value = evaluationResult.value
      setEvaluations(Array.isArray(value) ? value : [])
    } else {
      setEvaluationsError(evaluationResult.reason?.message === "401" ? "Your session has expired. Please sign in again." : "Could not load evaluations.")
    }
    if (interviewResult.status === "fulfilled") {
      const value = interviewResult.value
      setInterviews(Array.isArray(value) ? value : value?.items || [])
    } else {
      setInterviewsError(interviewResult.reason?.message === "401" ? "Your session has expired. Please sign in again." : "Could not load interviews for evaluation.")
    }
    setLoading(false)
  }, [])

  useEffect(() => { void load() }, [load])

  const evaluatedIds = new Set(evaluations.map(x => Number(x.interview_id)))
  const pending = interviews.filter(
    x =>
      ["completed", "interrupted"].includes(
        String(x.status || "").toLowerCase()
      ) &&
      !evaluatedIds.has(Number(x.id))
  )
  const avg = (key: string) => {
    const a = evaluations.map(x => x[key]).filter(v => v !== null && v !== undefined && v !== "").map(Number).filter(Number.isFinite)
    return a.length ? Math.round(a.reduce((s,n) => s+n, 0) / a.length) : null
  }

  useEffect(() => {
    if (!requestedInterviewId || requestedInterviewHandled.current || loading || evaluationsError || interviewsError) return
    const evaluation = evaluations.find(x => Number(x.interview_id) === requestedInterviewId)
    if (evaluation) {
      requestedInterviewHandled.current = true
      setMode("history")
      void openDetails(evaluation)
      return
    }
    const interview = interviews.find(x => Number(x.id) === requestedInterviewId)
    if (interview) {
      requestedInterviewHandled.current = true
      setMode("pending")
      setPendingInterview(interview)
      setMessage("No evaluation exists for this interview yet.")
    } else {
      requestedInterviewHandled.current = true
      setMessage("The requested interview could not be found.")
    }
  }, [requestedInterviewId, requestedInterviewHandled, loading, evaluationsError, interviewsError, evaluations, interviews])

  async function generate(interviewId: number) {
    if (!Number.isInteger(interviewId) || interviewId <= 0) return
    setGeneratingId(interviewId)
    setMessage("")
    try {
      setMessage("Generating evaluation from the interview transcript...")
      const result = await post(`/evaluations/${interviewId}/generate`, {})
      await load()
      setSelected(result)
      setPendingInterview(null)
      setMode("history")
      setMessage("Evaluation generated successfully.")
    } catch (e: any) {
      setMessage(e.message || "Evaluation could not be generated.")
    } finally {
      setGeneratingId(null)
    }
  }

  async function openDetails(evaluation: AnyRow) {
    if (!Number.isInteger(Number(evaluation.id)) || Number(evaluation.id) <= 0) return
    setSelected(evaluation)
    try {
      const detail = await get(`/evaluations/interview/${evaluation.interview_id}/details`)
      if (detail.evaluation && Number(detail.evaluation.id) > 0) {
        setSelected({ ...detail.evaluation, interview: detail.interview, candidate: detail.candidate, interview_id: evaluation.interview_id })
      }
    } catch (e: any) {
      setMessage(e.message === "401" ? "Your session has expired. Please sign in again." : "Could not load the full report. Showing the saved evaluation summary.")
    }
  }

  return <>
    <Header eyebrow="AI ASSESSMENT" title="Evaluations" subtitle="Evaluate completed interviews using the standardized SalesInterviewAI rubric." action={<Button onClick={() => setMode("pending")}>+ New evaluation</Button>} />
    <div className="evaluation-tabs">
      <button className={mode === "pending" ? "selected" : ""} onClick={() => setMode("pending")}>Pending evaluation <b>{pending.length}</b></button>
      <button className={mode === "history" ? "selected" : ""} onClick={() => setMode("history")}>Evaluation history <b>{evaluations.length}</b></button>
    </div>

    {message && <div className="notice" role="status">{message}</div>}
    {(evaluationsError || interviewsError) && <div className="error-state" role="alert">{[evaluationsError, interviewsError].filter(Boolean).join(" ")}<button className="secondary-button" onClick={() => void load()} disabled={loading}>Retry</button></div>}

    {loading && <div className="loading-state" role="status">Loading evaluations and interviews...</div>}
    {!loading && mode === "pending" && !evaluationsError && !interviewsError ? <article className="panel table-panel">
      <PanelTitle title="Interviews awaiting evaluation" sub="Completed interviews without an evaluation are shown here."/>
      <div className="table-scroll"><table><thead><tr><th>Candidate</th><th>Interview</th><th>Completed</th><th>Action</th></tr></thead><tbody>
        {pending.map(x => <tr key={x.id}><td><b>{x.candidate_name || x.candidate?.name || `Candidate #${x.candidate_id}`}</b><small>Interview #{x.id}</small></td><td>{x.position || "Sales interview"}</td><td>{x.completed_at ? new Date(x.completed_at).toLocaleString() : "Completed"}</td><td><Button onClick={() => generate(Number(x.id))}>Evaluate</Button></td></tr>)}
      </tbody></table>{!pending.length && <Empty text="No interviews are waiting for evaluation."/>}</div>
    </article> : !loading && mode === "history" && !evaluationsError ? <article className="panel table-panel">
      <PanelTitle title="Evaluation history" sub="Open any completed evaluation for the full report."/>
      <div className="table-scroll"><table><thead><tr><th>Interview</th><th>Candidate</th><th>Score</th><th>Result</th><th>Recruiter review</th><th>Action</th></tr></thead><tbody>
        {evaluations.map(x => <tr key={x.id}><td>#{x.interview_id}</td><td><b>{x.candidate_name || "Candidate evaluation"}</b></td><td><strong>{x.overall_score ?? "—"}/100</strong></td><td><Status value={x.evaluation_status || x.result || "pending"}/></td><td>{x.recruiter_status || "pending"}</td><td><Button secondary onClick={() => openDetails(x)}>View report</Button></td></tr>)}
      </tbody></table>{!evaluations.length && <Empty text="No evaluations available yet."/>}</div>
    </article> : null}

    {!loading && !evaluationsError && <section className="evaluation-bottom">
      <article className="panel"><PanelTitle title="Evaluation criteria" sub="Every interview is assessed against the same seven sales competencies."/>
        <div className="criteria-list">{criteria.map(([n,d]) => <div className="criteria-row" key={n}><b>{n}</b><span>{d}</span></div>)}</div>
      </article>
      <article className="panel"><PanelTitle title="Competency averages" sub="Average score across evaluation history."/>
        <Chart h={330}><RadarChart data={criteria.map(([name,,key]) => ({subject:name, score:avg(key)}))}><PolarGrid/><PolarAngleAxis dataKey="subject" tick={{fontSize:9}}/><Radar dataKey="score" stroke="#9b70b4" fill="#c9a6d7" fillOpacity={.55}/><Tooltip/></RadarChart></Chart>
      </article>
    </section>}

    {selected && <EvaluationModal data={selected} onClose={() => setSelected(null)} />}
    {pendingInterview && <div className="modal-backdrop" onClick={() => setPendingInterview(null)}><section className="modal pending-evaluation-modal" role="dialog" aria-modal="true" aria-labelledby="pending-evaluation-title" onClick={e => e.stopPropagation()}><div className="modal-head"><div><span className="eyebrow">PENDING EVALUATION</span><h2 id="pending-evaluation-title">{pendingInterview.candidate_name || pendingInterview.candidate?.name || `Interview #${pendingInterview.id}`}</h2><p className="modal-subtitle">Interview #{pendingInterview.id} · {pendingInterview.position || "Sales interview"}</p></div><button aria-label="Close evaluation prompt" onClick={() => setPendingInterview(null)}>×</button></div><p>This interview does not have a saved evaluation yet.</p>{["completed", "interrupted"].includes(String(pendingInterview.status).toLowerCase()) && pendingInterview.transcript_available ? <p>A transcript is available, so an evaluation can be generated.</p> : <p>An evaluation can be generated after the interview is completed and its transcript is available.</p>}<div className="candidate-form-actions">{["completed", "interrupted"].includes(String(pendingInterview.status).toLowerCase()) && pendingInterview.transcript_available && <button className="primary-button" onClick={() => void generate(Number(pendingInterview.id))} disabled={generatingId === Number(pendingInterview.id)}>{generatingId === Number(pendingInterview.id) ? "Generating..." : "Generate evaluation"}</button>}<button className="secondary-button" onClick={() => setPendingInterview(null)}>Close</button></div></section></div>}
  </>
}

function EvaluationModal({ data, onClose }: { data: AnyRow, onClose: () => void }) {
  const [busy, setBusy] = useState(false)
  const [review, setReview] = useState("")
  const hasEvaluationId = Number.isInteger(Number(data.id)) && Number(data.id) > 0
  async function recruiterAction(action: "approve" | "reject") {
    if (!hasEvaluationId) return
    setBusy(true)
    try {
      const result = await post(`/evaluations/${data.id}/${action}`, {})
      setReview(result.message || `Evaluation ${action}d.`)
    } catch (e: any) { setReview(e.message || "Unable to update recruiter review.") }
    finally { setBusy(false) }
  }

  return <div className="modal-backdrop" onClick={onClose}><div className="modal large-modal" onClick={e => e.stopPropagation()}>
    <div className="modal-head"><div><span className="eyebrow">EVALUATION REPORT</span><h2>{data.candidate?.name || `Interview #${data.interview_id}`}</h2><p className="modal-subtitle">Interview #{data.interview_id}</p></div><button onClick={onClose}>×</button></div>
    <div className="score-hero"><strong>{data.overall_score ?? "—"}</strong><span>/ 100</span><Status value={data.evaluation_status || data.result || "manual"}/></div>
    <div className="detail-grid">{criteria.map(([n,,k]) => <div className="detail-score" key={k}><span>{n}</span><b>{data[k] ?? "—"}</b><div className="bar"><i style={{width:`${Math.min(Number(data[k]) || 0, 100)}%`}}/></div></div>)}</div>
    <div className="report-grid"><div><h3>Strengths</h3><p>{data.strengths || "Not provided."}</p></div><div><h3>Weaknesses</h3><p>{data.weaknesses || "Not provided."}</p></div><div><h3>Automated summary</h3><p>{data.recommendation || "Not provided."}</p></div></div>
    {data.structured_result ? <section className="panel">
      <PanelTitle title="Evidence and competency profile" sub={`${data.structured_result.coverage?.description || "Coverage unavailable"} | ${Math.round((data.structured_result.coverage?.overall_confidence || 0) * 100)}% evaluation confidence`} />
      <small>Rubric {data.rubric_version || data.structured_result.rubric_version} | {data.evaluation_method || data.structured_result.evaluation_method} | {data.runs?.length || 0} recorded run(s)</small>
      <div className="detail-grid">{Object.values(data.structured_result.competencies || {}).map((item: any) => <div className="detail-score" key={item.competency}>
        <span>{item.label} - {item.weight}%</span><b>{item.score == null ? "Not observed" : `${item.score}/5`}</b>
        <p>{item.rationale}</p><small>Evidence confidence: {Math.round((item.confidence || 0) * 100)}%</small>
        {item.evidence?.filter((x: any) => x.assessment === "demonstrated" || x.assessment === "partially_demonstrated").map((e: any, i: number) => <blockquote key={`${e.criterion}-${i}`}><q>{e.answer_excerpt}</q><br/><small>{e.criterion_label} - {e.assessment}</small></blockquote>)}
        {!!item.missing_behaviors?.length && <small>Not evidenced in tested answers: {item.missing_behaviors.join(", ")}</small>}
      </div>)}</div>
      <h3>Question evidence</h3>
      {(data.structured_result.question_evaluations || []).map((q: any) => <article className="criteria-row" key={q.question_id ?? q.question_order}>
        <div><b>Q{q.question_order}: {q.question}</b><p>{q.candidate_answer || "No aligned candidate answer."}</p>
          <small>{q.relevant_competencies?.join(", ") || "No competency tag"} | {q.score == null ? "Not scored" : `${q.score}/5`} | {q.quality_indicator}</small>
          {q.evidence?.map((e: any, i: number) => <p key={`${e.criterion}-${i}`}><q>{e.answer_excerpt}</q> | {e.criterion_label}: {e.assessment}</p>)}
        </div>
      </article>)}
      <p><b>Recruiter decision remains independent.</b> This rubric output is evidence for review, not an approve/reject recommendation.</p>
    </section> : <div className="notice">This is a legacy/manual evaluation without structured evidence or reproducible rubric provenance.</div>}
    {hasEvaluationId && <div className="review-actions"><span>Recruiter decision: <b>{data.recruiter_status || "pending"}</b></span><div><button className="secondary-button" disabled={busy} onClick={() => recruiterAction("reject")}>Reject</button><button className="primary-button" disabled={busy} onClick={() => recruiterAction("approve")}>Approve</button></div></div>}
    {review && <div className="notice">{review}</div>}
  </div></div>
}

function Empty({ text }: { text: string }) {
  return <div className="empty"><div>◎</div><b>{text}</b><span>Data will appear here when the workflow has records.</span></div>
}

export default function App() {
  const [loggedIn, setLoggedIn] = useState(Boolean(localStorage.getItem("access_token")))
  const [page, setPage] = useState(currentPage())
  const [showSplash, setShowSplash] = useState(true)

  useEffect(() => {
    const sync = () => setPage(currentPage())
    const expired = () => {
      localStorage.removeItem("access_token")
      setLoggedIn(false)
      setPage("dashboard")
      window.history.replaceState({}, "", "/")
    }
    window.addEventListener("popstate", sync)
    window.addEventListener("auth-expired", expired)
    return () => {
      window.removeEventListener("popstate", sync)
      window.removeEventListener("auth-expired", expired)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => setShowSplash(false), 1100)
    return () => window.clearTimeout(timer)
  }, [])

  function loginWithGoogle(accessToken?: string) {
    if (accessToken) localStorage.setItem("access_token", accessToken)
    setLoggedIn(true)
    setPage(currentPage())
  }

  function logout() {
    localStorage.removeItem("access_token")
    setLoggedIn(false)
    setPage("dashboard")
    window.history.replaceState({}, "", "/")
  }

  if (showSplash) return <SplashScreen />

  if (!loggedIn) return <GoogleGate onConnected={loginWithGoogle} />

  const body =
    page === "candidates" ? <Candidates/> :
    page === "interviews" ? <Interviews/> :
    page === "schedule" ? <Schedule/> :
    page === "evaluations" ? <Evaluations/> :
    <Dashboard/>

  return <Layout page={page} onLogout={logout}>{body}</Layout>
}
