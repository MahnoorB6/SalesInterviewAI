import { useEffect, useMemo, useState } from "react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import "./App.css"

type DashboardStats = {
  total_candidates: number
  scheduled_interviews: number
  in_progress_interviews?: number
  completed_interviews: number
  pending_evaluation?: number
  average_score: number | null
}

type Interview = {
  id: number
  candidate_name: string
  scheduled_at: string
  completed_at?: string | null
  status: string
}

type Evaluation = {
  interview_id: number
  overall_score?: number | null
  communication?: number | null
  confidence?: number | null
  sales_knowledge?: number | null
  lead_qualification?: number | null
  objection_handling?: number | null
  persuasion?: number | null
  closing_ability?: number | null
  result?: string | null
}

const navItems = [
  { label: "Dashboard", href: "dashboard.html", active: true },
  { label: "Candidates", href: "candidates.html" },
  { label: "Interviews", href: "interviews.html" },
  { label: "Calendar", href: "schedule.html" },
  { label: "Evaluations", href: "evaluations.html" },
]

const tooltipStyle = {
  borderRadius: 10,
  border: "1px solid #eadfeb",
  background: "#ffffff",
  boxShadow: "0 10px 30px rgba(44, 30, 54, .12)",
  fontSize: 11,
}

function StatIcon({ type }: { type: "users" | "calendar" | "check" | "score" }) {
  const icons = { users: "◉", calendar: "▣", check: "✓", score: "★" }
  return <span className="stat-icon">{icons[type]}</span>
}

function App() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [interviews, setInterviews] = useState<Interview[]>([])
  const [evaluations, setEvaluations] = useState<Evaluation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    const token = localStorage.getItem("access_token") || localStorage.getItem("token")
    const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {}

    Promise.all([
      fetch("http://127.0.0.1:8000/api/dashboard/stats", { headers }).then(r => {
        if (!r.ok) throw new Error("Stats request failed")
        return r.json()
      }),
      fetch("http://127.0.0.1:8000/api/dashboard/interviews", { headers }).then(r => {
        if (!r.ok) throw new Error("Interviews request failed")
        return r.json()
      }),
      fetch("http://127.0.0.1:8000/api/evaluations/", { headers }).then(r => {
        if (!r.ok) throw new Error("Evaluations request failed")
        return r.json()
      }),
    ])
      .then(([statsData, interviewData, evaluationData]) => {
        setStats(statsData)
        setInterviews(Array.isArray(interviewData) ? interviewData : [])
        setEvaluations(Array.isArray(evaluationData) ? evaluationData : [])
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [])

  const values = {
    candidates: stats?.total_candidates ?? 0,
    scheduled: stats?.scheduled_interviews ?? 0,
    completed: stats?.completed_interviews ?? 0,
    inProgress: stats?.in_progress_interviews ?? 0,
    pending: stats?.pending_evaluation ?? 0,
    score: stats?.average_score ?? 0,
  }

  const pipelineData = [
    { name: "Scheduled", value: values.scheduled },
    { name: "In progress", value: values.inProgress },
    { name: "Completed", value: values.completed },
    { name: "Pending review", value: values.pending },
  ]

  const statusData = useMemo(() => {
    const counts = { Scheduled: 0, "In progress": 0, Completed: 0, Cancelled: 0 }
    interviews.forEach(item => {
      const key = item.status === "scheduled" ? "Scheduled"
        : item.status === "in_progress" ? "In progress"
        : item.status === "completed" ? "Completed"
        : item.status === "cancelled" ? "Cancelled"
        : null
      if (key) counts[key]++
    })
    return Object.entries(counts).map(([name, value]) => ({ name, value }))
  }, [interviews])

  const activityData = useMemo(() => {
    const months = new Map<string, { month: string; interviews: number; completed: number }>()
    interviews.forEach(item => {
      const date = new Date(item.scheduled_at)
      if (Number.isNaN(date.getTime())) return
      const key = date.toLocaleDateString("en-US", { month: "short" })
      const row = months.get(key) || { month: key, interviews: 0, completed: 0 }
      row.interviews++
      if (item.status === "completed") row.completed++
      months.set(key, row)
    })
    return Array.from(months.values()).slice(-8)
  }, [interviews])

  const criteriaData = useMemo(() => {
    const fields = [
      ["Communication", "communication"],
      ["Confidence", "confidence"],
      ["Sales knowledge", "sales_knowledge"],
      ["Lead qualification", "lead_qualification"],
      ["Objection handling", "objection_handling"],
      ["Persuasion", "persuasion"],
      ["Closing ability", "closing_ability"],
    ] as const

    return fields.map(([label, key]) => {
      const scores = evaluations
        .map(item => Number(item[key]))
        .filter(score => Number.isFinite(score))
      return {
        subject: label,
        score: scores.length
          ? Math.round(scores.reduce((sum, score) => sum + score, 0) / scores.length)
          : 0,
      }
    })
  }, [evaluations])

  const resultData = useMemo(() => {
    const counts = { Passed: 0, Failed: 0, Pending: 0 }
    evaluations.forEach(item => {
      const result = String(item.result || "").toLowerCase()
      if (result.includes("pass") || result.includes("selected") || result.includes("approved")) counts.Passed++
      else if (result.includes("fail") || result.includes("rejected")) counts.Failed++
      else counts.Pending++
    })
    return Object.entries(counts).map(([name, value]) => ({ name, value }))
  }, [evaluations])

  const scoreData = useMemo(() => {
    return evaluations
      .filter(item => item.overall_score != null)
      .slice(0, 8)
      .reverse()
      .map((item, index) => ({
        candidate: interviews.find(i => i.id === item.interview_id)?.candidate_name?.split(" ")[0] || `Candidate ${index + 1}`,
        score: Number(item.overall_score),
      }))
  }, [evaluations, interviews])

  const pieColors = ["#9b70b4", "#d889a4", "#c8a1d7"]

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">S</div>
          <div><div className="brand-name">SalesInterviewAI</div><div className="brand-subtitle">AI-powered hiring</div></div>
        </div>
        <div className="workspace-label">WORKSPACE</div>
        <nav className="nav">
          {navItems.map(item => <a key={item.label} href={item.href} className={item.active ? "nav-item active" : "nav-item"}><span className="nav-dot" />{item.label}</a>)}
        </nav>
        <div className="sidebar-bottom">
          <div className="alena-card"><div className="alena-status"><span /> Alena is ready</div><p>Your AI interviewer is connected to the interview workflow.</p></div>
          <div className="sidebar-footer">SalesInterviewAI · Recruiter workspace</div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div>
            <div className="eyebrow">RECRUITER ANALYTICS</div>
            <h1>Dashboard</h1>
            <p className="page-subtitle">A visual overview of your hiring pipeline and candidate performance.</p>
          </div>
          <div className="topbar-actions">
            <a className="secondary-button" href="schedule.html">View calendar</a>
            <a className="primary-button" href="candidates.html">+ New candidate</a>
          </div>
        </header>

        {error && <div className="notice"><span>Some dashboard data could not be loaded.</span><span className="notice-muted">Make sure the FastAPI backend is running.</span></div>}

        <section className="stats-grid">
          {[
            ["users", values.candidates, "Total candidates", "Pipeline"],
            ["calendar", values.scheduled, "Scheduled interviews", "Upcoming"],
            ["check", values.completed, "Completed interviews", "Completed"],
            ["score", stats?.average_score == null ? null : values.score.toFixed(1), "Average score", "Performance"],
          ].map(([icon, value, label, badge]) => (
            <article className="stat-card" key={String(label)}>
              <div className="stat-card-top"><StatIcon type={icon as "users" | "calendar" | "check" | "score"} /><span className="trend purple">{badge}</span></div>
              <div className="stat-value">{loading ? "—" : value ?? "—"}</div>
              <div className="stat-label">{label}</div>
              <div className="stat-helper">{label === "Average score" ? "Across evaluated interviews" : "Live database metric"}</div>
            </article>
          ))}
        </section>

        <section className="chart-grid">
          <article className="panel chart-panel wide">
            <div className="panel-header"><div><h2>Interview activity</h2><p>Scheduled and completed interviews over time.</p></div><span className="panel-badge">Database</span></div>
            <div className="chart-wrap"><ResponsiveContainer width="100%" height={280}>
              <LineChart data={activityData}>
                <CartesianGrid stroke="#eee9ef" strokeDasharray="4 4" vertical={false} />
                <XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#9b929f" }} />
                <YAxis allowDecimals={false} axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#9b929f" }} />
                <Tooltip contentStyle={tooltipStyle} />
                <Line type="monotone" dataKey="interviews" name="Interviews" stroke="#8b62a1" strokeWidth={3} dot={{ r: 4 }} />
                <Line type="monotone" dataKey="completed" name="Completed" stroke="#d786a2" strokeWidth={3} dot={{ r: 4 }} />
              </LineChart>
            </ResponsiveContainer></div>
          </article>

          <article className="panel chart-panel">
            <div className="panel-header"><div><h2>Pipeline</h2><p>Current interview status.</p></div></div>
            <div className="chart-wrap"><ResponsiveContainer width="100%" height={280}>
              <BarChart data={pipelineData} margin={{ top: 15, right: 5, left: -20, bottom: 5 }}>
                <CartesianGrid stroke="#eee9ef" strokeDasharray="4 4" vertical={false} />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 9, fill: "#9b929f" }} />
                <YAxis allowDecimals={false} axisLine={false} tickLine={false} tick={{ fontSize: 9, fill: "#9b929f" }} />
                <Tooltip contentStyle={tooltipStyle} />
                <Bar dataKey="value" name="Interviews" radius={[7,7,2,2]} fill="#9b70b4" />
              </BarChart>
            </ResponsiveContainer></div>
          </article>

          <article className="panel chart-panel">
            <div className="panel-header"><div><h2>Results distribution</h2><p>Evaluation outcomes from completed reviews.</p></div></div>
            <div className="donut-layout">
              <div className="donut-wrap"><ResponsiveContainer width="100%" height={210}>
                <PieChart>
                  <Pie data={resultData} dataKey="value" nameKey="name" innerRadius={58} outerRadius={82} paddingAngle={3}>
                    {resultData.map((_, index) => <Cell key={index} fill={pieColors[index % pieColors.length]} />)}
                  </Pie>
                  <Tooltip contentStyle={tooltipStyle} />
                </PieChart>
              </ResponsiveContainer>
              <div className="donut-center"><strong>{evaluations.length}</strong><span>reviews</span></div></div>
              <div className="legend-list">{resultData.map((item, index) => <div className="legend-row" key={item.name}><span className="legend-dot" style={{ background: pieColors[index % pieColors.length] }} /><span>{item.name}</span><strong>{item.value}</strong></div>)}</div>
            </div>
          </article>

          <article className="panel chart-panel wide">
            <div className="panel-header"><div><h2>Sales competency profile</h2><p>Average evaluation score by interview competency.</p></div></div>
            <div className="chart-wrap"><ResponsiveContainer width="100%" height={280}>
              <RadarChart data={criteriaData} outerRadius="72%">
                <PolarGrid stroke="#e9e2ec" />
                <PolarAngleAxis dataKey="subject" tick={{ fontSize: 9, fill: "#766b7c" }} />
                <Radar name="Score" dataKey="score" stroke="#9b70b4" fill="#c9a6d7" fillOpacity={0.55} />
                <Tooltip contentStyle={tooltipStyle} />
              </RadarChart>
            </ResponsiveContainer></div>
          </article>

          <article className="panel chart-panel">
            <div className="panel-header"><div><h2>Candidate scores</h2><p>Latest evaluated candidates.</p></div></div>
            <div className="chart-wrap"><ResponsiveContainer width="100%" height={280}>
              <BarChart data={scoreData} layout="vertical" margin={{ top: 5, right: 15, left: 10, bottom: 5 }}>
                <CartesianGrid stroke="#eee9ef" strokeDasharray="4 4" horizontal={false} />
                <XAxis type="number" domain={[0, 100]} axisLine={false} tickLine={false} tick={{ fontSize: 9, fill: "#9b929f" }} />
                <YAxis type="category" dataKey="candidate" width={55} axisLine={false} tickLine={false} tick={{ fontSize: 9, fill: "#766b7c" }} />
                <Tooltip contentStyle={tooltipStyle} />
                <Bar dataKey="score" name="Score" radius={[0,7,7,0]} fill="#d786a2" />
              </BarChart>
            </ResponsiveContainer></div>
          </article>
        </section>

        <section className="bottom-grid">
          <article className="panel activity-panel">
            <div className="panel-header"><div><h2>Recruiter workflow</h2><p>Move through your hiring process.</p></div></div>
            <div className="activity-list">
              <div className="activity-item"><div className="activity-icon purple">1</div><div><strong>Review candidates</strong><span>Manage resumes and candidate profiles.</span></div><a href="candidates.html">Open</a></div>
              <div className="activity-item"><div className="activity-icon rose">2</div><div><strong>Schedule interviews</strong><span>Create a Google Meet interview with Alena.</span></div><a href="schedule.html">Open</a></div>
              <div className="activity-item"><div className="activity-icon green">3</div><div><strong>Review evaluations</strong><span>Inspect interview results and scores.</span></div><a href="evaluations.html">Open</a></div>
            </div>
          </article>
          <article className="panel assistant-panel"><div className="assistant-glow" /><div className="assistant-content"><div className="assistant-avatar">A</div><div><span className="eyebrow">AI INTERVIEWER</span><h2>Meet Alena</h2><p>Alena conducts structured sales interviews and sends the conversation into your evaluation workflow.</p><a href="interviews.html" className="text-link">View interviews →</a></div></div></article>
        </section>
      </main>
    </div>
  )
}

export default App
