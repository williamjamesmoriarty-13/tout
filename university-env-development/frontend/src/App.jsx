import { useState, useEffect, useCallback, useRef } from "react";

// ─── CONFIG API ────────────────────────────────────────────────────────────────
const STUDENT_URL  = import.meta?.env?.VITE_STUDENT_SERVICE_URL  || "/api/students";
const TEACHER_URL  = import.meta?.env?.VITE_TEACHER_ADMIN_SERVICE_URL || "/api/teachers";
const ENROLL_URL   = import.meta?.env?.VITE_ENROLLMENT_SERVICE_URL   || "/api/enrollments";
const STUDENT_SERVICE_URL = import.meta.env.VITE_STUDENT_SERVICE_URL || "/api/students";
const TEACHER_ADMIN_SERVICE_URL = import.meta.env.VITE_TEACHER_ADMIN_SERVICE_URL || "/api/teachers";
const ENROLLMENT_SERVICE_URL = import.meta.env.VITE_ENROLLMENT_SERVICE_URL || "/api/enrollments";
console.log(STUDENT_URL)
console.log(STUDENT_SERVICE_URL)
async function api(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const ct = res.headers.get("content-type") || "";
  const body = ct.includes("application/json") ? await res.json() : null;
  if (!res.ok) throw new Error(body?.error || body?.detail || `Erreur ${res.status}`);
  return body;
}

const API = {
  // Students
  listStudents:   ()     => api(`${STUDENT_URL}/students`),
  getStudent:     (id)   => api(`${STUDENT_URL}/students/${id}`),
  createStudent:  (d)    => api(`${STUDENT_URL}/students`, { method:"POST", body:JSON.stringify(d) }),
  updateStudent:  (id,d) => api(`${STUDENT_URL}/students/${id}`, { method:"PUT", body:JSON.stringify(d) }),
  deleteStudent:  (id)   => api(`${STUDENT_URL}/students/${id}`, { method:"DELETE" }),
  studentCourses: (id)   => api(`${STUDENT_URL}/students/${id}/available-courses`),
  studentEnrolls: (id)   => api(`${STUDENT_URL}/students/${id}/enrollments`),
  studentGrades:  (id)   => api(`${STUDENT_URL}/students/${id}/grades`),
  // Courses
  listCourses:    ()     => api(`${TEACHER_URL}/courses`),
  getCourse:      (id)   => api(`${TEACHER_URL}/courses/${id}`),
  createCourse:   (d)    => api(`${TEACHER_URL}/courses`, { method:"POST", body:JSON.stringify(d) }),
  // Announcements
  listAnnouncements: (cid) => api(`${TEACHER_URL}/announcements?courseId=${cid}`),
  createAnnouncement: (d)  => api(`${TEACHER_URL}/announcements`, { method:"POST", body:JSON.stringify(d) }),
  // Grades
  listGrades:     (sid)  => api(`${TEACHER_URL}/grades?studentId=${sid}`),
  submitGrade:    (d)    => api(`${TEACHER_URL}/grades`, { method:"POST", body:JSON.stringify(d) }),
  // Enrollments
  listEnrollments:   ()    => api(`${ENROLL_URL}/enrollments`),
  createEnrollment:  (d)   => api(`${ENROLL_URL}/enrollments`, { method:"POST", body:JSON.stringify(d) }),
  cancelEnrollment:  (id)  => api(`${ENROLL_URL}/enrollments/${id}`, { method:"DELETE" }),
  studentGradesProxy:(sid) => api(`${ENROLL_URL}/grades?student_id=${sid}`),
};

// ─── DESIGN TOKENS ─────────────────────────────────────────────────────────────
const G = {
  900: "#4A0E1A",
  800: "#7B1C2E",
  700: "#A52840",
  600: "#C94060",
  400: "#E8A0B0",
  200: "#F5E8EB",
  100: "#FDF5F7",
  white: "#FFFFFF",
  gray50: "#F9FAFB",
  gray100: "#F3F4F6",
  gray200: "#E5E7EB",
  gray400: "#9CA3AF",
  gray600: "#4B5563",
  gray800: "#1F2937",
  success: "#059669",
  warning: "#D97706",
  danger: "#DC2626",
};

// ─── ICONS (SVG inline, pas de dépendance icône) ──────────────────────────────
const Icon = {
  Dashboard: () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>,
  Students:  () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>,
  Courses:   () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>,
  Enroll:    () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>,
  Grades:    () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>,
  Announce:  () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 17H2a3 3 0 0 0 3-3V9a7 7 0 0 1 14 0v5a3 3 0 0 0 3 3zm-8.27 4a2 2 0 0 1-3.46 0"/></svg>,
  Plus:      () => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>,
  Edit:      () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>,
  Trash:     () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>,
  Search:    () => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>,
  Close:     () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>,
  Eye:       () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>,
  Cap:       () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/></svg>,
  Check:     () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>,
  Alert:     () => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>,
  Collapse:  () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 18 9 12 15 6"/></svg>,
};

// ─── COMPOSANTS DE BASE ────────────────────────────────────────────────────────

function Toast({ toasts, remove }) {
  return (
    <div style={{ position:"fixed", bottom:24, right:24, zIndex:9999, display:"flex", flexDirection:"column", gap:8 }}>
      {toasts.map(t => (
        <div key={t.id} style={{
          display:"flex", alignItems:"center", gap:12, padding:"12px 16px",
          background: t.type==="error" ? G[700] : t.type==="warning" ? G.warning : G.success,
          color: G.white, borderRadius:10, boxShadow:"0 4px 20px rgba(0,0,0,.25)",
          minWidth:280, maxWidth:400, animation:"slideIn .2s ease",
        }}>
          <span style={{flexShrink:0}}><Icon.Alert /></span>
          <span style={{flex:1, fontSize:14, fontWeight:500}}>{t.msg}</span>
          <button onClick={() => remove(t.id)} style={{ background:"none", border:"none", color:G.white, cursor:"pointer", padding:0, opacity:.8 }}>
            <Icon.Close />
          </button>
        </div>
      ))}
    </div>
  );
}

function useToast() {
  const [toasts, setToasts] = useState([]);
  const add = useCallback((msg, type="success") => {
    const id = Date.now();
    setToasts(p => [...p, { id, msg, type }]);
    setTimeout(() => setToasts(p => p.filter(t => t.id !== id)), 4000);
  }, []);
  const remove = useCallback(id => setToasts(p => p.filter(t => t.id !== id)), []);
  return { toasts, toast: add, remove };
}

function Drawer({ open, onClose, title, children, width=520 }) {
  useEffect(() => {
    const handler = e => { if (e.key === "Escape") onClose(); };
    if (open) window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  return (
    <>
      {open && (
        <div onClick={onClose} style={{
          position:"fixed", inset:0, background:"rgba(74,14,26,.35)", zIndex:200, backdropFilter:"blur(2px)"
        }} />
      )}
      <div style={{
        position:"fixed", top:0, right:0, height:"100vh", width, zIndex:201, background:G.white,
        boxShadow:"-8px 0 40px rgba(74,14,26,.18)", transform: open?"translateX(0)":"translateX(100%)",
        transition:"transform .3s cubic-bezier(.4,0,.2,1)", display:"flex", flexDirection:"column",
      }}>
        <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between",
          padding:"20px 28px", borderBottom:`1px solid ${G.gray200}`, background:G[200] }}>
          <h2 style={{ margin:0, fontSize:18, fontWeight:700, color:G[800], fontFamily:"Playfair Display, Georgia, serif" }}>{title}</h2>
          <button onClick={onClose} style={{ background:"none", border:`1.5px solid ${G[400]}`, borderRadius:8,
            color:G[700], cursor:"pointer", padding:"6px 8px", display:"flex", alignItems:"center" }}>
            <Icon.Close />
          </button>
        </div>
        <div style={{ flex:1, overflowY:"auto", padding:28 }}>{children}</div>
      </div>
    </>
  );
}

function Modal({ open, onClose, title, children }) {
  useEffect(() => {
    const handler = e => { if (e.key === "Escape") onClose(); };
    if (open) window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div style={{ position:"fixed", inset:0, zIndex:300, display:"flex", alignItems:"center", justifyContent:"center" }}>
      <div onClick={onClose} style={{ position:"absolute", inset:0, background:"rgba(74,14,26,.4)", backdropFilter:"blur(3px)" }} />
      <div style={{ position:"relative", background:G.white, borderRadius:16, padding:32, maxWidth:440,
        width:"90%", boxShadow:"0 20px 60px rgba(74,14,26,.3)", zIndex:1 }}>
        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:20 }}>
          <h3 style={{ margin:0, fontSize:17, fontWeight:700, color:G[800], fontFamily:"Playfair Display, Georgia, serif" }}>{title}</h3>
          <button onClick={onClose} style={{ background:"none", border:"none", cursor:"pointer", color:G[600] }}><Icon.Close /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Field({ label, error, children }) {
  return (
    <div style={{ marginBottom:20 }}>
      <label style={{ display:"block", fontSize:13, fontWeight:600, color:G[800], marginBottom:6 }}>{label}</label>
      {children}
      {error && <span style={{ fontSize:12, color:G.danger, marginTop:4, display:"block" }}>{error}</span>}
    </div>
  );
}

const inputStyle = {
  width:"100%", padding:"10px 14px", borderRadius:8, fontSize:14, color:G.gray800,
  border:`1.5px solid ${G.gray200}`, outline:"none", background:G.white, boxSizing:"border-box",
  transition:"border-color .15s",
  fontFamily:"Inter, system-ui, sans-serif",
};

function Input({ ...props }) {
  const [focused, setFocused] = useState(false);
  return <input {...props}
    style={{ ...inputStyle, borderColor: focused ? G[600] : G.gray200, boxShadow: focused ? `0 0 0 3px ${G[200]}` : "none" }}
    onFocus={e => { setFocused(true); props.onFocus?.(e); }}
    onBlur={e => { setFocused(false); props.onBlur?.(e); }}
  />;
}

function Select({ children, ...props }) {
  return (
    <select {...props} style={{ ...inputStyle, cursor:"pointer", appearance:"none",
      backgroundImage:`url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%237B1C2E' stroke-width='1.5' fill='none'/%3E%3C/svg%3E")`,
      backgroundRepeat:"no-repeat", backgroundPosition:"right 12px center", paddingRight:36 }}>
      {children}
    </select>
  );
}

function Textarea({ ...props }) {
  const [focused, setFocused] = useState(false);
  return <textarea {...props}
    style={{ ...inputStyle, resize:"vertical", minHeight:90, borderColor: focused ? G[600] : G.gray200,
      boxShadow: focused ? `0 0 0 3px ${G[200]}` : "none" }}
    onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
  />;
}

function Btn({ variant="primary", size="md", icon, onClick, disabled, children, style:s={} }) {
  const [hov, setHov] = useState(false);
  const base = {
    display:"inline-flex", alignItems:"center", gap:6, border:"none", borderRadius:8,
    cursor: disabled ? "not-allowed" : "pointer", fontWeight:600, fontFamily:"Inter, system-ui, sans-serif",
    transition:"all .15s", opacity: disabled ? .55 : 1, ...s,
  };
  const sizes = { sm:{ padding:"6px 12px", fontSize:12 }, md:{ padding:"9px 18px", fontSize:14 }, lg:{ padding:"12px 24px", fontSize:15 } };
  const variants = {
    primary: { background: hov ? G[800] : G[700], color:G.white, boxShadow: hov ? "0 4px 14px rgba(165,40,64,.4)" : "none" },
    secondary: { background: hov ? G[200] : G.white, color:G[700], border:`1.5px solid ${G[400]}` },
    danger: { background: hov ? "#B91C1C" : G.danger, color:G.white },
    ghost: { background:"transparent", color: hov ? G[700] : G.gray600 },
  };
  return (
    <button onClick={disabled ? undefined : onClick} disabled={disabled}
      style={{ ...base, ...sizes[size], ...variants[variant] }}
      onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}>
      {icon && <span style={{display:"flex"}}>{icon}</span>}
      {children}
    </button>
  );
}

function Badge({ color, children }) {
  const colors = {
    green:  { bg:"#D1FAE5", text:"#065F46" },
    red:    { bg:"#FEE2E2", text:"#991B1B" },
    garnet: { bg:G[200],   text:G[800] },
    yellow: { bg:"#FEF3C7", text:"#92400E" },
    gray:   { bg:G.gray100, text:G.gray600 },
  };
  const c = colors[color] || colors.gray;
  return <span style={{ display:"inline-flex", alignItems:"center", gap:4, padding:"3px 10px",
    borderRadius:99, fontSize:12, fontWeight:600, background:c.bg, color:c.text }}>{children}</span>;
}

function SearchBar({ value, onChange, placeholder }) {
  return (
    <div style={{ position:"relative", flexShrink:0 }}>
      <span style={{ position:"absolute", left:12, top:"50%", transform:"translateY(-50%)", color:G.gray400, pointerEvents:"none" }}>
        <Icon.Search />
      </span>
      <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        style={{ ...inputStyle, paddingLeft:38, width:260 }} />
    </div>
  );
}

function EmptyState({ icon, title, sub, action }) {
  return (
    <div style={{ textAlign:"center", padding:"64px 24px", color:G.gray400 }}>
      <div style={{ fontSize:56, marginBottom:16, opacity:.4 }}>{icon}</div>
      <div style={{ fontSize:17, fontWeight:600, color:G.gray600, marginBottom:8, fontFamily:"Playfair Display, Georgia, serif" }}>{title}</div>
      <div style={{ fontSize:14, marginBottom:24 }}>{sub}</div>
      {action}
    </div>
  );
}

function Spinner() {
  return (
    <div style={{ display:"flex", justifyContent:"center", alignItems:"center", padding:48 }}>
      <div style={{ width:36, height:36, border:`3px solid ${G[200]}`, borderTopColor:G[600],
        borderRadius:"50%", animation:"spin 0.7s linear infinite" }} />
    </div>
  );
}

function Table({ cols, rows, onRowClick }) {
  return (
    <div style={{ overflowX:"auto" }}>
      <table style={{ width:"100%", borderCollapse:"collapse", fontSize:14 }}>
        <thead>
          <tr>
            {cols.map(c => (
              <th key={c.key} style={{ padding:"12px 16px", textAlign:"left", fontSize:12, fontWeight:700,
                color:G[800], background:G[100], borderBottom:`2px solid ${G[200]}`,
                whiteSpace:"nowrap", letterSpacing:.3 }}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} onClick={() => onRowClick?.(row)}
              style={{ borderBottom:`1px solid ${G.gray100}`, cursor: onRowClick ? "pointer" : "default",
                transition:"background .1s" }}
              onMouseEnter={e => { if(onRowClick) e.currentTarget.style.background=G[100]; }}
              onMouseLeave={e => { e.currentTarget.style.background="transparent"; }}>
              {cols.map(c => (
                <td key={c.key} style={{ padding:"13px 16px", color:G.gray800, verticalAlign:"middle" }}>
                  {c.render ? c.render(row) : row[c.key] ?? <span style={{color:G.gray400}}>—</span>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PageHeader({ title, sub, action }) {
  return (
    <div style={{ display:"flex", alignItems:"flex-start", justifyContent:"space-between",
      marginBottom:28, gap:16, flexWrap:"wrap" }}>
      <div>
        <h1 style={{ margin:0, fontSize:26, fontWeight:800, color:G[800],
          fontFamily:"Playfair Display, Georgia, serif", lineHeight:1.2 }}>{title}</h1>
        {sub && <p style={{ margin:"6px 0 0", fontSize:14, color:G.gray400 }}>{sub}</p>}
      </div>
      {action}
    </div>
  );
}

// ─── PAGE DASHBOARD ────────────────────────────────────────────────────────────
function Dashboard({ onNavigate }) {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.allSettled([
      API.listStudents(),
      API.listCourses(),
      API.listEnrollments(),
    ]).then(([s, c, e]) => {
      setStats({
        students: s.status==="fulfilled" ? (s.value||[]).length : "—",
        courses:  c.status==="fulfilled" ? (c.value||[]).length : "—",
        enrollments: e.status==="fulfilled" ? (e.value||[]).length : "—",
        activeEnrollments: e.status==="fulfilled"
          ? (e.value||[]).filter(x=>x.status==="enrolled").length : "—",
      });
      setLoading(false);
    });
  }, []);

  const cards = [
    { label:"Étudiants inscrits",  value:stats?.students,     color:G[700], icon:"🎓", page:"students" },
    { label:"Cours disponibles",   value:stats?.courses,      color:G[600], icon:"📚", page:"courses"  },
    { label:"Inscriptions totales",value:stats?.enrollments,  color:G[800], icon:"📋", page:"enrollments" },
    { label:"Inscriptions actives",value:stats?.activeEnrollments, color:G[900], icon:"✅", page:"enrollments" },
  ];

  return (
    <div>
      <PageHeader
        title="Tableau de bord"
        sub="Vue d'ensemble du système universitaire"
      />
      {loading ? <Spinner /> : (
        <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fit, minmax(220px,1fr))", gap:20, marginBottom:36 }}>
          {cards.map(c => (
            <div key={c.label} onClick={() => onNavigate(c.page)}
              style={{ background:c.color, borderRadius:14, padding:"28px 24px", cursor:"pointer",
                color:G.white, transition:"transform .15s, box-shadow .15s", boxShadow:"0 4px 16px rgba(74,14,26,.18)" }}
              onMouseEnter={e=>e.currentTarget.style.transform="translateY(-3px)"}
              onMouseLeave={e=>e.currentTarget.style.transform="translateY(0)"}>
              <div style={{ fontSize:32, marginBottom:12 }}>{c.icon}</div>
              <div style={{ fontSize:36, fontWeight:800, lineHeight:1, marginBottom:6,
                fontFamily:"Playfair Display, Georgia, serif" }}>{c.value}</div>
              <div style={{ fontSize:13, opacity:.85, fontWeight:500 }}>{c.label}</div>
            </div>
          ))}
        </div>
      )}
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:20 }}>
        <QuickActions onNavigate={onNavigate} />
        <RecentActivity />
      </div>
    </div>
  );
}

function QuickActions({ onNavigate }) {
  const actions = [
    { icon:"👤", label:"Ajouter un étudiant",    page:"students",    sub:"Créer un nouveau profil" },
    { icon:"📖", label:"Créer un cours",          page:"courses",     sub:"Définir un nouveau cours" },
    { icon:"✍️", label:"Gérer les inscriptions",  page:"enrollments", sub:"Inscrire ou désinscrire" },
    { icon:"📊", label:"Saisir des notes",        page:"grades",      sub:"Enregistrer les résultats" },
  ];
  return (
    <div style={{ background:G.white, borderRadius:14, padding:24, border:`1px solid ${G.gray200}` }}>
      <h3 style={{ margin:"0 0 18px", fontSize:16, fontWeight:700, color:G[800],
        fontFamily:"Playfair Display, Georgia, serif" }}>Actions rapides</h3>
      <div style={{ display:"flex", flexDirection:"column", gap:10 }}>
        {actions.map(a => (
          <button key={a.page} onClick={() => onNavigate(a.page)}
            style={{ display:"flex", alignItems:"center", gap:14, padding:"12px 16px",
              border:`1.5px solid ${G[200]}`, borderRadius:10, background:G[100],
              cursor:"pointer", textAlign:"left", transition:"all .15s" }}
            onMouseEnter={e=>{e.currentTarget.style.borderColor=G[400]; e.currentTarget.style.background=G[200];}}
            onMouseLeave={e=>{e.currentTarget.style.borderColor=G[200]; e.currentTarget.style.background=G[100];}}>
            <span style={{fontSize:22}}>{a.icon}</span>
            <div>
              <div style={{fontSize:14, fontWeight:600, color:G[800]}}>{a.label}</div>
              <div style={{fontSize:12, color:G.gray400}}>{a.sub}</div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function RecentActivity() {
  const [enrollments, setEnrollments] = useState([]);
  useEffect(() => {
    API.listEnrollments().then(d => setEnrollments((d||[]).slice(-5).reverse())).catch(()=>{});
  }, []);
  return (
    <div style={{ background:G.white, borderRadius:14, padding:24, border:`1px solid ${G.gray200}` }}>
      <h3 style={{ margin:"0 0 18px", fontSize:16, fontWeight:700, color:G[800],
        fontFamily:"Playfair Display, Georgia, serif" }}>Dernières inscriptions</h3>
      {enrollments.length === 0
        ? <p style={{color:G.gray400, fontSize:14}}>Aucune inscription récente.</p>
        : <div style={{display:"flex",flexDirection:"column",gap:10}}>
            {enrollments.map(e => (
              <div key={e.id} style={{display:"flex",alignItems:"center",gap:12,
                padding:"10px 14px",background:G[100],borderRadius:9}}>
                <div style={{width:36,height:36,borderRadius:"50%",background:G[700],
                  display:"flex",alignItems:"center",justifyContent:"center",color:G.white,
                  fontSize:14,fontWeight:700,flexShrink:0}}>
                  {e.student_id}
                </div>
                <div>
                  <div style={{fontSize:13,fontWeight:600,color:G[800]}}>
                    Étudiant #{e.student_id} → Cours #{e.course_id}
                  </div>
                  <div style={{fontSize:11,color:G.gray400}}>
                    {e.created_at ? new Date(e.created_at).toLocaleDateString("fr-FR") : "—"}
                  </div>
                </div>
                <div style={{marginLeft:"auto"}}>
                  <Badge color={e.status==="enrolled" ? "green" : "gray"}>{e.status}</Badge>
                </div>
              </div>
            ))}
          </div>
      }
    </div>
  );
}

// ─── PAGE ÉTUDIANTS ────────────────────────────────────────────────────────────
function StudentsPage({ toast }) {
  const [students, setStudents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [drawer, setDrawer] = useState(null); // null | "create" | "edit" | "view"
  const [selected, setSelected] = useState(null);
  const [delModal, setDelModal] = useState(null);
  const [form, setForm] = useState({ first_name:"", last_name:"", email:"" });
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [studentDetails, setStudentDetails] = useState({});

  const load = useCallback(() => {
    setLoading(true);
    API.listStudents().then(d => { setStudents(d||[]); setLoading(false); })
      .catch(() => { toast("Erreur lors du chargement des étudiants", "error"); setLoading(false); });
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  const filtered = students.filter(s =>
    `${s.first_name} ${s.last_name} ${s.email}`.toLowerCase().includes(search.toLowerCase())
  );

  function validate() {
    const e = {};
    if (!form.first_name.trim()) e.first_name = "Le prénom est requis";
    if (!form.last_name.trim()) e.last_name = "Le nom est requis";
    if (!form.email.match(/^[^\s@]+@[^\s@]+\.[^\s@]+$/)) e.email = "Email invalide";
    return e;
  }

  async function handleSave() {
    const e = validate();
    if (Object.keys(e).length) { setErrors(e); return; }
    setSaving(true);
    try {
      if (drawer === "edit") {
        await API.updateStudent(selected.id, form);
        toast("Étudiant mis à jour");
      } else {
        await API.createStudent(form);
        toast("Étudiant créé avec succès");
      }
      setDrawer(null); load();
    } catch(err) {
      toast(err.message, "error");
    } finally { setSaving(false); }
  }

  async function handleDelete() {
    try {
      await API.deleteStudent(delModal.id);
      toast("Étudiant supprimé");
      setDelModal(null); load();
    } catch(err) { toast(err.message, "error"); }
  }

  async function openView(s) {
    setSelected(s); setDrawer("view");
    const [courses, enrolls, grades] = await Promise.allSettled([
      API.studentCourses(s.id),
      API.studentEnrolls(s.id),
      API.studentGradesProxy(s.id),
    ]);
    setStudentDetails({
      courses: courses.status==="fulfilled" ? (courses.value||[]) : [],
      enrolls: enrolls.status==="fulfilled" ? (enrolls.value||[]) : [],
      grades:  grades.status==="fulfilled"  ? (grades.value||[])  : [],
    });
  }

  const cols = [
    { key:"id", label:"ID", render: r => <span style={{color:G[600], fontWeight:700}}>#{r.id}</span> },
    { key:"name", label:"Nom complet", render: r => (
      <div style={{display:"flex",alignItems:"center",gap:10}}>
        <div style={{width:34,height:34,borderRadius:"50%",background:G[700],
          display:"flex",alignItems:"center",justifyContent:"center",
          color:G.white,fontSize:13,fontWeight:700,flexShrink:0}}>
          {r.first_name[0]}{r.last_name[0]}
        </div>
        <div>
          <div style={{fontWeight:600,color:G.gray800}}>{r.first_name} {r.last_name}</div>
          <div style={{fontSize:12,color:G.gray400}}>{r.email}</div>
        </div>
      </div>
    )},
    { key:"email", label:"Email", render: r => <span style={{color:G.gray600}}>{r.email}</span> },
    { key:"created_at", label:"Inscription", render: r => r.created_at
      ? new Date(r.created_at).toLocaleDateString("fr-FR") : "—" },
    { key:"actions", label:"", render: r => (
      <div style={{display:"flex",gap:6}} onClick={e=>e.stopPropagation()}>
        <Btn variant="ghost" size="sm" icon={<Icon.Eye/>} onClick={()=>openView(r)}>Voir</Btn>
        <Btn variant="secondary" size="sm" icon={<Icon.Edit/>} onClick={()=>{
          setSelected(r); setForm({first_name:r.first_name,last_name:r.last_name,email:r.email});
          setErrors({}); setDrawer("edit");
        }}>Modifier</Btn>
        <Btn variant="danger" size="sm" icon={<Icon.Trash/>} onClick={()=>setDelModal(r)}>Supprimer</Btn>
      </div>
    )},
  ];

  return (
    <div>
      <PageHeader
        title="Étudiants"
        sub={`${students.length} étudiant${students.length>1?"s":""} enregistré${students.length>1?"s":""}`}
        action={<Btn variant="primary" icon={<Icon.Plus/>} onClick={()=>{
          setForm({first_name:"",last_name:"",email:""}); setErrors({}); setDrawer("create");
        }}>Nouvel étudiant</Btn>}
      />

      <div style={{ background:G.white, borderRadius:14, border:`1px solid ${G.gray200}`, overflow:"hidden" }}>
        <div style={{ padding:"16px 20px", borderBottom:`1px solid ${G.gray100}`,
          display:"flex", alignItems:"center", gap:12 }}>
          <SearchBar value={search} onChange={setSearch} placeholder="Rechercher par nom, email…" />
          <span style={{fontSize:13,color:G.gray400,marginLeft:"auto"}}>
            {filtered.length} résultat{filtered.length!==1?"s":""}
          </span>
        </div>
        {loading ? <Spinner /> : filtered.length === 0
          ? <EmptyState icon="👤" title="Aucun étudiant trouvé"
              sub={search ? "Essayez d'autres termes de recherche" : "Commencez par ajouter un étudiant"}
              action={!search && <Btn variant="primary" icon={<Icon.Plus/>} onClick={()=>{
                setForm({first_name:"",last_name:"",email:""}); setErrors({}); setDrawer("create");
              }}>Premier étudiant</Btn>}
            />
          : <Table cols={cols} rows={filtered} />
        }
      </div>

      {/* Drawer créer/modifier */}
      <Drawer open={drawer==="create"||drawer==="edit"} onClose={()=>setDrawer(null)}
        title={drawer==="edit" ? "Modifier l'étudiant" : "Nouvel étudiant"}>
        <Field label="Prénom *" error={errors.first_name}>
          <Input value={form.first_name} onChange={e=>setForm(p=>({...p,first_name:e.target.value}))} placeholder="ex: Marie" />
        </Field>
        <Field label="Nom *" error={errors.last_name}>
          <Input value={form.last_name} onChange={e=>setForm(p=>({...p,last_name:e.target.value}))} placeholder="ex: Curie" />
        </Field>
        <Field label="Adresse email *" error={errors.email}>
          <Input type="email" value={form.email} onChange={e=>setForm(p=>({...p,email:e.target.value}))} placeholder="ex: marie.curie@universite.fr" />
        </Field>
        <div style={{display:"flex",gap:12,marginTop:8}}>
          <Btn variant="primary" onClick={handleSave} disabled={saving}>
            {saving ? "Enregistrement…" : drawer==="edit" ? "Mettre à jour" : "Créer l'étudiant"}
          </Btn>
          <Btn variant="secondary" onClick={()=>setDrawer(null)}>Annuler</Btn>
        </div>
      </Drawer>

      {/* Drawer vue détaillée */}
      <Drawer open={drawer==="view"} onClose={()=>setDrawer(null)}
        title={selected ? `${selected.first_name} ${selected.last_name}` : ""} width={580}>
        {selected && (
          <>
            <div style={{ background:G[800], borderRadius:12, padding:20, marginBottom:24,
              display:"flex", alignItems:"center", gap:16 }}>
              <div style={{ width:56, height:56, borderRadius:"50%", background:G[600],
                display:"flex", alignItems:"center", justifyContent:"center",
                color:G.white, fontSize:20, fontWeight:800 }}>
                {selected.first_name[0]}{selected.last_name[0]}
              </div>
              <div style={{color:G.white}}>
                <div style={{fontSize:18,fontWeight:700,fontFamily:"Playfair Display, Georgia, serif"}}>
                  {selected.first_name} {selected.last_name}
                </div>
                <div style={{fontSize:13,opacity:.8}}>{selected.email}</div>
                <div style={{fontSize:12,opacity:.6,marginTop:2}}>ID #{selected.id}</div>
              </div>
            </div>

            <div style={{marginBottom:24}}>
              <h4 style={{margin:"0 0 12px",fontSize:14,fontWeight:700,color:G[700],textTransform:"uppercase",letterSpacing:.5}}>
                Cours disponibles ({(studentDetails.courses||[]).length})
              </h4>
              {(studentDetails.courses||[]).length===0
                ? <p style={{color:G.gray400,fontSize:13}}>Aucun cours disponible</p>
                : (studentDetails.courses||[]).slice(0,4).map(c=>(
                    <div key={c.id} style={{display:"flex",justifyContent:"space-between",
                      padding:"10px 14px",background:G[100],borderRadius:8,marginBottom:6}}>
                      <span style={{fontSize:13,fontWeight:600,color:G.gray800}}>{c.title}</span>
                      <Badge color="garnet">{c.availableSeats} places</Badge>
                    </div>
                  ))
              }
            </div>

            <div style={{marginBottom:24}}>
              <h4 style={{margin:"0 0 12px",fontSize:14,fontWeight:700,color:G[700],textTransform:"uppercase",letterSpacing:.5}}>
                Inscriptions ({(studentDetails.enrolls||[]).length})
              </h4>
              {(studentDetails.enrolls||[]).length===0
                ? <p style={{color:G.gray400,fontSize:13}}>Aucune inscription</p>
                : (studentDetails.enrolls||[]).map(e=>(
                    <div key={e.id} style={{display:"flex",justifyContent:"space-between",
                      padding:"10px 14px",background:G[100],borderRadius:8,marginBottom:6}}>
                      <span style={{fontSize:13,fontWeight:600,color:G.gray800}}>Cours #{e.course_id}</span>
                      <Badge color={e.status==="enrolled"?"green":"gray"}>{e.status}</Badge>
                    </div>
                  ))
              }
            </div>

            <div>
              <h4 style={{margin:"0 0 12px",fontSize:14,fontWeight:700,color:G[700],textTransform:"uppercase",letterSpacing:.5}}>
                Notes ({(studentDetails.grades||[]).length})
              </h4>
              {(studentDetails.grades||[]).length===0
                ? <p style={{color:G.gray400,fontSize:13}}>Aucune note enregistrée</p>
                : (studentDetails.grades||[]).map(g=>(
                    <div key={g.id} style={{display:"flex",justifyContent:"space-between",
                      padding:"10px 14px",background:G[100],borderRadius:8,marginBottom:6}}>
                      <span style={{fontSize:13,fontWeight:600,color:G.gray800}}>Cours #{g.course_id}</span>
                      <span style={{fontSize:15,fontWeight:800,color:
                        g.value>=14?G.success:g.value>=10?G.warning:G.danger}}>
                        {g.value}/20
                      </span>
                    </div>
                  ))
              }
            </div>
          </>
        )}
      </Drawer>

      {/* Modal suppression */}
      <Modal open={!!delModal} onClose={()=>setDelModal(null)} title="Confirmer la suppression">
        <p style={{color:G.gray600,fontSize:14,lineHeight:1.6,marginBottom:24}}>
          Vous allez supprimer <strong>{delModal?.first_name} {delModal?.last_name}</strong>.
          Cette action est irréversible.
        </p>
        <div style={{display:"flex",gap:10}}>
          <Btn variant="danger" onClick={handleDelete}>Supprimer définitivement</Btn>
          <Btn variant="secondary" onClick={()=>setDelModal(null)}>Annuler</Btn>
        </div>
      </Modal>
    </div>
  );
}

// ─── PAGE COURS ────────────────────────────────────────────────────────────────
function CoursesPage({ toast }) {
  const [courses, setCourses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [drawer, setDrawer] = useState(null);
  const [viewCourse, setViewCourse] = useState(null);
  const [form, setForm] = useState({ title:"", description:"", capacity:30 });
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [announceForm, setAnnounceForm] = useState({ text:"" });
  const [courseAnnounces, setCourseAnnounces] = useState([]);

  const load = useCallback(() => {
    setLoading(true);
    API.listCourses().then(d => { setCourses(d||[]); setLoading(false); })
      .catch(() => { toast("Erreur chargement cours","error"); setLoading(false); });
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  const filtered = courses.filter(c =>
    `${c.title} ${c.description||""}`.toLowerCase().includes(search.toLowerCase())
  );

  async function handleSave() {
    const e = {};
    if (!form.title.trim()) e.title = "Le titre est requis";
    if (!form.capacity || form.capacity < 1) e.capacity = "Capacité invalide";
    if (Object.keys(e).length) { setErrors(e); return; }
    setSaving(true);
    try {
      await API.createCourse({ ...form, capacity: Number(form.capacity) });
      toast("Cours créé avec succès");
      setDrawer(null); load();
    } catch(err) { toast(err.message,"error"); }
    finally { setSaving(false); }
  }

  async function openView(c) {
    setViewCourse(c); setDrawer("view");
    try {
      const a = await API.listAnnouncements(c.id);
      setCourseAnnounces(a||[]);
    } catch { setCourseAnnounces([]); }
  }

  async function handleAnnounce() {
    if (!announceForm.text.trim()) return;
    try {
      await API.createAnnouncement({ courseId: viewCourse.id, text: announceForm.text });
      toast("Annonce publiée");
      setAnnounceForm({ text:"" });
      const a = await API.listAnnouncements(viewCourse.id);
      setCourseAnnounces(a||[]);
    } catch(err) { toast(err.message,"error"); }
  }

  const cols = [
    { key:"id", label:"ID", render: r => <span style={{color:G[600],fontWeight:700}}>#{r.id}</span> },
    { key:"title", label:"Titre", render: r => (
      <div>
        <div style={{fontWeight:600,color:G.gray800}}>{r.title}</div>
        {r.description && <div style={{fontSize:12,color:G.gray400,marginTop:2,
          maxWidth:280,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>
          {r.description}
        </div>}
      </div>
    )},
    { key:"capacity", label:"Capacité", render: r => (
      <div style={{display:"flex",flexDirection:"column",gap:4}}>
        <div style={{display:"flex",justifyContent:"space-between",fontSize:12,color:G.gray500}}>
          <span>{r.enrolledCount}/{r.capacity}</span>
          <span>{Math.round((r.enrolledCount/r.capacity)*100)}%</span>
        </div>
        <div style={{height:6,background:G.gray200,borderRadius:99,overflow:"hidden"}}>
          <div style={{height:"100%",borderRadius:99,
            background: (r.enrolledCount/r.capacity)>=.9 ? G.danger : (r.enrolledCount/r.capacity)>=.7 ? G.warning : G.success,
            width:`${Math.min(100,(r.enrolledCount/r.capacity)*100)}%`}} />
        </div>
      </div>
    )},
    { key:"availableSeats", label:"Places libres", render: r => (
      <Badge color={r.availableSeats===0?"red":r.availableSeats<5?"yellow":"green"}>
        {r.availableSeats} libre{r.availableSeats!==1?"s":""}
      </Badge>
    )},
    { key:"actions", label:"", render: r => (
      <div onClick={e=>e.stopPropagation()}>
        <Btn variant="ghost" size="sm" icon={<Icon.Eye/>} onClick={()=>openView(r)}>Voir</Btn>
      </div>
    )},
  ];

  return (
    <div>
      <PageHeader
        title="Cours"
        sub={`${courses.length} cours au catalogue`}
        action={<Btn variant="primary" icon={<Icon.Plus/>} onClick={()=>{
          setForm({title:"",description:"",capacity:30}); setErrors({}); setDrawer("create");
        }}>Nouveau cours</Btn>}
      />

      <div style={{ background:G.white, borderRadius:14, border:`1px solid ${G.gray200}`, overflow:"hidden" }}>
        <div style={{ padding:"16px 20px", borderBottom:`1px solid ${G.gray100}`, display:"flex", gap:12 }}>
          <SearchBar value={search} onChange={setSearch} placeholder="Rechercher un cours…" />
          <span style={{fontSize:13,color:G.gray400,marginLeft:"auto",alignSelf:"center"}}>
            {filtered.length} cours
          </span>
        </div>
        {loading ? <Spinner /> : filtered.length===0
          ? <EmptyState icon="📚" title="Aucun cours trouvé" sub="Créez votre premier cours"
              action={<Btn variant="primary" icon={<Icon.Plus/>} onClick={()=>{
                setForm({title:"",description:"",capacity:30}); setErrors({}); setDrawer("create");
              }}>Créer un cours</Btn>}
            />
          : <Table cols={cols} rows={filtered} onRowClick={c=>openView(c)} />
        }
      </div>

      {/* Drawer création */}
      <Drawer open={drawer==="create"} onClose={()=>setDrawer(null)} title="Nouveau cours">
        <Field label="Titre du cours *" error={errors.title}>
          <Input value={form.title} onChange={e=>setForm(p=>({...p,title:e.target.value}))} placeholder="ex: Algorithmique avancée" />
        </Field>
        <Field label="Description">
          <Textarea value={form.description} onChange={e=>setForm(p=>({...p,description:e.target.value}))} placeholder="Décrivez le contenu du cours…" />
        </Field>
        <Field label="Capacité maximale *" error={errors.capacity}>
          <Input type="number" min="1" value={form.capacity} onChange={e=>setForm(p=>({...p,capacity:e.target.value}))} />
        </Field>
        <div style={{display:"flex",gap:12}}>
          <Btn variant="primary" onClick={handleSave} disabled={saving}>
            {saving?"Création…":"Créer le cours"}
          </Btn>
          <Btn variant="secondary" onClick={()=>setDrawer(null)}>Annuler</Btn>
        </div>
      </Drawer>

      {/* Drawer détail cours */}
      <Drawer open={drawer==="view"} onClose={()=>setDrawer(null)}
        title={viewCourse?.title||""} width={580}>
        {viewCourse && (
          <>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,marginBottom:24}}>
              {[
                {label:"Capacité totale", value:viewCourse.capacity},
                {label:"Inscrits", value:viewCourse.enrolledCount},
                {label:"Places libres", value:viewCourse.availableSeats},
                {label:"Taux remplissage", value:`${Math.round((viewCourse.enrolledCount/viewCourse.capacity)*100)}%`},
              ].map(s=>(
                <div key={s.label} style={{background:G[100],borderRadius:10,padding:"14px 18px"}}>
                  <div style={{fontSize:12,color:G.gray400,marginBottom:4}}>{s.label}</div>
                  <div style={{fontSize:22,fontWeight:800,color:G[700],fontFamily:"Playfair Display,Georgia,serif"}}>{s.value}</div>
                </div>
              ))}
            </div>

            {viewCourse.description && (
              <div style={{background:G[100],borderRadius:10,padding:16,marginBottom:24}}>
                <div style={{fontSize:12,color:G.gray400,marginBottom:6}}>Description</div>
                <p style={{margin:0,fontSize:14,color:G.gray800,lineHeight:1.6}}>{viewCourse.description}</p>
              </div>
            )}

            <div>
              <h4 style={{margin:"0 0 14px",fontSize:14,fontWeight:700,color:G[700],textTransform:"uppercase",letterSpacing:.5}}>
                Annonces ({courseAnnounces.length})
              </h4>
              <div style={{marginBottom:16}}>
                <Textarea value={announceForm.text} onChange={e=>setAnnounceForm({text:e.target.value})}
                  placeholder="Rédigez une annonce pour ce cours…" style={{marginBottom:8}} />
                <Btn variant="primary" size="sm" icon={<Icon.Announce/>} onClick={handleAnnounce}
                  disabled={!announceForm.text.trim()}>
                  Publier
                </Btn>
              </div>
              {courseAnnounces.length===0
                ? <p style={{color:G.gray400,fontSize:13}}>Aucune annonce pour ce cours.</p>
                : courseAnnounces.map(a=>(
                    <div key={a.id} style={{padding:"12px 16px",background:G[100],
                      borderRadius:9,marginBottom:8,borderLeft:`3px solid ${G[600]}`}}>
                      <p style={{margin:"0 0 4px",fontSize:14,color:G.gray800,lineHeight:1.5}}>{a.text}</p>
                      <span style={{fontSize:11,color:G.gray400}}>
                        {a.created_at ? new Date(a.created_at).toLocaleDateString("fr-FR") : ""}
                      </span>
                    </div>
                  ))
              }
            </div>
          </>
        )}
      </Drawer>
    </div>
  );
}

// ─── PAGE INSCRIPTIONS ─────────────────────────────────────────────────────────
function EnrollmentsPage({ toast }) {
  const [enrollments, setEnrollments] = useState([]);
  const [students, setStudents] = useState([]);
  const [courses, setCourses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [drawer, setDrawer] = useState(false);
  const [form, setForm] = useState({ student_id:"", course_id:"" });
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [cancelModal, setCancelModal] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [e, s, c] = await Promise.all([
        API.listEnrollments(),
        API.listStudents(),
        API.listCourses(),
      ]);
      setEnrollments(e||[]); setStudents(s||[]); setCourses(c||[]);
    } catch { toast("Erreur chargement","error"); }
    finally { setLoading(false); }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  const studentMap = Object.fromEntries(students.map(s=>[s.id,s]));
  const courseMap  = Object.fromEntries(courses.map(c=>[c.id,c]));

  const filtered = enrollments.filter(e => {
    const s = studentMap[e.student_id];
    const c = courseMap[e.course_id];
    const q = search.toLowerCase();
    const matchSearch = !q || `${s?.first_name||""} ${s?.last_name||""} ${c?.title||""}`.toLowerCase().includes(q);
    const matchFilter = filter==="all" || e.status===filter;
    return matchSearch && matchFilter;
  });

  async function handleSave() {
    const e = {};
    if (!form.student_id) e.student_id="Sélectionnez un étudiant";
    if (!form.course_id)  e.course_id="Sélectionnez un cours";
    if (Object.keys(e).length) { setErrors(e); return; }
    setSaving(true);
    try {
      await API.createEnrollment({ student_id:Number(form.student_id), course_id:Number(form.course_id) });
      toast("Inscription créée"); setDrawer(false); load();
    } catch(err) { toast(err.message,"error"); }
    finally { setSaving(false); }
  }

  async function handleCancel() {
    try {
      await API.cancelEnrollment(cancelModal.id);
      toast("Inscription annulée"); setCancelModal(null); load();
    } catch(err) { toast(err.message,"error"); }
  }

  const cols = [
    { key:"id", label:"ID", render: r => <span style={{color:G[600],fontWeight:700}}>#{r.id}</span> },
    { key:"student", label:"Étudiant", render: r => {
      const s = studentMap[r.student_id];
      return s ? (
        <div style={{display:"flex",alignItems:"center",gap:8}}>
          <div style={{width:30,height:30,borderRadius:"50%",background:G[700],
            display:"flex",alignItems:"center",justifyContent:"center",color:G.white,fontSize:11,fontWeight:700}}>
            {s.first_name[0]}{s.last_name[0]}
          </div>
          <div>
            <div style={{fontWeight:600,fontSize:13}}>{s.first_name} {s.last_name}</div>
            <div style={{fontSize:11,color:G.gray400}}>{s.email}</div>
          </div>
        </div>
      ) : <span style={{color:G.gray400}}>#{r.student_id}</span>;
    }},
    { key:"course", label:"Cours", render: r => {
      const c = courseMap[r.course_id];
      return c
        ? <div><div style={{fontWeight:600,fontSize:13}}>{c.title}</div><div style={{fontSize:11,color:G.gray400}}>{c.capacity} places</div></div>
        : <span style={{color:G.gray400}}>#{r.course_id}</span>;
    }},
    { key:"status", label:"Statut", render: r => (
      <Badge color={r.status==="enrolled"?"green":"gray"}>{r.status==="enrolled"?"Inscrit":"Annulé"}</Badge>
    )},
    { key:"created_at", label:"Date", render: r => r.created_at
      ? new Date(r.created_at).toLocaleDateString("fr-FR") : "—" },
    { key:"actions", label:"", render: r => r.status==="enrolled" && (
      <div onClick={e=>e.stopPropagation()}>
        <Btn variant="danger" size="sm" icon={<Icon.Trash/>} onClick={()=>setCancelModal(r)}>
          Annuler
        </Btn>
      </div>
    )},
  ];

  const counts = {
    all: enrollments.length,
    enrolled: enrollments.filter(e=>e.status==="enrolled").length,
    cancelled: enrollments.filter(e=>e.status==="cancelled").length,
  };

  return (
    <div>
      <PageHeader
        title="Inscriptions"
        sub="Gestion des inscriptions aux cours"
        action={<Btn variant="primary" icon={<Icon.Plus/>} onClick={()=>{
          setForm({student_id:"",course_id:""}); setErrors({}); setDrawer(true);
        }}>Nouvelle inscription</Btn>}
      />

      <div style={{display:"flex",gap:8,marginBottom:16}}>
        {[["all","Toutes",counts.all],["enrolled","Actives",counts.enrolled],["cancelled","Annulées",counts.cancelled]].map(([v,l,c])=>(
          <button key={v} onClick={()=>setFilter(v)} style={{
            padding:"8px 18px", borderRadius:99, border:"none", cursor:"pointer",fontSize:13,fontWeight:600,
            background: filter===v ? G[700] : G.gray100,
            color: filter===v ? G.white : G.gray600,
            transition:"all .15s",
          }}>
            {l} <span style={{fontSize:11,opacity:.75}}>({c})</span>
          </button>
        ))}
      </div>

      <div style={{ background:G.white, borderRadius:14, border:`1px solid ${G.gray200}`, overflow:"hidden" }}>
        <div style={{ padding:"16px 20px", borderBottom:`1px solid ${G.gray100}`, display:"flex", gap:12 }}>
          <SearchBar value={search} onChange={setSearch} placeholder="Étudiant ou cours…" />
          <span style={{fontSize:13,color:G.gray400,marginLeft:"auto",alignSelf:"center"}}>{filtered.length} résultats</span>
        </div>
        {loading ? <Spinner /> : filtered.length===0
          ? <EmptyState icon="📋" title="Aucune inscription" sub="Inscrivez un étudiant à un cours"
              action={<Btn variant="primary" icon={<Icon.Plus/>} onClick={()=>setDrawer(true)}>Inscrire</Btn>}
            />
          : <Table cols={cols} rows={filtered} />
        }
      </div>

      <Drawer open={drawer} onClose={()=>setDrawer(false)} title="Nouvelle inscription">
        <Field label="Étudiant *" error={errors.student_id}>
          <Select value={form.student_id} onChange={e=>setForm(p=>({...p,student_id:e.target.value}))}>
            <option value="">— Sélectionner un étudiant —</option>
            {students.map(s=>(
              <option key={s.id} value={s.id}>{s.first_name} {s.last_name} ({s.email})</option>
            ))}
          </Select>
        </Field>
        <Field label="Cours *" error={errors.course_id}>
          <Select value={form.course_id} onChange={e=>setForm(p=>({...p,course_id:e.target.value}))}>
            <option value="">— Sélectionner un cours —</option>
            {courses.filter(c=>c.availableSeats>0).map(c=>(
              <option key={c.id} value={c.id}>{c.title} ({c.availableSeats} places libres)</option>
            ))}
          </Select>
        </Field>
        {courses.filter(c=>c.availableSeats===0).length > 0 && (
          <p style={{fontSize:12,color:G.warning,marginBottom:16}}>
            <Icon.Alert/> {courses.filter(c=>c.availableSeats===0).length} cours complet(s) non affiché(s)
          </p>
        )}
        <div style={{display:"flex",gap:12}}>
          <Btn variant="primary" onClick={handleSave} disabled={saving}>{saving?"Inscription…":"Inscrire"}</Btn>
          <Btn variant="secondary" onClick={()=>setDrawer(false)}>Annuler</Btn>
        </div>
      </Drawer>

      <Modal open={!!cancelModal} onClose={()=>setCancelModal(null)} title="Annuler l'inscription">
        <p style={{color:G.gray600,fontSize:14,lineHeight:1.6,marginBottom:24}}>
          Annuler l'inscription de <strong>{studentMap[cancelModal?.student_id]?.first_name} {studentMap[cancelModal?.student_id]?.last_name}</strong> au cours <strong>{courseMap[cancelModal?.course_id]?.title}</strong> ?
          La place sera libérée automatiquement.
        </p>
        <div style={{display:"flex",gap:10}}>
          <Btn variant="danger" onClick={handleCancel}>Confirmer l'annulation</Btn>
          <Btn variant="secondary" onClick={()=>setCancelModal(null)}>Garder</Btn>
        </div>
      </Modal>
    </div>
  );
}

// ─── PAGE NOTES ────────────────────────────────────────────────────────────────
function GradesPage({ toast }) {
  const [students, setStudents] = useState([]);
  const [courses, setCourses] = useState([]);
  const [selectedStudent, setSelectedStudent] = useState("");
  const [grades, setGrades] = useState([]);
  const [loading, setLoading] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [form, setForm] = useState({ studentId:"", courseId:"", value:"" });
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    Promise.all([API.listStudents(), API.listCourses()])
      .then(([s,c]) => { setStudents(s||[]); setCourses(c||[]); });
  }, []);

  async function loadGrades(sid) {
    setSelectedStudent(sid); setLoading(true);
    try {
      const g = await API.listGrades(sid);
      setGrades(g||[]);
    } catch { toast("Erreur chargement notes","error"); setGrades([]); }
    finally { setLoading(false); }
  }

  async function handleSave() {
    const e = {};
    if (!form.studentId) e.studentId="Étudiant requis";
    if (!form.courseId)  e.courseId="Cours requis";
    const v = parseFloat(form.value);
    if (isNaN(v)||v<0||v>20) e.value="Note entre 0 et 20";
    if (Object.keys(e).length) { setErrors(e); return; }
    setSaving(true);
    try {
      await API.submitGrade({ studentId:Number(form.studentId), courseId:Number(form.courseId), value:v });
      toast("Note enregistrée");
      setDrawer(false);
      if (selectedStudent && Number(selectedStudent)===Number(form.studentId)) loadGrades(selectedStudent);
    } catch(err) { toast(err.message,"error"); }
    finally { setSaving(false); }
  }

  const courseMap = Object.fromEntries(courses.map(c=>[c.id,c]));

  function gradeColor(v) {
    if (v>=16) return "#047857";
    if (v>=14) return G.success;
    if (v>=12) return "#0369A1";
    if (v>=10) return G.warning;
    return G.danger;
  }

  return (
    <div>
      <PageHeader
        title="Notes"
        sub="Consultation et saisie des résultats académiques"
        action={<Btn variant="primary" icon={<Icon.Plus/>} onClick={()=>{
          setForm({studentId:"",courseId:"",value:""}); setErrors({}); setDrawer(true);
        }}>Saisir une note</Btn>}
      />

      <div style={{background:G.white,borderRadius:14,border:`1px solid ${G.gray200}`,padding:20,marginBottom:20}}>
        <label style={{fontSize:13,fontWeight:600,color:G[800],display:"block",marginBottom:8}}>
          Consulter les notes d'un étudiant
        </label>
        <div style={{display:"flex",gap:12}}>
          <Select value={selectedStudent} onChange={e=>loadGrades(e.target.value)}
            style={{...inputStyle,maxWidth:380}}>
            <option value="">— Choisir un étudiant —</option>
            {students.map(s=>(
              <option key={s.id} value={s.id}>{s.first_name} {s.last_name}</option>
            ))}
          </Select>
        </div>
      </div>

      {selectedStudent && (
        <div style={{background:G.white,borderRadius:14,border:`1px solid ${G.gray200}`,overflow:"hidden"}}>
          {loading ? <Spinner /> : grades.length===0
            ? <EmptyState icon="📊" title="Aucune note" sub="Cet étudiant n'a pas encore de notes enregistrées"
                action={<Btn variant="primary" size="sm" icon={<Icon.Plus/>} onClick={()=>{
                  setForm({studentId:selectedStudent,courseId:"",value:""}); setErrors({}); setDrawer(true);
                }}>Saisir une note</Btn>}
              />
            : (
              <>
                <div style={{padding:"16px 20px",borderBottom:`1px solid ${G.gray100}`,
                  display:"flex",alignItems:"center",justifyContent:"space-between"}}>
                  <span style={{fontSize:13,fontWeight:600,color:G[700]}}>
                    {grades.length} note{grades.length>1?"s":""} — Moyenne&nbsp;:&nbsp;
                    <strong style={{color:gradeColor(grades.reduce((a,g)=>a+Number(g.value),0)/grades.length)}}>
                      {(grades.reduce((a,g)=>a+Number(g.value),0)/grades.length).toFixed(2)}/20
                    </strong>
                  </span>
                </div>
                <div style={{padding:20,display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(220px,1fr))",gap:14}}>
                  {grades.map(g => {
                    const c = courseMap[g.course_id];
                    const v = Number(g.value);
                    return (
                      <div key={g.id} style={{background:G[100],borderRadius:12,padding:18,
                        borderTop:`4px solid ${gradeColor(v)}`}}>
                        <div style={{fontSize:13,fontWeight:600,color:G.gray800,marginBottom:4}}>
                          {c?.title||`Cours #${g.course_id}`}
                        </div>
                        <div style={{fontSize:36,fontWeight:800,color:gradeColor(v),lineHeight:1,
                          fontFamily:"Playfair Display,Georgia,serif"}}>
                          {v.toFixed(2)}
                          <span style={{fontSize:16,fontWeight:400,color:G.gray400}}>/20</span>
                        </div>
                        <div style={{marginTop:10,height:6,background:G.gray200,borderRadius:99}}>
                          <div style={{height:"100%",borderRadius:99,background:gradeColor(v),width:`${(v/20)*100}%`}} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )
          }
        </div>
      )}

      <Drawer open={drawer} onClose={()=>setDrawer(false)} title="Saisir une note">
        <Field label="Étudiant *" error={errors.studentId}>
          <Select value={form.studentId} onChange={e=>setForm(p=>({...p,studentId:e.target.value}))}>
            <option value="">— Sélectionner —</option>
            {students.map(s=><option key={s.id} value={s.id}>{s.first_name} {s.last_name}</option>)}
          </Select>
        </Field>
        <Field label="Cours *" error={errors.courseId}>
          <Select value={form.courseId} onChange={e=>setForm(p=>({...p,courseId:e.target.value}))}>
            <option value="">— Sélectionner —</option>
            {courses.map(c=><option key={c.id} value={c.id}>{c.title}</option>)}
          </Select>
        </Field>
        <Field label="Note (0 – 20) *" error={errors.value}>
          <Input type="number" min="0" max="20" step="0.5" value={form.value}
            onChange={e=>setForm(p=>({...p,value:e.target.value}))} placeholder="ex: 14.5" />
        </Field>
        {form.value && !isNaN(parseFloat(form.value)) && (
          <div style={{padding:"12px 16px",background:G[100],borderRadius:9,marginBottom:16,
            display:"flex",alignItems:"center",gap:8}}>
            <span style={{fontSize:22,fontWeight:800,color:gradeColor(parseFloat(form.value)),
              fontFamily:"Playfair Display,Georgia,serif"}}>{parseFloat(form.value).toFixed(2)}/20</span>
            <Badge color={parseFloat(form.value)>=10?"green":"red"}>
              {parseFloat(form.value)>=16?"Très bien":parseFloat(form.value)>=14?"Bien":
               parseFloat(form.value)>=12?"Assez bien":parseFloat(form.value)>=10?"Passable":"Insuffisant"}
            </Badge>
          </div>
        )}
        <div style={{display:"flex",gap:12}}>
          <Btn variant="primary" onClick={handleSave} disabled={saving}>{saving?"Enregistrement…":"Enregistrer"}</Btn>
          <Btn variant="secondary" onClick={()=>setDrawer(false)}>Annuler</Btn>
        </div>
      </Drawer>
    </div>
  );
}

// ─── SIDEBAR ───────────────────────────────────────────────────────────────────
const NAV = [
  { id:"dashboard",    label:"Tableau de bord",  Icon: Icon.Dashboard },
  { id:"students",     label:"Étudiants",         Icon: Icon.Students  },
  { id:"courses",      label:"Cours",             Icon: Icon.Courses   },
  { id:"enrollments",  label:"Inscriptions",      Icon: Icon.Enroll    },
  { id:"grades",       label:"Notes",             Icon: Icon.Grades    },
];

function Sidebar({ active, onNavigate, collapsed, onToggle }) {
  return (
    <aside style={{
      width: collapsed ? 64 : 240, background:G[800], color:G.white,
      display:"flex", flexDirection:"column", height:"100vh", position:"sticky", top:0,
      transition:"width .25s cubic-bezier(.4,0,.2,1)", flexShrink:0, zIndex:100,
    }}>
      {/* Logo */}
      <div style={{ padding: collapsed?"16px 12px":"20px 20px", borderBottom:`1px solid rgba(255,255,255,.12)`,
        display:"flex", alignItems:"center", gap:12, minHeight:72 }}>
        <div style={{ width:36, height:36, background:G[600], borderRadius:10, display:"flex",
          alignItems:"center", justifyContent:"center", flexShrink:0 }}>
          <Icon.Cap />
        </div>
        {!collapsed && (
          <div>
            <div style={{fontSize:15,fontWeight:800,fontFamily:"Playfair Display,Georgia,serif",lineHeight:1.2}}>Université</div>
            <div style={{fontSize:11,opacity:.6,marginTop:1}}>Système de gestion</div>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav style={{ flex:1, padding:"12px 8px", overflowY:"auto" }}>
        {NAV.map(item => {
          const isActive = active === item.id;
          return (
            <button key={item.id} onClick={()=>onNavigate(item.id)}
              title={collapsed ? item.label : undefined}
              style={{
                width:"100%", display:"flex", alignItems:"center", gap:12,
                padding: collapsed ? "12px 0" : "11px 14px",
                justifyContent: collapsed ? "center" : "flex-start",
                borderRadius:10, border:"none", cursor:"pointer", marginBottom:2,
                background: isActive ? `rgba(255,255,255,.15)` : "transparent",
                color: isActive ? G.white : "rgba(255,255,255,.65)",
                fontWeight: isActive ? 700 : 500, fontSize:14, transition:"all .15s",
                boxShadow: isActive ? `inset 3px 0 0 ${G[400]}` : "none",
              }}
              onMouseEnter={e=>{ if(!isActive) e.currentTarget.style.background="rgba(255,255,255,.08)"; }}
              onMouseLeave={e=>{ if(!isActive) e.currentTarget.style.background="transparent"; }}>
              <span style={{flexShrink:0, display:"flex"}}><item.Icon /></span>
              {!collapsed && <span>{item.label}</span>}
            </button>
          );
        })}
      </nav>

      {/* Toggle */}
      <button onClick={onToggle}
        style={{ margin:"0 8px 16px", padding:"10px", background:"rgba(255,255,255,.08)",
          border:"none", borderRadius:10, cursor:"pointer", color:"rgba(255,255,255,.65)",
          display:"flex", alignItems:"center", justifyContent: collapsed?"center":"flex-start",
          gap:8, fontSize:12, fontWeight:500, transition:"all .15s" }}
        onMouseEnter={e=>e.currentTarget.style.background="rgba(255,255,255,.15)"}
        onMouseLeave={e=>e.currentTarget.style.background="rgba(255,255,255,.08)"}>
        <span style={{ display:"flex", transform: collapsed?"rotate(180deg)":"rotate(0deg)", transition:"transform .25s" }}>
          <Icon.Collapse />
        </span>
        {!collapsed && <span>Réduire</span>}
      </button>
    </aside>
  );
}

// ─── APP ───────────────────────────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState("dashboard");
  const [collapsed, setCollapsed] = useState(false);
  const { toasts, toast, remove } = useToast();

  const pages = {
    dashboard:   <Dashboard onNavigate={setPage} />,
    students:    <StudentsPage toast={toast} />,
    courses:     <CoursesPage toast={toast} />,
    enrollments: <EnrollmentsPage toast={toast} />,
    grades:      <GradesPage toast={toast} />,
  };

  const pageLabel = NAV.find(n=>n.id===page)?.label || "";

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Playfair+Display:wght@700;800&display=swap');
        * { box-sizing: border-box; }
        body { margin:0; font-family:'Inter',system-ui,sans-serif; background:${G.gray50}; }
        ::-webkit-scrollbar { width:6px; height:6px; }
        ::-webkit-scrollbar-track { background:transparent; }
        ::-webkit-scrollbar-thumb { background:${G[200]}; border-radius:99px; }
        ::-webkit-scrollbar-thumb:hover { background:${G[400]}; }
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes slideIn { from { transform: translateX(20px); opacity:0; } to { transform: translateX(0); opacity:1; } }
        select, input, textarea, button { font-family: inherit; }
      `}</style>

      <div style={{ display:"flex", minHeight:"100vh" }}>
        <Sidebar active={page} onNavigate={setPage} collapsed={collapsed} onToggle={()=>setCollapsed(p=>!p)} />

        <main style={{ flex:1, overflow:"auto", display:"flex", flexDirection:"column" }}>
          {/* Topbar */}
          <div style={{ background:G.white, borderBottom:`1px solid ${G.gray200}`,
            padding:"0 32px", height:64, display:"flex", alignItems:"center",
            justifyContent:"space-between", position:"sticky", top:0, zIndex:50 }}>
            <div>
              <span style={{fontSize:13,color:G.gray400}}>Université /&nbsp;</span>
              <span style={{fontSize:13,fontWeight:700,color:G[700]}}>{pageLabel}</span>
            </div>
            <div style={{display:"flex",alignItems:"center",gap:10}}>
              <div style={{width:8,height:8,borderRadius:"50%",background:G.success}} />
              <span style={{fontSize:12,color:G.gray400}}>Système en ligne</span>
            </div>
          </div>

          {/* Contenu */}
          <div style={{ padding:"32px", maxWidth:1200, width:"100%" }}>
            {pages[page]}
          </div>
        </main>
      </div>

      <Toast toasts={toasts} remove={remove} />
    </>
  );
}