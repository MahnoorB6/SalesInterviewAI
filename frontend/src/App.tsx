import { useEffect, useState } from "react"

type DashboardStats = {
  total_candidates: number
  scheduled_interviews: number
  completed_interviews: number
  average_score: number | null
}

function App() {
  const [stats, setStats] = useState<DashboardStats | null>(null)

  useEffect(() => {
    fetch("http://127.0.0.1:8000/api/dashboard/stats")
      .then((response) => response.json())
      .then((data) => setStats(data))
      .catch((error) => console.error("Dashboard API error:", error))
  }, [])

  return (
    <div className="min-h-screen bg-gray-100">
      <aside className="fixed left-0 top-0 h-screen w-64 bg-gray-900 p-6 text-white">
        <h1 className="text-2xl font-bold">SalesInterviewAI</h1>

        <p className="mt-1 text-sm text-gray-400">
          AI Interview Platform
        </p>

        <nav className="mt-10 space-y-3">
          <div className="rounded-lg bg-gray-800 px-4 py-3">
            Dashboard
          </div>

          <div className="px-4 py-3 text-gray-400">
            Candidates
          </div>

          <div className="px-4 py-3 text-gray-400">
            Interviews
          </div>

          <div className="px-4 py-3 text-gray-400">
            Calendar
          </div>
        </nav>
      </aside>

      <main className="ml-64 p-8">
        <h2 className="text-3xl font-bold text-gray-900">
          Dashboard
        </h2>

        <p className="mt-1 text-gray-500">
          Welcome to SalesInterviewAI — Alena
        </p>

        <div className="mt-8 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl bg-white p-6 shadow-sm">
            <p className="text-sm text-gray-500">Total Candidates</p>
            <p className="mt-2 text-3xl font-bold">
              {stats?.total_candidates ?? 0}
            </p>
          </div>

          <div className="rounded-xl bg-white p-6 shadow-sm">
            <p className="text-sm text-gray-500">Scheduled Interviews</p>
            <p className="mt-2 text-3xl font-bold">
              {stats?.scheduled_interviews ?? 0}
            </p>
          </div>

          <div className="rounded-xl bg-white p-6 shadow-sm">
            <p className="text-sm text-gray-500">Completed Interviews</p>
            <p className="mt-2 text-3xl font-bold">
              {stats?.completed_interviews ?? 0}
            </p>
          </div>

          <div className="rounded-xl bg-white p-6 shadow-sm">
            <p className="text-sm text-gray-500">Average Score</p>
            <p className="mt-2 text-3xl font-bold">
              {stats?.average_score ?? "—"}
            </p>
          </div>
        </div>

        <div className="mt-8 rounded-xl bg-white p-6 shadow-sm">
          <h3 className="text-xl font-semibold text-gray-900">
            Recent Interviews
          </h3>

          <div className="mt-6 rounded-lg border border-dashed border-gray-300 p-10 text-center">
            <p className="text-gray-500">
              No interviews yet
            </p>

            <p className="mt-1 text-sm text-gray-400">
              Scheduled interviews will appear here.
            </p>
          </div>
        </div>
      </main>
    </div>
  )
}

export default App