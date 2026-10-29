import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  ArrowRight, ArrowUpRight, BriefcaseBusiness, Check,
  CircleHelp, CloudUpload, Compass, FileDown, FileText, Fingerprint, Gauge,
  LayoutDashboard, LoaderCircle, LockKeyhole, LogOut, MapPin, Menu, Search,
  Send, Sparkles, Target, UserRound, X,
} from "lucide-react";
import { api, downloadResume, getToken, setToken, streamTailor } from "./api";
import { emptyProfile, type Dashboard, type Job, type ProfileData, type ProfileResponse, type Resume, type User } from "./types";

type Page = "overview" | "profile" | "tailor" | "jobs" | "resumes";

const navigation: { id: Page; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "profile", label: "My profile", icon: UserRound },
  { id: "tailor", label: "Resume studio", icon: Sparkles },
  { id: "jobs", label: "Find opportunities", icon: Compass },
  { id: "resumes", label: "My resumes", icon: FileText },
];

function prettyDate(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric" }).format(date);
}

function initials(name: string) {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("") || "J";
}

function scoreTone(value: number | null) {
  if (value === null) return "muted";
  return value >= 75 ? "strong" : value >= 55 ? "good" : "low";
}

function Avatar({ name, small = false }: { name: string; small?: boolean }) {
  return <span className={`avatar${small ? " avatar-small" : ""}`}>{initials(name)}</span>;
}

function ScoreRing({ score }: { score: number | null }) {
  const value = Math.round(score ?? 0);
  return (
    <div className={`score-ring ${scoreTone(score)}`} style={{ "--score": `${value * 3.6}deg` } as React.CSSProperties}>
      <span>{score === null ? "—" : `${value}%`}</span>
    </div>
  );
}

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [page, setPage] = useState<Page>("overview");
  const [tailorDraft, setTailorDraft] = useState<{ title: string; text: string } | null>(null);
  const [loading, setLoading] = useState(Boolean(getToken()));
  const [error, setError] = useState("");
  const [mobileNav, setMobileNav] = useState(false);

  const refresh = useCallback(async () => {
    const data = await api.dashboard();
    setDashboard(data);
    setUser(data.user);
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    let active = true;
    api.me().then((profile) => {
      if (active) setUser(profile);
      return api.dashboard();
    }).then((data) => {
      if (active) setDashboard(data);
    }).catch((reason: unknown) => {
      setToken(null);
      if (active) {
        setUser(null);
        setError(reason instanceof Error ? reason.message : "Could not connect to Joba.");
      }
    }).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  async function onSignedIn(nextUser: User) {
    setError("");
    setLoading(true);
    try {
      const data = await api.dashboard();
      setUser(nextUser);
      setDashboard(data);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load your workspace.");
      setToken(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }

  async function signOut() {
    try {
      await api.logout();
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Your session could not be ended on the server.");
    } finally {
      setToken(null);
      setUser(null);
      setDashboard(null);
      setPage("overview");
    }
  }

  if (loading) return <div className="app-loading"><span className="brand-mark"><Sparkles size={20} /></span><LoaderCircle className="spin" size={20} /> Preparing your workspace…</div>;
  if (!user) return <AuthScreen onSignedIn={onSignedIn} initialError={error} />;

  return (
    <div className="app-shell">
      <aside className={`sidebar${mobileNav ? " sidebar-open" : ""}`}>
        <div className="brand-lockup">
          <span className="brand-mark"><Sparkles size={20} strokeWidth={2.2} /></span>
          <span className="brand-name">joba<span>.</span></span>
        </div>
        <div className="workspace-label">YOUR WORKSPACE</div>
        <nav className="side-nav" aria-label="Main navigation">
          {navigation.map(({ id, label, icon: Icon }) => (
            <button key={id} className={`nav-link${page === id ? " active" : ""}`} onClick={() => { setPage(id); setMobileNav(false); }}>
              <Icon size={18} strokeWidth={1.8} /><span>{label}</span>
              {id === "jobs" && dashboard && dashboard.stats.saved_jobs > 0 && <span className="nav-count">{dashboard.stats.saved_jobs}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-tip">
          <div className="tip-orbit"><Sparkles size={18} /></div>
          <strong>A little progress<br />goes a long way.</strong>
          <p>Your next chapter starts with one good application.</p>
          <button onClick={() => setPage("tailor")}>Tailor a resume <ArrowRight size={14} /></button>
        </div>
        <div className="sidebar-user">
          <Avatar name={dashboard?.profile.profile.contact.name || user.username} small />
          <div className="user-text"><strong>{dashboard?.profile.profile.contact.name || user.username}</strong><span>{user.email}</span></div>
          <button className="icon-button logout-button" title="Sign out" aria-label="Sign out" onClick={signOut}><LogOut size={17} /></button>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setMobileNav((open) => !open)} aria-label="Toggle navigation"><Menu size={20} /></button>
          <div className="breadcrumbs"><span>Workspace</span><span className="crumb-slash">/</span><strong>{navigation.find((item) => item.id === page)?.label}</strong></div>
          <div className="topbar-right"><span className="today-label">{new Intl.DateTimeFormat("en", { weekday: "long", month: "long", day: "numeric" }).format(new Date())}</span><button className="help-button" title="Your data stays private and is only used to power your workspace."><CircleHelp size={17} /></button><Avatar name={dashboard?.profile.profile.contact.name || user.username} small /></div>
        </header>
        <div className="content-wrap">
          {page === "overview" && <Overview data={dashboard} onNavigate={setPage} onRefresh={refresh} />}
          {page === "profile" && <ProfilePage initial={dashboard?.profile || null} onSaved={refresh} />}
          {page === "tailor" && <TailorPage initialDraft={tailorDraft} onComplete={refresh} />}
          {page === "jobs" && <JobsPage onTailor={(job) => { setTailorDraft({ title: `${job.title} at ${job.company}`, text: job.jd_text }); setPage("tailor"); }} />}
          {page === "resumes" && <ResumesPage />}
        </div>
        <footer className="footer"><span>Made for the work you want.</span><span>Joba keeps your career details yours <Fingerprint size={13} /></span></footer>
      </main>
      {mobileNav && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileNav(false)} />}
    </div>
  );
}

function AuthScreen({ onSignedIn, initialError }: { onSignedIn: (user: User) => Promise<void>; initialError: string }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(initialError);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const result = mode === "login"
        ? await api.login(username, password)
        : await api.signup(username, email, password);
      setToken(result.token);
      await onSignedIn(result.user);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "We couldn't sign you in.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-art">
        <div className="auth-art-brand"><span className="brand-mark"><Sparkles size={20} /></span><span className="brand-name">joba<span>.</span></span></div>
        <div className="auth-quote"><span className="eyebrow">YOUR NEXT CHAPTER</span><h1>Find work that<br />feels like <em>you.</em></h1><p>A calmer, more thoughtful way to find your next opportunity—and show up as your best self.</p><div className="art-decoration"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="orbit-center"><Sparkles size={26} /></div><span className="float-tag tag-one">your story, beautifully told</span><span className="float-tag tag-two">the right fit is out there</span></div></div>
        <span className="auth-art-foot">A career workspace, made personal.</span>
      </div>
      <div className="auth-form-side">
        <form className="auth-form" onSubmit={submit}>
          <span className="eyebrow">{mode === "login" ? "WELCOME BACK" : "A GOOD PLACE TO BEGIN"}</span>
          <h2>{mode === "login" ? "Good to see you." : "Let’s make it yours."}</h2>
          <p>{mode === "login" ? "Pick up right where your next chapter begins." : "Create your account and make room for what’s next."}</p>
          {error && <div className="alert alert-error"><X size={16} />{error}</div>}
          <label>Username or email<input required autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} placeholder="Your username or email" /></label>
          {mode === "signup" && <label>Email address<input required type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" /></label>}
          <label>Password<input required minLength={mode === "signup" ? 8 : 1} type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} placeholder={mode === "signup" ? "At least 8 characters" : "Your password"} /></label>
          <button className="button button-primary button-wide" disabled={busy}>{busy ? <LoaderCircle className="spin" size={17} /> : <LockKeyhole size={16} />}{mode === "login" ? "Sign in to Joba" : "Create your account"}<ArrowRight size={16} /></button>
          <div className="auth-switch">{mode === "login" ? "New to Joba?" : "Already have an account?"}<button type="button" onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(""); }}>{mode === "login" ? "Create an account" : "Sign in"}</button></div>
          <div className="privacy-note"><Fingerprint size={15} />Your career data stays private and securely yours.</div>
        </form>
      </div>
    </div>
  );
}

function PageHeading({ eyebrow, title, subtitle, action }: { eyebrow: string; title: ReactNode; subtitle: string; action?: ReactNode }) {
  return <div className="page-heading"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{subtitle}</p></div>{action && <div className="heading-action">{action}</div>}</div>;
}

function Overview({ data, onNavigate, onRefresh }: { data: Dashboard | null; onNavigate: (page: Page) => void; onRefresh: () => Promise<void> }) {
  const name = data?.profile.profile.contact.name?.split(/\s+/)[0] || data?.user.username || "there";
  const [refreshing, setRefreshing] = useState(false);
  async function refresh() {
    setRefreshing(true);
    try { await onRefresh(); } finally { setRefreshing(false); }
  }
  const profileReady = data?.stats.profile_ready ?? false;
  return (
    <div className="page-stack">
      <PageHeading eyebrow="MONDAY MOTIVATION, ANY DAY" title={<>A fresh start, <span>{name}.</span></>} subtitle="Your next opportunity isn't a long way off. Let's make it happen." action={<button className="button button-outline" onClick={refresh}><LoaderCircle size={16} className={refreshing ? "spin" : ""} />Refresh</button>} />
      {!profileReady && <div className="welcome-banner"><div className="welcome-icon"><Sparkles size={21} /></div><div><strong>First, let’s get to know your story.</strong><span>Add your master resume to unlock tailored matches and thoughtful resume edits.</span></div><button className="button button-dark" onClick={() => onNavigate("profile")}>Set up your profile <ArrowRight size={15} /></button></div>}
      <section className="stats-grid">
        <StatCard label="Resumes tailored" value={data?.stats.resume_count ?? 0} foot="Built around the role" icon={<FileText size={18} />} tint="lilac" />
        <StatCard label="Jobs saved" value={data?.stats.saved_jobs ?? 0} foot="Worth a closer look" icon={<BriefcaseBusiness size={18} />} tint="peach" />
        <StatCard label="Applications sent" value={data?.stats.applied_jobs ?? 0} foot="Small steps add up" icon={<Send size={18} />} tint="mint" />
        <div className="stat-card profile-stat"><div className="stat-head"><span>Profile strength</span><span className="stat-icon stat-mint"><Target size={18} /></span></div><div className="profile-stat-value">{profileReady ? "Ready to go" : "Just getting started"}</div><div className="profile-progress"><span style={{ width: profileReady ? "100%" : "26%" }} /></div><button className="text-action" onClick={() => onNavigate("profile")}>Review your profile <ArrowRight size={13} /></button></div>
      </section>

      <section className="hero-workspace">
        <div className="hero-copy"><span className="hero-kicker"><span className="spark-dot" />YOUR NEXT MOVE</span><h2>Your next role deserves<br />your <em>best story.</em></h2><p>Let’s shape your experience around the work that excites you. Grounded in what you’ve actually done—never made up.</p><button className="button button-dark" onClick={() => onNavigate(profileReady ? "tailor" : "profile")}>{profileReady ? "Tailor a resume" : "Add your profile"}<ArrowRight size={16} /></button><span className="hero-reassurance"><Fingerprint size={14} />Only your real experience. Always.</span></div>
        <div className="hero-art" aria-hidden="true"><div className="hero-circle hero-circle-back" /><div className="hero-circle hero-circle-front" /><div className="hero-paper"><div className="paper-top"><span /><span /><span /></div><div className="paper-person" /><div className="paper-line paper-line-long" /><div className="paper-line paper-line-short" /><div className="paper-rule" /><div className="paper-label">EXPERIENCE</div><div className="paper-line paper-line-mid" /><div className="paper-line paper-line-long" /><div className="paper-line paper-line-short" /><div className="paper-skill-row"><i /><i /><i /></div><div className="paper-check"><Check size={16} /></div></div><div className="float-note"><Sparkles size={15} /><span>Made for this role</span></div><div className="hero-star star-a">✳</div><div className="hero-star star-b">✦</div></div>
      </section>

      <div className="section-heading"><div><span className="eyebrow">YOUR WORKSPACE</span><h2>Keep your momentum</h2></div><button className="text-action" onClick={() => onNavigate("resumes")}>See all resumes <ArrowRight size={14} /></button></div>
      <div className="overview-grid">
        <section className="card recent-card"><div className="card-heading"><div><h3>Recently tailored</h3><p>Your latest versions, ready when you are.</p></div><button className="icon-button subtle-button" aria-label="Go to resumes" onClick={() => onNavigate("resumes")}><ArrowUpRight size={17} /></button></div>
          {data?.recent_resumes.length ? <div className="resume-list">{data.recent_resumes.slice(0, 4).map((resume) => <ResumeRow key={resume.id} resume={resume} onDownload={downloadResume} />)}</div> : <EmptyInline icon={<FileText size={20} />} title="Your next resume starts here." action="Create your first tailored version" onClick={() => onNavigate(profileReady ? "tailor" : "profile")} />}
        </section>
        <section className="card opportunity-card"><div className="card-heading"><div><h3>Good-fit opportunities</h3><p>Picked with your profile in mind.</p></div><button className="icon-button subtle-button" aria-label="Find jobs" onClick={() => onNavigate("jobs")}><ArrowUpRight size={17} /></button></div>
          {data?.recent_jobs.length ? <div className="opportunity-list">{data.recent_jobs.slice(0, 4).map((job) => <JobMini key={job.id} job={job} />)}</div> : <EmptyInline icon={<Compass size={20} />} title="A better search starts with your profile." action="Explore matching roles" onClick={() => onNavigate(profileReady ? "jobs" : "profile")} />}
        </section>
      </div>
      <div className="bottom-note"><span className="note-flower">✳</span><span><strong>Good work takes a little heart.</strong> Take it one meaningful step at a time.</span><button onClick={() => onNavigate("jobs")}>Find your next step <ArrowRight size={14} /></button></div>
    </div>
  );
}

function StatCard({ label, value, foot, icon, tint }: { label: string; value: number; foot: string; icon: ReactNode; tint: string }) {
  return <div className="stat-card"><div className="stat-head"><span>{label}</span><span className={`stat-icon stat-${tint}`}>{icon}</span></div><div className="stat-value">{value.toLocaleString()}</div><div className="stat-foot"><span className="stat-foot-dot" />{foot}</div></div>;
}

function EmptyInline({ icon, title, action, onClick }: { icon: ReactNode; title: string; action: string; onClick: () => void }) {
  return <div className="empty-inline"><span className="empty-icon">{icon}</span><strong>{title}</strong><button className="text-action" onClick={onClick}>{action}<ArrowRight size={13} /></button></div>;
}

function ResumeRow({ resume, onDownload }: { resume: Resume; onDownload: (id: number, format: "md" | "pdf" | "docx") => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function download() {
    setBusy(true); setError("");
    try { await onDownload(resume.id, "pdf"); } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not download."); } finally { setBusy(false); }
  }
  return <div className="resume-row"><span className="document-icon"><FileText size={17} /></span><div className="resume-row-info"><strong>{resume.title}</strong><span>{prettyDate(resume.created_at)}{resume.company ? ` · ${resume.company}` : ""}{resume.page_count ? ` · ${resume.page_count} pg` : ""}</span>{error && <small className="inline-error">{error}</small>}</div><div className="resume-score"><ScoreRing score={resume.match_score} /><span>match</span></div><button className="icon-button download-button" onClick={download} disabled={busy} aria-label="Download PDF">{busy ? <LoaderCircle className="spin" size={16} /> : <FileDown size={16} />}</button></div>;
}

function JobMini({ job }: { job: Job }) {
  return <a className="job-mini" href={job.url} target="_blank" rel="noreferrer"><span className="company-mark">{job.company.slice(0, 1).toUpperCase()}</span><span className="job-mini-info"><strong>{job.title}</strong><small>{job.company} · {job.location || (job.remote ? "Remote" : "Location flexible")}</small></span><span className={`mini-match ${scoreTone(job.match_score)}`}>{job.match_score === null ? "—" : `${Math.round(job.match_score)}%`}</span></a>;
}

function ProfilePage({ initial, onSaved }: { initial: ProfileResponse | null; onSaved: () => Promise<void> }) {
  const [profile, setProfile] = useState<ProfileData>(initial?.profile || emptyProfile());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [file, setFile] = useState<File | null>(null);
  useEffect(() => { if (initial) setProfile(initial.profile); }, [initial]);
  function updateContact(field: keyof ProfileData["contact"], value: string) {
    setProfile((current) => ({ ...current, contact: { ...current.contact, [field]: value } }));
  }
  async function save() {
    setBusy(true); setError(""); setMessage("");
    try {
      await api.saveProfile(profile);
      await onSaved();
      setMessage("Your profile is saved and ready for the next step.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "We couldn't save your profile."); }
    finally { setBusy(false); }
  }
  async function upload() {
    if (!file) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await api.importProfile(file);
      await onSaved();
      setMessage("Your resume is in. Review the extracted details below.");
      setFile(null);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "We couldn't import this resume."); }
    finally { setBusy(false); }
  }
  const skillText = profile.skills.join(", ");
  return (
    <div className="page-stack">
      <PageHeading eyebrow="THE STORY BEHIND THE WORK" title="Your profile" subtitle="A clear picture of your experience helps Joba find the roles that fit you." action={<button className="button button-primary" onClick={save} disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />}Save changes</button>} />
      {(message || error) && <div className={`alert ${error ? "alert-error" : "alert-success"}`}>{error ? <X size={16} /> : <Check size={16} />}{error || message}</div>}
      <div className="profile-layout">
        <section className="card profile-form-card">
          <div className="profile-card-title"><span className="section-icon"><UserRound size={18} /></span><div><h2>About you</h2><p>The essentials, exactly as you want them shared.</p></div></div>
          <div className="form-grid">
            <label className="field-full">Full name<input value={profile.contact.name} onChange={(event) => updateContact("name", event.target.value)} placeholder="How should we introduce you?" /></label>
            <label>Email address<input type="email" value={profile.contact.email} onChange={(event) => updateContact("email", event.target.value)} placeholder="you@example.com" /></label>
            <label>Phone<input value={profile.contact.phone} onChange={(event) => updateContact("phone", event.target.value)} placeholder="+1 (555) 000-0000" /></label>
            <label>Location<input value={profile.contact.location} onChange={(event) => updateContact("location", event.target.value)} placeholder="City, Country" /></label>
            <label>LinkedIn<input value={profile.contact.linkedin} onChange={(event) => updateContact("linkedin", event.target.value)} placeholder="linkedin.com/in/you" /></label>
            <label>GitHub<input value={profile.contact.github} onChange={(event) => updateContact("github", event.target.value)} placeholder="github.com/you" /></label>
            <label>Portfolio<input value={profile.contact.portfolio} onChange={(event) => updateContact("portfolio", event.target.value)} placeholder="your-site.com" /></label>
            <label className="field-full">A little about your work<textarea rows={4} value={profile.summary} onChange={(event) => setProfile((current) => ({ ...current, summary: event.target.value }))} placeholder="What kind of work do you do best? What are you proud of?" /></label>
            <label className="field-full">Skills <span className="label-hint">Separate each skill with a comma.</span><textarea rows={3} value={skillText} onChange={(event) => setProfile((current) => ({ ...current, skills: event.target.value.split(",").map((skill) => skill.trim()).filter(Boolean) }))} placeholder="Product strategy, Python, User research…" /></label>
          </div>
          <div className="form-footer"><span><Fingerprint size={15} />Your profile is private to your account.</span><button className="button button-primary" onClick={save} disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />}Save profile</button></div>
        </section>
        <aside className="profile-aside">
          <div className="card import-card"><span className="eyebrow">A SHORTCUT</span><div className="import-icon"><CloudUpload size={21} /></div><h3>Bring your resume along.</h3><p>Upload your current resume, and we'll help you get the details into place.</p><label className="upload-zone"><input type="file" accept=".pdf,.docx,.txt" onChange={(event) => setFile(event.target.files?.[0] || null)} /><FileText size={16} /><span>{file?.name || "Choose a PDF, DOCX, or TXT"}</span></label><button className="button button-dark button-wide" onClick={upload} disabled={!file || busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <CloudUpload size={16} />}Import and review</button><small>Your resume is parsed to your private profile.</small></div>
          <div className="privacy-card"><span className="privacy-shield"><LockKeyhole size={18} /></span><div><strong>Always your story.</strong><p>Your experience stays the source of truth. Joba never invents career claims.</p></div></div>
          <ProfileSummary profile={profile} />
        </aside>
      </div>
    </div>
  );
}

function ProfileSummary({ profile }: { profile: ProfileData }) {
  const complete = [profile.contact.name, profile.summary, profile.skills.length, profile.experience.length].filter(Boolean).length;
  return <div className="card profile-completion"><div className="completion-head"><Gauge size={17} /><span>Profile snapshot</span><strong>{complete}/4</strong></div><div className="completion-track"><i style={{ width: `${complete * 25}%` }} /></div><div className="completion-list">{[["A name to know", !!profile.contact.name], ["A story to tell", !!profile.summary], ["Skills to share", profile.skills.length > 0], ["Experience to draw from", profile.experience.length > 0]].map(([label, done]) => <span key={String(label)} className={done ? "is-done" : ""}>{done ? <Check size={13} /> : <span className="empty-check" />}{label}</span>)}</div></div>;
}

function TailorPage({ initialDraft, onComplete }: { initialDraft: { title: string; text: string } | null; onComplete: () => Promise<void> }) {
  const [method, setMethod] = useState<"paste" | "link" | "file">("paste");
  const [jdText, setJdText] = useState("");
  const [jdUrl, setJdUrl] = useState("");
  const [jdTitle, setJdTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<Record<string, { status: string; detail: string }> | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (initialDraft) {
      setMethod("paste");
      setJdTitle(initialDraft.title);
      setJdText(initialDraft.text);
      setFile(null);
    }
  }, [initialDraft]);
  const stages = useMemo(() => [
    ["job_research", "Getting to know the role", "Pulling out the skills and priorities that matter."],
    ["candidate_profiling", "Finding your strongest evidence", "Matching the role to what you've actually done."],
    ["resume_strategy", "Bringing your story together", "Choosing the most relevant details for this role."],
  ] as const, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setResult(null); setProgress({});
    try {
      const output = await streamTailor({
        jd_text: method === "paste" ? jdText : "",
        jd_title: jdTitle,
        jd_url: method === "link" ? jdUrl : "",
        file: method === "file" ? file : null,
      }, setProgress);
      setResult(output);
      await onComplete();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "We couldn't tailor this resume."); }
    finally { setBusy(false); }
  }
  const stageProgress = progress || {};
  const resumeId = result?.version_id as number | undefined;
  return (
    <div className="page-stack">
      <PageHeading eyebrow="A RESUME THAT MEETS THE MOMENT" title="Resume studio" subtitle="Give us the job description. We’ll help your real experience show up for it." />
      <div className="studio-layout">
        <form className="card tailor-card" onSubmit={submit}>
          <div className="studio-intro"><span className="studio-spark"><Sparkles size={20} /></span><div><h2>Start with the opportunity.</h2><p>Joba finds the match between what they need and what you bring.</p></div></div>
          <label className="form-label">What should we call this role?<input value={jdTitle} onChange={(event) => setJdTitle(event.target.value)} placeholder="e.g. Product Designer at Acme" /></label>
          <div className="form-label">Job description <span className="required-note">Required</span></div>
          <div className="input-tabs">{([{ id: "paste", label: "Paste text" }, { id: "link", label: "Add a link" }, { id: "file", label: "Upload a file" }] as const).map((option) => <button type="button" key={option.id} className={method === option.id ? "selected" : ""} onClick={() => setMethod(option.id)}>{option.label}</button>)}</div>
          {method === "paste" && <textarea className="jd-textarea" rows={11} value={jdText} onChange={(event) => setJdText(event.target.value)} placeholder={"Paste the full job description here…\n\nThe more detail you share, the more thoughtfully we can match your experience."} />}
          {method === "link" && <div className="link-input-wrap"><span>https://</span><input type="url" value={jdUrl} onChange={(event) => setJdUrl(event.target.value)} placeholder="company.com/careers/role" /></div>}
          {method === "file" && <label className="jd-file-drop"><CloudUpload size={25} /><strong>{file?.name || "Drop the role in here."}</strong><span>Choose a PDF, DOCX, or TXT document.</span><input type="file" accept=".pdf,.docx,.txt" onChange={(event) => setFile(event.target.files?.[0] || null)} /></label>}
          {error && <div className="alert alert-error"><X size={16} />{error}</div>}
          {busy && <div className="agent-progress"><div className="progress-title"><LoaderCircle className="spin" size={16} /><strong>Your resume is taking shape</strong><span>Stay right here—we're on it.</span></div>{stages.map(([id, title, desc]) => { const status = stageProgress[id]?.status || "queued"; return <div className={`agent-step agent-${status}`} key={id}><span className="agent-indicator">{status === "completed" ? <Check size={13} /> : status === "running" ? <LoaderCircle className="spin" size={13} /> : <span />}</span><span><strong>{title}</strong><small>{stageProgress[id]?.detail || desc}</small></span><small className="agent-state">{status === "queued" ? "UP NEXT" : status.toUpperCase()}</small></div>; })}</div>}
          <div className="tailor-submit"><span><LockKeyhole size={14} />Your resume stays grounded in your saved profile.</span><button className="button button-primary" disabled={busy || (method === "paste" && !jdText.trim()) || (method === "link" && !jdUrl.trim()) || (method === "file" && !file)}>{busy ? <LoaderCircle className="spin" size={16} /> : <Sparkles size={16} />}{busy ? "Working on it…" : "Tailor my resume"}<ArrowRight size={15} /></button></div>
        </form>
        <aside className="studio-aside"><div className="studio-promise"><span className="promise-icon"><Fingerprint size={20} /></span><span className="eyebrow">A PROMISE FROM JOBA</span><h3>Your story stays<br /><em>your story.</em></h3><p>We select and organize your original experience. No made-up bullet points. No embellished claims. Just you, clearly told.</p><div className="promise-rule" /><span className="promise-foot"><Check size={14} />Verified against your master profile</span></div><div className="process-card"><span className="eyebrow">THOUGHTFUL BY DESIGN</span>{[["01", "Read the role", "We find the skills and needs."], ["02", "Find your proof", "We look through your real experience."], ["03", "Shape your resume", "Your own words, in the right order."]].map(([num, title, desc]) => <div className="process-step" key={num}><span>{num}</span><div><strong>{title}</strong><small>{desc}</small></div></div>)}</div></aside>
      </div>
      {result && <section className="card result-card"><div className="result-title"><span className="result-check"><Check size={20} /></span><div><span className="eyebrow">READY FOR YOUR NEXT STEP</span><h2>Your tailored resume is ready.</h2><div className="template-badge" style={{ marginTop: "4px", fontSize: "0.82rem", color: "var(--color-primary, #4338ca)", display: "flex", alignItems: "center", gap: "6px" }}><Check size={14} /><span>Master Template Preserved • Strict 1-Page Layout ({String(result.page_count ?? 1)} Page)</span></div></div></div><div className="result-metrics"><div><span>Match score</span><strong>{Math.round(Number(result.match_score || 0))}%</strong></div><div><span>ATS score</span><strong>{Math.round(Number(result.ats_score || 0))}%</strong></div><div><span>Evidence used</span><strong>{Number(result.evidence_count || 0)}</strong></div></div>{typeof result.improvements === "string" && result.improvements && <p className="result-summary">{result.improvements}</p>}{Array.isArray(result.missing_keywords) && result.missing_keywords.length > 0 && <div className="missing-terms"><span>Worth highlighting, if applicable:</span>{result.missing_keywords.slice(0, 8).map((keyword) => <i key={String(keyword)}>{String(keyword)}</i>)}</div>}<pre className="resume-preview">{String(result.markdown_content || "")}</pre><div className="result-actions"><button className="button button-dark" onClick={() => resumeId && downloadResume(resumeId, "pdf")}><FileDown size={16} />Download PDF</button><button className="button button-outline" onClick={() => resumeId && downloadResume(resumeId, "docx")}>Download DOCX</button><button className="button button-outline" onClick={() => resumeId && downloadResume(resumeId, "md")}>Markdown</button></div></section>}
    </div>
  );
}

function JobsPage({ onTailor }: { onTailor: (job: Job) => void }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [location, setLocation] = useState("");
  const [remote, setRemote] = useState(false);
  const [age, setAge] = useState(30);
  const [count, setCount] = useState(10);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [filter, setFilter] = useState("all");
  const [searchMeta, setSearchMeta] = useState<{ errors: string[]; fallback: string | null } | null>(null);
  const load = useCallback(async (status?: string) => {
    const rows = await api.jobs(status === "all" ? undefined : status);
    setJobs(rows); setLoaded(true);
  }, []);
  useEffect(() => { load().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not load jobs.")); }, [load]);
  async function search(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setNotice(""); setSearchMeta(null);
    try {
      const result = await api.searchJobs({ location, remote_only: remote, max_age_days: age, top_n: count });
      setSearchMeta({ errors: result.source_errors || [], fallback: result.fallback_note });
      setNotice(`${result.results.length} new match${result.results.length === 1 ? "" : "es"} added to your list.`);
      await load(filter === "all" ? undefined : filter);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "We couldn't search right now."); }
    finally { setBusy(false); }
  }
  async function setStatus(job: Job, status: Job["status"]) {
    setError("");
    try {
      await api.updateJob(job.id, status);
      setNotice(status === "ignored" ? "Role hidden from your list." : `Marked as ${status}.`);
      await load(filter === "all" ? undefined : filter);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Status update failed."); }
  }
  const filtered = jobs.filter((job) => filter === "all" ? job.status !== "ignored" : job.status === filter);
  return (
    <div className="page-stack">
      <PageHeading eyebrow="THE NEXT GOOD FIT" title="Find opportunities" subtitle="Discover roles that line up with your experience—not just your search terms." />
      <form className="card search-panel" onSubmit={search}><div className="search-panel-head"><span className="search-illustration"><Search size={20} /></span><div><h2>Tell us what you're looking for.</h2><p>We'll search public job sources and rank opportunities against your profile.</p></div></div><div className="search-controls"><label>Location<input value={location} onChange={(event) => setLocation(event.target.value)} placeholder="City, country, or anywhere" /></label><label>Posted within<select value={age} onChange={(event) => setAge(Number(event.target.value))}><option value={7}>Last 7 days</option><option value={14}>Last 14 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option><option value={180}>Last 6 months</option></select></label><label>Results<select value={count} onChange={(event) => setCount(Number(event.target.value))}><option value={5}>Top 5</option><option value={10}>Top 10</option><option value={20}>Top 20</option></select></label><button className="button button-primary" disabled={busy}>{busy ? <LoaderCircle className="spin" size={16} /> : <Search size={16} />}{busy ? "Searching…" : "Find my matches"}</button></div><label className="toggle-control"><input type="checkbox" checked={remote} onChange={(event) => setRemote(event.target.checked)} /><span className="toggle-track" /><span>Remote roles only</span></label></form>
      {error && <div className="alert alert-error"><X size={16} />{error}</div>}{notice && <div className="alert alert-success"><Check size={16} />{notice}</div>}{searchMeta?.fallback && <div className="alert alert-note">{searchMeta.fallback}</div>}{searchMeta?.errors.map((item) => <div className="alert alert-note" key={item}>{item}</div>)}
      <div className="section-heading jobs-section-heading"><div><span className="eyebrow">YOUR SHORTLIST</span><h2>Roles worth a look</h2></div><div className="filter-tabs">{[["all", "All"], ["new", "New"], ["saved", "Saved"], ["applied", "Applied"]].map(([value, label]) => <button key={value} className={filter === value ? "selected" : ""} onClick={() => { setFilter(value); load(value === "all" ? undefined : value).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not filter jobs.")); }}>{label}</button>)}</div></div>
      {filtered.length > 0 ? <div className="job-grid">{filtered.map((job) => <JobCard key={job.id} job={job} onStatus={setStatus} onTailor={onTailor} />)}</div> : <div className="card empty-jobs"><span className="empty-jobs-art"><Compass size={28} /></span><h3>{loaded ? "Your shortlist has room for one more." : "Ready when you are."}</h3><p>{loaded ? "Try a fresh search to find roles that could be a great fit." : "Add a master resume, then search and find good-fit opportunities."}</p><button className="button button-outline" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>Back to search <ArrowUpRight size={15} /></button></div>}
    </div>
  );
}

function JobCard({ job, onStatus, onTailor }: { job: Job; onStatus: (job: Job, status: Job["status"]) => void; onTailor: (job: Job) => void }) {
  return <article className="card job-card"><div className="job-card-top"><span className="company-mark company-mark-large">{job.company.slice(0, 1).toUpperCase()}</span><span className={`job-status status-${job.status}`}>{job.status}</span><ScoreRing score={job.match_score} /></div><span className="job-source">{job.source}</span><h3>{job.title}</h3><div className="job-company">{job.company}</div><div className="job-location"><MapPin size={14} />{job.location || (job.remote ? "Remote" : "Location flexible")}<span>·</span>{job.remote ? "Remote-friendly" : prettyDate(job.posted_at)}</div><p className="job-fit">{job.fit_note || "A potential match based on your saved experience."}</p><div className="job-card-actions"><button className="button button-dark" onClick={() => onTailor(job)}><Sparkles size={15} />Tailor resume</button><a className="button button-outline" href={job.url} target="_blank" rel="noreferrer">View role <ArrowUpRight size={14} /></a></div><div className="job-card-footer"><span>Already applied?</span><button onClick={() => onStatus(job, "applied")}>Mark applied</button><button className="job-save" onClick={() => onStatus(job, job.status === "saved" ? "new" : "saved")}>{job.status === "saved" ? "Saved ✓" : "Save role"}</button></div></article>;
}

function ResumesPage() {
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => { api.resumes().then(setResumes).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not load resumes.")).finally(() => setBusy(false)); }, []);
  const filtered = resumes.filter((resume) => resume.title.toLowerCase().includes(query.toLowerCase()));
  return (
    <div className="page-stack">
      <PageHeading eyebrow="YOUR WORK, READY TO GO" title="My resumes" subtitle="Each version is shaped around a role and built from your verified experience." />
      <div className="resume-toolbar"><div className="resume-count"><strong>{resumes.length}</strong> {resumes.length === 1 ? "tailored version" : "tailored versions"}</div><div className="resume-search"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search by role title" /></div></div>
      {error && <div className="alert alert-error">{error}</div>}
      {busy ? <div className="loading-panel"><LoaderCircle className="spin" />Loading your resumes…</div> : filtered.length ? <div className="card history-table"><div className="history-header"><span>ROLE</span><span>DATE CREATED</span><span>ROLE MATCH</span><span>ATS SCORE</span><span>DOWNLOAD</span></div>{filtered.map((resume) => <ResumeHistoryRow key={resume.id} resume={resume} />)}</div> : <div className="card empty-jobs"><span className="empty-jobs-art"><FileText size={27} /></span><h3>{query ? "No title matches that search." : "Your first tailored resume is waiting."}</h3><p>{query ? "Try another search term." : "Bring a job description to the resume studio to create a version that's ready for that opportunity."}</p></div>}
    </div>
  );
}

function ResumeHistoryRow({ resume }: { resume: Resume }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  async function download(format: "pdf" | "docx" | "md") {
    setBusy(format); setError("");
    try { await downloadResume(resume.id, format); } catch (reason) { setError(reason instanceof Error ? reason.message : "Download failed."); }
    finally { setBusy(""); }
  }
  return <div className="history-row"><div className="history-role"><span className="document-icon"><FileText size={17} /></span><span><strong>{resume.title}</strong>{error && <small className="inline-error">{error}</small>}</span></div><span className="history-date">{prettyDate(resume.created_at)}</span><span className={`history-score ${scoreTone(resume.match_score)}`}>{resume.match_score === null ? "—" : `${Math.round(resume.match_score)}%`}</span><span className="history-score">{resume.ats_score === null ? "—" : `${Math.round(resume.ats_score)}%`}</span><div className="history-downloads">{(["pdf", "docx", "md"] as const).map((format) => <button key={format} title={`Download ${format.toUpperCase()}`} onClick={() => download(format)} disabled={Boolean(busy)}>{busy === format ? <LoaderCircle className="spin" size={14} /> : format.toUpperCase()}</button>)}</div></div>;
}

export default App;
