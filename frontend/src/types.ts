export type User = { id: number; username: string; email: string };

export type ResumeEntry = {
  id: string;
  title: string;
  company: string;
  location?: string | null;
  start_date: string;
  end_date: string;
  bullets: string[];
};

export type ProfileData = {
  contact: {
    name: string;
    email: string;
    phone: string;
    location: string;
    linkedin: string;
    github: string;
    portfolio: string;
  };
  summary: string;
  skills: string[];
  skill_categories: { category: string; items: string[] }[];
  experience: ResumeEntry[];
  projects: ResumeEntry[];
  education: ResumeEntry[];
  certifications: string[];
  achievements: string[];
};

export type ProfileResponse = {
  profile: ProfileData;
  has_profile: boolean;
  source: string | null;
  filename: string | null;
  master_page_count?: number;
  layout_profile?: Record<string, any> | null;
  updated_at: string | null;
};

export type Resume = {
  id: number;
  title: string;
  company: string | null;
  match_score: number | null;
  ats_score: number | null;
  page_count?: number;
  tailored_format?: string;
  has_tailored_document?: boolean;
  template_preserved?: boolean;
  improvement_summary: string | null;
  missing_keywords: string | null;
  created_at: string | null;
};

export type Job = {
  id: number;
  url: string;
  title: string;
  company: string;
  location: string | null;
  remote: boolean;
  posted_at: string;
  source: string;
  jd_text: string;
  match_score: number | null;
  fit_note: string | null;
  status: "new" | "saved" | "applied" | "ignored";
  created_at: string | null;
};

export type Dashboard = {
  user: User;
  profile: ProfileResponse;
  stats: {
    resume_count: number;
    saved_jobs: number;
    applied_jobs: number;
    profile_ready: boolean;
  };
  recent_resumes: Resume[];
  recent_jobs: Job[];
};

export const emptyProfile = (): ProfileData => ({
  contact: { name: "", email: "", phone: "", location: "", linkedin: "", github: "", portfolio: "" },
  summary: "",
  skills: [],
  skill_categories: [],
  experience: [],
  projects: [],
  education: [],
  certifications: [],
  achievements: [],
});
