import { useState, useEffect, useCallback, useMemo } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar, Legend, PieChart, Pie, Cell } from "recharts";

// ── Supabase Config ──
const SUPABASE_URL = "https://twbunmbzyqcqzgffdrib.supabase.co";
const SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InR3YnVubWJ6eXFjcXpnZmZkcmliIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE1ODgxODUsImV4cCI6MjA4NzE2NDE4NX0.8Y6tMnX5bhIWxTS7llFZElPY-st7rji0MtlTzxeqiW8";

async function supaQuery(table, params = {}) {
  const url = new URL(`${SUPABASE_URL}/rest/v1/${table}`);
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  const res = await fetch(url.toString(), {
    headers: {
      apikey: SUPABASE_KEY,
      Authorization: `Bearer ${SUPABASE_KEY}`,
      "Content-Type": "application/json",
      Prefer: "return=representation",
    },
  });
  if (!res.ok) throw new Error(`Supabase error: ${res.status} ${res.statusText}`);
  return res.json();
}

// ── Brand Colors ──
const COLORS = {
  bg: "#1a1612",
  bgCard: "#231f1a",
  bgCardHover: "#2a2520",
  gold: "#c4a265",
  goldDim: "#9a7d4e",
  goldBright: "#d4b87a",
  burgundy: "#8b3a3a",
  burgundyLight: "#a85454",
  forest: "#3a5a3a",
  forestLight: "#4a7a4a",
  cream: "#e8dcc8",
  warmGray: "#8a7e6e",
  text: "#d4c5a9",
  textDim: "#8a7e6e",
  border: "#3a3228",
  borderLight: "#4a4238",
};

const CHART_PALETTE = ["#c4a265", "#8b3a3a", "#3a5a3a", "#7a6a5a", "#a85454", "#4a7a4a", "#d4b87a", "#6a4a4a", "#5a7a5a"];

const RHETORICAL_COLORS = {
  exposition: "#c4a265",
  theological_claim: "#8b3a3a",
  illustration: "#3a5a3a",
  application: "#7a6a5a",
  introduction: "#a85454",
  conclusion: "#4a7a4a",
  transition: "#5a5040",
  pastoral_aside: "#d4b87a",
  prayer: "#6a5a4a",
};

// ── Loading Skeleton ──
function Skeleton({ width = "100%", height = 20 }) {
  return (
    <div
      style={{
        width, height, borderRadius: 4,
        background: `linear-gradient(90deg, ${COLORS.bgCard} 25%, ${COLORS.bgCardHover} 50%, ${COLORS.bgCard} 75%)`,
        backgroundSize: "200% 100%",
        animation: "shimmer 1.5s infinite",
      }}
    />
  );
}

// ── Stat Card ──
function StatCard({ label, value, sub }) {
  return (
    <div style={{
      background: COLORS.bgCard, border: `1px solid ${COLORS.border}`, borderRadius: 8,
      padding: "20px 24px", flex: "1 1 180px", minWidth: 160,
    }}>
      <div style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 32, fontWeight: 600, color: COLORS.gold, lineHeight: 1.1 }}>
        {value}
      </div>
      <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 12, color: COLORS.textDim, marginTop: 6, textTransform: "uppercase", letterSpacing: "0.08em" }}>
        {label}
      </div>
      {sub && <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: COLORS.warmGray, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

// ── Custom Tooltip ──
function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: COLORS.bgCard, border: `1px solid ${COLORS.border}`, borderRadius: 6,
      padding: "10px 14px", fontFamily: "'DM Sans', sans-serif", fontSize: 12, color: COLORS.text,
    }}>
      <div style={{ fontWeight: 600, marginBottom: 4, color: COLORS.gold }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 2 }}>
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: p.color || COLORS.gold }} />
          <span style={{ color: COLORS.textDim }}>{p.name}:</span>
          <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>{typeof p.value === "number" ? p.value.toFixed(1) : p.value}</span>
        </div>
      ))}
    </div>
  );
}

// ── Main Dashboard ──
export default function GuildHallDashboard() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [preachers, setPreachers] = useState([]);
  const [sermons, setSermons] = useState([]);
  const [units, setUnits] = useState([]);
  const [selectedPreacher, setSelectedPreacher] = useState(null);
  const [view, setView] = useState("overview"); // overview | compare | detail

  // ── Fetch Data ──
  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        setError(null);
        const [p, s, u] = await Promise.all([
          supaQuery("preachers", { select: "*", order: "name.asc" }),
          supaQuery("sermons", { select: "id,title,preacher_id,primary_text,sermon_type,hermeneutical_method,tone,date,series_name", order: "preacher_id.asc" }),
          supaQuery("units", { select: "id,sermon_id,rhetorical_function,doctrinal_loci,unit_index", limit: "10000" }),
        ]);
        setPreachers(p || []);
        setSermons(s || []);
        setUnits(u || []);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  // ── Derived Data ──
  const preacherMap = useMemo(() => {
    const map = {};
    preachers.forEach(p => { map[p.id] = p; });
    return map;
  }, [preachers]);

  const sermonsByPreacher = useMemo(() => {
    const map = {};
    sermons.forEach(s => {
      if (!map[s.preacher_id]) map[s.preacher_id] = [];
      map[s.preacher_id].push(s);
    });
    return map;
  }, [sermons]);

  const unitsBySermon = useMemo(() => {
    const map = {};
    units.forEach(u => {
      if (!map[u.sermon_id]) map[u.sermon_id] = [];
      map[u.sermon_id].push(u);
    });
    return map;
  }, [units]);

  const preacherStats = useMemo(() => {
    return preachers.map(p => {
      const slist = sermonsByPreacher[p.id] || [];
      const ulist = slist.flatMap(s => unitsBySermon[s.id] || []);
      const funcCounts = {};
      const lociCounts = {};
      ulist.forEach(u => {
        if (u.rhetorical_function) funcCounts[u.rhetorical_function] = (funcCounts[u.rhetorical_function] || 0) + 1;
        if (u.doctrinal_loci && Array.isArray(u.doctrinal_loci)) {
          u.doctrinal_loci.forEach(l => { lociCounts[l] = (lociCounts[l] || 0) + 1; });
        }
      });
      const sermonTypes = {};
      slist.forEach(s => {
        if (s.sermon_type) sermonTypes[s.sermon_type] = (sermonTypes[s.sermon_type] || 0) + 1;
      });
      return {
        ...p,
        sermonCount: slist.length,
        unitCount: ulist.length,
        avgUnits: slist.length ? (ulist.length / slist.length).toFixed(1) : "—",
        funcCounts,
        lociCounts,
        sermonTypes,
      };
    }).filter(p => p.sermonCount > 0);
  }, [preachers, sermonsByPreacher, unitsBySermon]);

  // ── Comparison Data ──
  const comparisonRadarData = useMemo(() => {
    const functions = ["exposition", "theological_claim", "illustration", "application", "pastoral_aside", "transition"];
    return functions.map(fn => {
      const row = { function: fn.replace("_", " ") };
      preacherStats.forEach(p => {
        const total = p.unitCount || 1;
        row[p.name] = ((p.funcCounts[fn] || 0) / total * 100);
      });
      return row;
    });
  }, [preacherStats]);

  const overviewBarData = useMemo(() => {
    return preacherStats.map(p => ({
      name: p.name?.split(" ").pop() || "Unknown",
      fullName: p.name,
      sermons: p.sermonCount,
      units: p.unitCount,
      avgUnits: parseFloat(p.avgUnits) || 0,
    })).sort((a, b) => b.sermons - a.sermons);
  }, [preacherStats]);

  // ── Selected Preacher Detail ──
  const detailPreacher = useMemo(() => {
    if (!selectedPreacher) return null;
    return preacherStats.find(p => p.id === selectedPreacher);
  }, [selectedPreacher, preacherStats]);

  const detailFuncData = useMemo(() => {
    if (!detailPreacher) return [];
    return Object.entries(detailPreacher.funcCounts)
      .map(([name, value]) => ({ name: name.replace(/_/g, " "), value, fill: RHETORICAL_COLORS[name] || COLORS.gold }))
      .sort((a, b) => b.value - a.value);
  }, [detailPreacher]);

  const detailLociData = useMemo(() => {
    if (!detailPreacher) return [];
    return Object.entries(detailPreacher.lociCounts)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 10);
  }, [detailPreacher]);

  // ── Render ──
  if (error) {
    return (
      <div style={{ background: COLORS.bg, minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "'DM Sans', sans-serif", color: COLORS.burgundyLight, padding: 40 }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 12 }}>Connection Error</div>
          <div style={{ fontSize: 13, color: COLORS.textDim, maxWidth: 400 }}>{error}</div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ background: COLORS.bg, minHeight: "100vh", fontFamily: "'DM Sans', sans-serif", color: COLORS.text }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;0,700&family=DM+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
        @keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: none; } }
        .fade-in { animation: fadeIn 0.4s ease-out both; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 6px; } ::-webkit-scrollbar-track { background: ${COLORS.bg}; } ::-webkit-scrollbar-thumb { background: ${COLORS.border}; border-radius: 3px; }
      `}</style>

      {/* ── Header ── */}
      <header style={{
        borderBottom: `1px solid ${COLORS.border}`, padding: "24px 32px",
        display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 16,
      }}>
        <div>
          <div style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 11, color: COLORS.goldDim, textTransform: "uppercase", letterSpacing: "0.15em", marginBottom: 4 }}>
            Shepherd's Guild
          </div>
          <h1 style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 28, fontWeight: 600, color: COLORS.gold, lineHeight: 1.2 }}>
            Guild Hall — Preacher Profiles
          </h1>
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          {["overview", "compare", "detail"].map(v => (
            <button key={v} onClick={() => setView(v)} style={{
              background: view === v ? COLORS.gold : "transparent",
              color: view === v ? COLORS.bg : COLORS.textDim,
              border: `1px solid ${view === v ? COLORS.gold : COLORS.border}`,
              borderRadius: 6, padding: "8px 16px", fontSize: 12, fontWeight: 500,
              cursor: "pointer", textTransform: "capitalize", fontFamily: "'DM Sans', sans-serif",
              transition: "all 0.2s",
            }}>
              {v}
            </button>
          ))}
        </div>
      </header>

      <main style={{ padding: "28px 32px", maxWidth: 1200, margin: "0 auto" }}>
        {loading ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {[1, 2, 3, 4].map(i => <Skeleton key={i} height={80} />)}
          </div>
        ) : (
          <div className="fade-in">
            {/* ── Overview ── */}
            {view === "overview" && (
              <div>
                {/* Summary stats */}
                <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 32 }}>
                  <StatCard label="Preachers" value={preacherStats.length} />
                  <StatCard label="Sermons Processed" value={sermons.length} sub={`of 330 target (${(sermons.length / 330 * 100).toFixed(0)}%)`} />
                  <StatCard label="Functional Units" value={units.length.toLocaleString()} />
                  <StatCard label="Avg Units / Sermon" value={(units.length / (sermons.length || 1)).toFixed(1)} />
                </div>

                {/* Sermons per Preacher bar chart */}
                <div style={{ background: COLORS.bgCard, border: `1px solid ${COLORS.border}`, borderRadius: 8, padding: 24, marginBottom: 24 }}>
                  <h3 style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 18, color: COLORS.gold, marginBottom: 20 }}>Sermons per Preacher</h3>
                  <ResponsiveContainer width="100%" height={280}>
                    <BarChart data={overviewBarData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                      <XAxis dataKey="name" tick={{ fill: COLORS.textDim, fontSize: 11, fontFamily: "'DM Sans', sans-serif" }} axisLine={{ stroke: COLORS.border }} tickLine={false} />
                      <YAxis tick={{ fill: COLORS.textDim, fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }} axisLine={false} tickLine={false} />
                      <Tooltip content={<CustomTooltip />} />
                      <Bar dataKey="sermons" fill={COLORS.gold} radius={[4, 4, 0, 0]} name="Sermons" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>

                {/* Preacher cards grid */}
                <h3 style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 18, color: COLORS.gold, marginBottom: 16 }}>Preacher Index</h3>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12 }}>
                  {preacherStats.map(p => (
                    <button key={p.id} onClick={() => { setSelectedPreacher(p.id); setView("detail"); }}
                      style={{
                        background: COLORS.bgCard, border: `1px solid ${COLORS.border}`, borderRadius: 8,
                        padding: "18px 20px", cursor: "pointer", textAlign: "left", transition: "all 0.2s",
                      }}
                      onMouseEnter={e => { e.currentTarget.style.borderColor = COLORS.goldDim; e.currentTarget.style.background = COLORS.bgCardHover; }}
                      onMouseLeave={e => { e.currentTarget.style.borderColor = COLORS.border; e.currentTarget.style.background = COLORS.bgCard; }}
                    >
                      <div style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 18, fontWeight: 600, color: COLORS.cream }}>{p.name}</div>
                      <div style={{ display: "flex", gap: 20, marginTop: 10 }}>
                        <div>
                          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 20, color: COLORS.gold }}>{p.sermonCount}</div>
                          <div style={{ fontSize: 10, color: COLORS.textDim, textTransform: "uppercase", letterSpacing: "0.08em" }}>sermons</div>
                        </div>
                        <div>
                          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 20, color: COLORS.gold }}>{p.unitCount}</div>
                          <div style={{ fontSize: 10, color: COLORS.textDim, textTransform: "uppercase", letterSpacing: "0.08em" }}>units</div>
                        </div>
                        <div>
                          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 20, color: COLORS.gold }}>{p.avgUnits}</div>
                          <div style={{ fontSize: 10, color: COLORS.textDim, textTransform: "uppercase", letterSpacing: "0.08em" }}>avg/sermon</div>
                        </div>
                      </div>
                      {/* Top 3 rhetorical functions mini-bar */}
                      <div style={{ marginTop: 12, display: "flex", gap: 2, height: 4, borderRadius: 2, overflow: "hidden" }}>
                        {Object.entries(p.funcCounts).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([fn, ct]) => (
                          <div key={fn} style={{
                            flex: ct, background: RHETORICAL_COLORS[fn] || COLORS.warmGray, minWidth: 2,
                          }} title={`${fn}: ${ct}`} />
                        ))}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* ── Compare View ── */}
            {view === "compare" && (
              <div>
                <h3 style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 20, color: COLORS.gold, marginBottom: 8 }}>Rhetorical Profile Comparison</h3>
                <p style={{ fontSize: 13, color: COLORS.textDim, marginBottom: 24 }}>
                  Each axis shows what percentage of a preacher's total units serve that rhetorical function.
                </p>
                {preacherStats.length > 0 ? (
                  <div style={{ background: COLORS.bgCard, border: `1px solid ${COLORS.border}`, borderRadius: 8, padding: 24 }}>
                    <ResponsiveContainer width="100%" height={450}>
                      <RadarChart data={comparisonRadarData}>
                        <PolarGrid stroke={COLORS.border} />
                        <PolarAngleAxis dataKey="function" tick={{ fill: COLORS.textDim, fontSize: 11, fontFamily: "'DM Sans', sans-serif" }} />
                        <PolarRadiusAxis tick={{ fill: COLORS.textDim, fontSize: 10 }} axisLine={false} />
                        {preacherStats.map((p, i) => (
                          <Radar key={p.id} name={p.name} dataKey={p.name}
                            stroke={CHART_PALETTE[i % CHART_PALETTE.length]} fill={CHART_PALETTE[i % CHART_PALETTE.length]}
                            fillOpacity={0.08} strokeWidth={2}
                          />
                        ))}
                        <Legend wrapperStyle={{ fontFamily: "'DM Sans', sans-serif", fontSize: 11, color: COLORS.textDim }} />
                        <Tooltip content={<CustomTooltip />} />
                      </RadarChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <div style={{ color: COLORS.textDim, fontSize: 14 }}>No data available for comparison.</div>
                )}

                {/* Units per sermon comparison */}
                <div style={{ background: COLORS.bgCard, border: `1px solid ${COLORS.border}`, borderRadius: 8, padding: 24, marginTop: 24 }}>
                  <h3 style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 18, color: COLORS.gold, marginBottom: 20 }}>Average Units per Sermon</h3>
                  <ResponsiveContainer width="100%" height={250}>
                    <BarChart data={overviewBarData.sort((a, b) => b.avgUnits - a.avgUnits)} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                      <XAxis dataKey="name" tick={{ fill: COLORS.textDim, fontSize: 11 }} axisLine={{ stroke: COLORS.border }} tickLine={false} />
                      <YAxis tick={{ fill: COLORS.textDim, fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }} axisLine={false} tickLine={false} />
                      <Tooltip content={<CustomTooltip />} />
                      <Bar dataKey="avgUnits" fill={COLORS.burgundy} radius={[4, 4, 0, 0]} name="Avg Units" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {/* ── Detail View ── */}
            {view === "detail" && (
              <div>
                {/* Preacher selector */}
                <div style={{ marginBottom: 24, display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {preacherStats.map(p => (
                    <button key={p.id} onClick={() => setSelectedPreacher(p.id)}
                      style={{
                        background: selectedPreacher === p.id ? COLORS.gold : "transparent",
                        color: selectedPreacher === p.id ? COLORS.bg : COLORS.textDim,
                        border: `1px solid ${selectedPreacher === p.id ? COLORS.gold : COLORS.border}`,
                        borderRadius: 20, padding: "6px 14px", fontSize: 12, cursor: "pointer",
                        fontFamily: "'DM Sans', sans-serif", fontWeight: 500, transition: "all 0.2s",
                      }}
                    >
                      {p.name?.split(" ").pop()}
                    </button>
                  ))}
                </div>

                {detailPreacher ? (
                  <div>
                    <h2 style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 28, color: COLORS.cream, fontWeight: 600, marginBottom: 4 }}>{detailPreacher.name}</h2>
                    <div style={{ fontSize: 13, color: COLORS.textDim, marginBottom: 24 }}>
                      {detailPreacher.sermonCount} sermons · {detailPreacher.unitCount} units · {detailPreacher.avgUnits} avg units/sermon
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
                      {/* Rhetorical Function Pie */}
                      <div style={{ background: COLORS.bgCard, border: `1px solid ${COLORS.border}`, borderRadius: 8, padding: 24 }}>
                        <h4 style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 16, color: COLORS.gold, marginBottom: 16 }}>Rhetorical Function Distribution</h4>
                        <ResponsiveContainer width="100%" height={280}>
                          <PieChart>
                            <Pie data={detailFuncData} dataKey="value" nameKey="name" cx="50%" cy="50%"
                              innerRadius={50} outerRadius={100} paddingAngle={2}>
                              {detailFuncData.map((entry, i) => (
                                <Cell key={i} fill={entry.fill} />
                              ))}
                            </Pie>
                            <Tooltip content={<CustomTooltip />} />
                            <Legend wrapperStyle={{ fontFamily: "'DM Sans', sans-serif", fontSize: 11, color: COLORS.textDim }} />
                          </PieChart>
                        </ResponsiveContainer>
                      </div>

                      {/* Top Doctrinal Loci */}
                      <div style={{ background: COLORS.bgCard, border: `1px solid ${COLORS.border}`, borderRadius: 8, padding: 24 }}>
                        <h4 style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 16, color: COLORS.gold, marginBottom: 16 }}>Top Doctrinal Loci</h4>
                        <ResponsiveContainer width="100%" height={280}>
                          <BarChart data={detailLociData} layout="vertical" margin={{ top: 0, right: 20, bottom: 0, left: 80 }}>
                            <XAxis type="number" tick={{ fill: COLORS.textDim, fontSize: 10, fontFamily: "'JetBrains Mono', monospace" }} axisLine={false} tickLine={false} />
                            <YAxis type="category" dataKey="name" tick={{ fill: COLORS.textDim, fontSize: 10, fontFamily: "'DM Sans', sans-serif" }} axisLine={false} tickLine={false} width={80} />
                            <Tooltip content={<CustomTooltip />} />
                            <Bar dataKey="value" fill={COLORS.forest} radius={[0, 4, 4, 0]} name="Units" />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    </div>

                    {/* Sermon Type Distribution */}
                    {Object.keys(detailPreacher.sermonTypes).length > 0 && (
                      <div style={{ background: COLORS.bgCard, border: `1px solid ${COLORS.border}`, borderRadius: 8, padding: 24, marginTop: 20 }}>
                        <h4 style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 16, color: COLORS.gold, marginBottom: 16 }}>Sermon Types</h4>
                        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                          {Object.entries(detailPreacher.sermonTypes).sort((a, b) => b[1] - a[1]).map(([type, count]) => (
                            <div key={type} style={{
                              background: COLORS.bg, border: `1px solid ${COLORS.border}`, borderRadius: 6,
                              padding: "12px 18px", textAlign: "center",
                            }}>
                              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 22, color: COLORS.gold }}>{count}</div>
                              <div style={{ fontSize: 11, color: COLORS.textDim, textTransform: "capitalize", marginTop: 2 }}>{type}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Sermon List */}
                    <div style={{ background: COLORS.bgCard, border: `1px solid ${COLORS.border}`, borderRadius: 8, padding: 24, marginTop: 20 }}>
                      <h4 style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 16, color: COLORS.gold, marginBottom: 16 }}>Sermons</h4>
                      <div style={{ maxHeight: 300, overflowY: "auto" }}>
                        {(sermonsByPreacher[detailPreacher.id] || []).map((s, i) => {
                          const uCount = (unitsBySermon[s.id] || []).length;
                          return (
                            <div key={s.id} style={{
                              padding: "10px 0", borderBottom: `1px solid ${COLORS.border}`,
                              display: "flex", justifyContent: "space-between", alignItems: "baseline",
                            }}>
                              <div>
                                <span style={{ color: COLORS.cream, fontSize: 13 }}>{s.title || "Untitled"}</span>
                                {s.primary_text && <span style={{ color: COLORS.goldDim, fontSize: 11, marginLeft: 10 }}>{s.primary_text}</span>}
                              </div>
                              <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: COLORS.warmGray, whiteSpace: "nowrap", marginLeft: 12 }}>
                                {uCount} units
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div style={{ textAlign: "center", padding: 60, color: COLORS.textDim }}>
                    <div style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 20, color: COLORS.goldDim, marginBottom: 8 }}>Select a Preacher</div>
                    <div style={{ fontSize: 13 }}>Choose from the buttons above to see detailed profile stats.</div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </main>

      {/* ── Footer ── */}
      <footer style={{ borderTop: `1px solid ${COLORS.border}`, padding: "20px 32px", textAlign: "center", marginTop: 40 }}>
        <div style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 13, color: COLORS.goldDim, letterSpacing: "0.08em" }}>Shepherd's Guild</div>
        <div style={{ fontSize: 11, color: COLORS.warmGray, marginTop: 4 }}>Guild Hall Dashboard · Live from Supabase</div>
      </footer>
    </div>
  );
}
