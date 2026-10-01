import { useEffect, useMemo, useState } from "react"
import "./App.css"

type DashboardStats = {
  total_candidates: number
  scheduled_interviews: number
  completed_interviews: number
  average_score: number | null
}

const navItems = [
  { label: "Dashboard", href: "dashboard.html", active: true },
  { label: "Candidates", href: "candidates.html" },
  { label: "Interviews", href: "interviews.html" },
  { label: "Calendar", href: "schedule.html" },
  { label: "Evaluations", href: "evaluations.html" },
]

function StatIcon({ type }: { type: "users" | "calendar" | "check" | "score" }) {
  if (type === "users") return <span className="stat-icon">◉</span>
  if (type === "calendar") return <span className="stat-icon">▣</span>
  if (type === "check") return <span className="stat-icon">✓</span>
  return <span className="stat-icon">★</span>
}

function App() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  useEffect(() => {
    const token = localStorage.getItem("access_token") || localStorage.getItem("token")
    const headers: HeadersInit = token
      ? { Authorization: `Bearer ${token}` }
      : {}

    fetch("http://127.0.0.1:8000/api/dashboard/stats", { headers })
      .then((response) => {
        if (!response.ok) throw new Error("Dashboard request failed")
        return response.json()
      })
      .then((data) => setStats(data))
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [])

  const values = useMemo(() => ({
    candidates: stats?.total_candidates ?? 0,
    scheduled: stats?.scheduled_interviews ?? 0,
    completed: stats?.completed_interviews ?? 0,
    score: stats?.average_score ?? 0,
  }), [stats])

  const maxPipeline = Math.max(values.scheduled, values.completed, 1)
  const scheduledPercent = (values.scheduled / maxPipeline) * 100
  const completedPercent = (values.completed / maxPipeline) * 100
  const score = Math.max(0, Math.min(100, values.score))
  const circumference = 2 * Math.PI * 43
  const scoreOffset = circumference - (score / 100) * circumference

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">S</div>
          <div>
            <div className="brand-name">SalesInterviewAI</div>
            <div className="brand-subtitle">AI-powered hiring</div>
          </div>
        </div>

        <div className="workspace-label">WORKSPACE</div>
        <nav className="nav">
          {navItems.map((item) => (
            <a
              key={item.label}
              href={item.href}
              className={item.active ? "nav-item active" : "nav-item"}
            >
              <span className="nav-dot" />
              {item.label}
            </a>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="alena-card">
            <div className="alena-status"><span /> Alena is ready</div>
            <p>Your AI interviewer is connected to the interview workflow.</p>
          </div>
          <div className="sidebar-footer">SalesInterviewAI · Recruiter workspace</div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div>
            <div className="eyebrow">RECRUITER OVERVIEW</div>
            <h1>Dashboard</h1>
            <p className="page-subtitle">Monitor your interview pipeline and candidate performance.</p>
          </div>
          <div className="topbar-actions">
            <a className="secondary-button" href="schedule.html">View calendar</a>
            <a className="primary-button" href="candidates.html">+ New candidate</a>
          </div>
        </header>

        {error && (
          <div className="notice">
            <span>Dashboard data could not be loaded.</span>
            <span className="notice-muted">Make sure the FastAPI backend is running.</span>
          </div>
        )}

        <section className="stats-grid">
          <article className="stat-card">
            <div className="stat-card-top"><StatIcon type="users" /><span className="trend neutral">Pipeline</span></div>
            <div className="stat-value">{loading ? "—" : values.candidates}</div>
            <div className="stat-label">Total candidates</div>
            <div className="stat-helper">Candidates in your workspace</div>
          </article>

          <article className="stat-card">
            <div className="stat-card-top"><StatIcon type="calendar" /><span className="trend purple">Upcoming</span></div>
            <div className="stat-value">{loading ? "—" : values.scheduled}</div>
            <div className="stat-label">Scheduled interviews</div>
            <div className="stat-helper">Interviews waiting to happen</div>
          </article>

          <article className="stat-card">
            <div className="stat-card-top"><StatIcon type="check" /><span className="trend green">Completed</span></div>
            <div className="stat-value">{loading ? "—" : values.completed}</div>
            <div className="stat-label">Completed interviews</div>
            <div className="stat-helper">Interviews finished by Alena</div>
          </article>

          <article className="stat-card score-card">
            <div className="stat-card-top"><StatIcon type="score" /><span className="trend rose">Performance</span></div>
            <div className="score-row">
              <div>
                <div className="stat-value">{loading || stats?.average_score == null ? "—" : values.score.toFixed(1)}</div>
                <div className="stat-label">Average score</div>
              </div>
              <div className="mini-ring">
                <svg viewBox="0 0 100 100">
                  <circle className="ring-track" cx="50" cy="50" r="43" />
                  <circle className="ring-value" cx="50" cy="50" r="43" strokeDasharray={circumference} strokeDashoffset={scoreOffset} />
                </svg>
                <span>{stats?.average_score == null ? "—" : `${Math.round(score)}%`}</span>
              </div>
            </div>
          </article>
        </section>

        <section className="dashboard-grid">
          <article className="panel pipeline-panel">
            <div className="panel-header">
              <div>
                <h2>Interview pipeline</h2>
                <p>Current scheduled vs completed volume.</p>
              </div>
              <span className="panel-badge">Live data</span>
            </div>

            <div className="bar-chart">
              <div className="y-labels"><span>{maxPipeline}</span><span>{Math.round(maxPipeline / 2)}</span><span>0</span></div>
              <div className="chart-area">
                <div className="grid-line line-top" />
                <div className="grid-line line-mid" />
                <div className="grid-line line-bottom" />
                <div className="bars">
                  <div className="bar-group">
                    <div className="bar-value">{values.scheduled}</div>
                    <div className="bar scheduled" style={{ height: `${Math.max(scheduledPercent, values.scheduled ? 8 : 2)}%` }} />
                    <span>Scheduled</span>
                  </div>
                  <div className="bar-group">
                    <div className="bar-value">{values.completed}</div>
                    <div className="bar completed" style={{ height: `${Math.max(completedPercent, values.completed ? 8 : 2)}%` }} />
                    <span>Completed</span>
                  </div>
                </div>
              </div>
            </div>
          </article>

          <article className="panel score-panel">
            <div className="panel-header">
              <div>
                <h2>Performance snapshot</h2>
                <p>Average candidate evaluation score.</p>
              </div>
            </div>
            <div className="score-visual">
              <div className="large-ring">
                <svg viewBox="0 0 120 120">
                  <circle className="ring-track" cx="60" cy="60" r="50" />
                  <circle className="ring-value" cx="60" cy="60" r="50" strokeDasharray={2 * Math.PI * 50} strokeDashoffset={2 * Math.PI * 50 - (score / 100) * 2 * Math.PI * 50} />
                </svg>
                <div><strong>{stats?.average_score == null ? "—" : Math.round(score)}</strong><span>/ 100</span></div>
              </div>
              <div className="score-copy">
                <div className="score-title">Candidate quality</div>
                <p>{stats?.average_score == null ? "Complete an interview to start building performance insights." : "Average performance across completed candidate evaluations."}</p>
                <a href="evaluations.html">Open evaluations →</a>
              </div>
            </div>
          </article>
        </section>

        <section className="bottom-grid">
          <article className="panel activity-panel">
            <div className="panel-header">
              <div>
                <h2>Recruiter activity</h2>
                <p>A quick view of your current workflow.</p>
              </div>
            </div>
            <div className="activity-list">
              <div className="activity-item"><div className="activity-icon purple">1</div><div><strong>Review candidates</strong><span>Manage resumes and candidate profiles.</span></div><a href="candidates.html">Open</a></div>
              <div className="activity-item"><div className="activity-icon rose">2</div><div><strong>Schedule interviews</strong><span>Create a Google Meet interview with Alena.</span></div><a href="schedule.html">Open</a></div>
              <div className="activity-item"><div className="activity-icon green">3</div><div><strong>Review evaluations</strong><span>Inspect interview results and scores.</span></div><a href="evaluations.html">Open</a></div>
            </div>
          </article>

          <article className="panel assistant-panel">
            <div className="assistant-glow" />
            <div className="assistant-content">
              <div className="assistant-avatar">A</div>
              <div>
                <span className="eyebrow">AI INTERVIEWER</span>
                <h2>Meet Alena</h2>
                <p>Alena conducts structured sales interviews and sends the conversation into your evaluation workflow.</p>
                <a href="interviews.html" className="text-link">View interviews →</a>
              </div>
            </div>
          </article>
        </section>
      </main>
    </div>
  )
}

export default App
