"""Frequency workspace chrome — premium editorial UI, review-first lead detail."""

from __future__ import annotations

import html
import re

from .branding import brand_name, brand_wordmark


LIGHT_VARS = """
  /* Frequency signal desk — cool graphite (not cream) */
  --bg-primary: #EEF1F4;
  --bg-secondary: #E3E8EE;
  --surface-1: #F7F9FB;
  --surface-2: #EBEEF3;
  --surface-hover: #E0E5EC;
  --text-primary: #0E141B;
  --text-secondary: #4A5563;
  --text-tertiary: #7A8694;
  --border-subtle: #C9D2DC;
  --border-strong: #9AA8B5;
  --accent: #0F6E8C;
  --accent-hover: #0B5670;
  --accent-soft: rgba(15,110,140,.12);
  --accent-glow: rgba(15,110,140,.28);
  --on-accent: #FFFFFF;
  --btn-primary-bg: #0F6E8C;
  --btn-primary-hover: #0B5670;
  --btn-primary-fg: #FFFFFF;
  --btn-secondary-bg: #E8EEF4;
  --btn-secondary-hover: #D5DEE8;
  --btn-secondary-fg: #0E141B;
  --btn-secondary-border: #7A8B9C;
  --success: #0F7A5A;
  --success-soft: rgba(15,122,90,.12);
  --warning: #B45309;
  --warning-soft: rgba(180,83,9,.12);
  --danger: #B42318;
  --danger-soft: rgba(180,35,24,.12);
  --info: #0F6E8C;
  --ink: var(--text-primary);
  --mute: var(--text-secondary);
  --line: var(--border-subtle);
  --panel: var(--surface-1);
  --panel-2: var(--surface-2);
  --bg: var(--bg-primary);
  --wash: var(--bg-secondary);
  --primary: var(--accent);
  --primary-hover: var(--accent-hover);
  --primary-soft: var(--accent-soft);
  --on-primary: var(--on-accent);
  --link: var(--accent);
  --warn: var(--warning);
  --warn-soft: var(--warning-soft);
  --bad: var(--danger);
  --bad-soft: var(--danger-soft);
  --text-color: #0E141B;
  --background-color: #EEF1F4;
  --secondary-background-color: #F7F9FB;
  --primary-color: #0F6E8C;
"""

DARK_VARS = """
  /* Cinematic radar — deep ink + signal teal */
  --bg-primary: #05070A;
  --bg-secondary: #080B10;
  --surface-1: #0F141C;
  --surface-2: #151C27;
  --surface-hover: #1B2431;
  --text-primary: #EDF2F7;
  --text-secondary: #9AA8B8;
  --text-tertiary: #6B7787;
  --border-subtle: #243041;
  --border-strong: #3A4A5E;
  --accent: #3DB8D4;
  --accent-hover: #6AD0E6;
  --accent-soft: rgba(61,184,212,.16);
  --accent-glow: rgba(61,184,212,.35);
  --on-accent: #FFFFFF;
  /* Buttons use deeper teal — bright sky blue washes out white labels */
  --btn-primary-bg: #0E7A96;
  --btn-primary-hover: #1090B0;
  --btn-primary-fg: #FFFFFF;
  --btn-secondary-bg: #1A2330;
  --btn-secondary-hover: #243041;
  --btn-secondary-fg: #F3F7FB;
  --btn-secondary-border: #4A5C72;
  --success: #3DCF9A;
  --success-soft: rgba(61,207,154,.16);
  --warning: #E8A54B;
  --warning-soft: rgba(232,165,75,.16);
  --danger: #F07178;
  --danger-soft: rgba(240,113,120,.16);
  --info: #3DB8D4;
  --ink: var(--text-primary);
  --mute: var(--text-secondary);
  --line: var(--border-subtle);
  --panel: var(--surface-1);
  --panel-2: var(--surface-2);
  --bg: var(--bg-primary);
  --wash: var(--bg-secondary);
  --primary: var(--accent);
  --primary-hover: var(--accent-hover);
  --primary-soft: var(--accent-soft);
  --on-primary: var(--on-accent);
  --link: var(--accent);
  --warn: var(--warning);
  --warn-soft: var(--warning-soft);
  --bad: var(--danger);
  --bad-soft: var(--danger-soft);
  --text-color: #EDF2F7;
  --background-color: #05070A;
  --secondary-background-color: #0F141C;
  --primary-color: #0E7A96;
"""

SHARED_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@500;600;700;800&family=Manrope:wght@400;500;600;700&display=swap');

html, body, [data-testid="stAppViewContainer"], .stApp {
  background:
    radial-gradient(1200px 600px at 12% -10%, var(--accent-glow), transparent 55%),
    radial-gradient(900px 500px at 100% 0%, rgba(15,110,140,.10), transparent 50%),
    linear-gradient(180deg, var(--bg-secondary) 0%, transparent 280px),
    var(--bg-primary) !important;
  color: var(--text-primary);
  font-family: "Manrope", sans-serif;
  transition: background-color 220ms ease, color 220ms ease;
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"], #MainMenu, footer, [data-testid="stStatusWidget"] { visibility: hidden; }

section[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapseButton"] {
  display: none !important;
  width: 0 !important;
  min-width: 0 !important;
}

.block-container {
  padding-top: 0.75rem !important;
  padding-bottom: 2.8rem !important;
  max-width: 1320px;
}

/* ── Splash ── */
.fx-splash {
  position: fixed; inset: 0; z-index: 100000;
  display: flex; align-items: center; justify-content: center;
  background:
    radial-gradient(700px 400px at 50% 40%, var(--accent-glow), transparent 60%),
    var(--bg-primary);
  pointer-events: none;
  animation: fxSplashHold 0.32s ease-out, fxSplashOut 0.5s ease-in 0.38s forwards;
}
.fx-splash .fx-splash-word {
  font-family: "Syne", sans-serif;
  font-size: clamp(2rem, 5vw, 3.2rem);
  font-weight: 800;
  letter-spacing: 0.22em;
  text-indent: 0.22em;
  color: var(--text-primary);
  margin: 0;
  animation: fxSplashIn 0.45s cubic-bezier(.2,.7,.2,1) both;
}
.fx-splash .fx-splash-rule {
  width: 56px; height: 2px; background: var(--accent); margin: 16px auto 0;
  box-shadow: 0 0 18px var(--accent-glow);
  opacity: 0; animation: fxSplashIn 0.35s ease 0.12s both;
}
@keyframes fxSplashIn {
  from { opacity: 0; transform: translateY(10px) scale(.98); letter-spacing: 0.4em; }
  to { opacity: 1; transform: none; letter-spacing: 0.22em; }
}
@keyframes fxSplashHold { from { opacity: 1; } to { opacity: 1; } }
@keyframes fxSplashOut {
  to { opacity: 0; visibility: hidden; }
}

/* ── Shell / topbar ── */
.fx-shell { margin: 0; }
.fx-top {
  display: flex; align-items: flex-end; justify-content: space-between;
  gap: 16px; padding: 8px 0 20px; border-bottom: 1px solid var(--border-subtle);
  margin-bottom: 18px;
}
.fx-brand {
  display: flex; flex-direction: column; align-items: flex-start; gap: 8px;
}
.fx-wordmark {
  font-family: "Syne", sans-serif;
  font-size: clamp(2.15rem, 4.2vw, 2.95rem);
  letter-spacing: 0.2em;
  text-indent: 0.2em;
  text-transform: uppercase;
  color: var(--text-primary);
  margin: 0; font-weight: 800; line-height: 0.92;
  display: inline-block;
}
.fx-wordmark em {
  font-style: normal; color: var(--accent); margin-left: 2px;
  letter-spacing: 0;
  text-indent: 0;
}
.fx-top-sub {
  color: var(--text-tertiary); font-size: 11px; letter-spacing: 0.3em;
  text-transform: uppercase; margin: 0; font-weight: 600;
  opacity: 0.92;
}
.fx-shell-hint { height: 4px; margin: 0; }
.fx-kicker {
  font-size: 11px; letter-spacing: 0.2em; text-transform: uppercase;
  color: var(--accent); font-weight: 700; margin: 0 0 8px;
}
.fx-auth-shell { padding: 18px 0 8px; margin-bottom: 8px; }
.fx-auth-sub { color: var(--text-secondary); max-width: 42rem; margin: 0 0 6px; }
.fx-panel-hero {
  padding: 8px 0 18px; margin-bottom: 10px;
  border-bottom: 1px solid var(--border-subtle);
}
.fx-panel-hero h2 {
  font-family: "Syne", sans-serif; font-weight: 700; letter-spacing: -0.02em;
  margin: 0 0 8px; font-size: clamp(1.6rem, 2.8vw, 2.1rem);
}
.fx-panel-hero p { color: var(--text-secondary); margin: 0; max-width: 48rem; }
.fx-card-block {
  background: linear-gradient(145deg, var(--surface-1), var(--surface-2));
  border: 1px solid var(--border-subtle);
  border-radius: 16px; padding: 16px 18px; margin: 8px 0 14px;
  box-shadow: 0 12px 40px rgba(0,0,0,.08);
}
.fx-card-block p { margin: 0 0 6px; color: var(--text-secondary); }
.fx-card-block p:last-child { margin-bottom: 0; }
.fx-card-block strong { color: var(--text-primary); }

/* Buttons */
.stButton > button {
  border-radius: 999px !important;
  font-family: "Manrope", sans-serif !important;
  font-weight: 650 !important;
  letter-spacing: 0.01em;
  transition: transform 140ms ease, box-shadow 140ms ease, background 140ms ease !important;
}
.stButton > button[kind="primary"],
.stButton > button[data-testid="baseButton-primary"] {
  box-shadow: 0 0 0 1px var(--accent-soft), 0 8px 24px var(--accent-glow) !important;
}
.stButton > button:hover { transform: translateY(-1px); }

/* Tabs */
button[data-baseweb="tab"] {
  font-family: "Manrope", sans-serif !important;
  font-weight: 600 !important;
}
div[data-baseweb="tab-list"] {
  gap: 4px; border-bottom: 1px solid var(--border-subtle);
}

/* Inputs */
.stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] > div {
  border-radius: 12px !important;
}

/* ── Hero ── */
.fx-hero {
  border-bottom: 1px solid var(--border-subtle);
  padding: 4px 0 22px;
  margin-bottom: 14px;
}
.fx-hero h1 {
  font-family: "Syne", sans-serif;
  font-size: clamp(1.9rem, 3.4vw, 2.55rem);
  font-weight: 700; margin: 0 0 10px; color: var(--text-primary); line-height: 1.15;
  letter-spacing: -0.02em;
}
.fx-hero h1 em { color: var(--accent); font-style: italic; }
.fx-hero p {
  color: var(--text-secondary); margin: 0; font-size: 14.5px;
  max-width: 560px; line-height: 1.55;
}

/* ── Composer / command center ── */
.fx-composer {
  border: 1px solid var(--border-subtle);
  background: linear-gradient(160deg, var(--surface-1), var(--surface-2));
  padding: 20px 22px;
  margin: 0 0 16px;
  border-radius: 18px;
  box-shadow: 0 16px 48px rgba(0,0,0,.10);
}
.fx-composer .fx-composer-kicker {
  font-size: 10px; letter-spacing: .18em; text-transform: uppercase;
  color: var(--accent); margin: 0 0 6px; font-weight: 700;
}
.fx-composer h2 {
  font-family: "Syne", serif;
  font-size: 22px; font-weight: 400; margin: 0 0 6px; color: var(--text-primary);
}
.fx-composer p {
  margin: 0; color: var(--text-secondary); font-size: 13.5px; line-height: 1.5; max-width: 520px;
}

/* ── Empty state ── */
.fx-empty {
  border: 1px dashed var(--border-strong);
  background: var(--surface-2);
  padding: 28px 24px;
  margin: 12px 0 16px;
  border-radius: 6px;
  text-align: center;
}
.fx-empty h3 {
  font-family: "Syne", serif;
  font-size: 18px; font-weight: 400; margin: 0 0 8px; color: var(--text-primary);
}
.fx-empty p {
  margin: 0 auto; color: var(--text-secondary); font-size: 13.5px;
  line-height: 1.5; max-width: 420px;
}

/* ── Agent stage rail (single horizontal stepper) ── */
.fx-stage {
  display: block;
  padding: 10px 12px; margin: 0 0 12px;
  background: var(--surface-1); border: 1px solid var(--border-subtle);
  border-radius: 6px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}
.fx-stage-track {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 0;
  width: max-content;
  min-width: 100%;
}
.fx-stage-item {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 6px;
  font-family: "Manrope", sans-serif;
  font-size: 10.5px;
  letter-spacing: .02em;
  line-height: 1.2;
  white-space: nowrap;
  padding: 4px 2px;
  color: var(--text-tertiary);
  background: transparent;
  border: none;
  opacity: .55;
  transition: color 180ms ease, opacity 180ms ease;
}
.fx-stage-dot {
  width: 7px; height: 7px; border-radius: 50%; flex: 0 0 auto;
  background: var(--border-strong);
  box-shadow: none;
  transition: background 180ms ease, box-shadow 180ms ease, transform 180ms ease;
}
.fx-stage-label {
  font-weight: 500;
}
.fx-stage-sep {
  flex: 1 1 12px;
  min-width: 10px;
  max-width: 28px;
  height: 1px;
  margin: 0 4px;
  background: linear-gradient(90deg, var(--border-subtle), var(--border-strong), var(--border-subtle));
  opacity: .7;
}
.fx-stage-item.active {
  color: var(--accent);
  opacity: 1;
  font-weight: 600;
}
.fx-stage-item.active .fx-stage-dot {
  background: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft), 0 0 12px var(--accent-glow);
  transform: scale(1.15);
}
.fx-stage-item.done {
  color: var(--text-secondary);
  opacity: .9;
}
.fx-stage-item.done .fx-stage-dot {
  background: var(--accent);
  opacity: .85;
}
.fx-stage-item.upcoming {
  color: var(--text-tertiary);
  opacity: .45;
}

/* ── Background fetch dock (minimizable) ── */
.fx-job-dock {
  margin: 0 0 14px;
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  background: linear-gradient(145deg, var(--surface-1), var(--surface-2));
  box-shadow: 0 10px 28px rgba(0,0,0,.08);
  overflow: hidden;
}
.fx-job-dock-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
}
.fx-job-dock-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.fx-job-pulse {
  width: 10px; height: 10px; border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 0 0 var(--accent-glow);
  animation: fxJobPulse 1.4s ease-out infinite;
  flex: 0 0 auto;
}
@keyframes fxJobPulse {
  0% { box-shadow: 0 0 0 0 var(--accent-glow); }
  70% { box-shadow: 0 0 0 10px transparent; }
  100% { box-shadow: 0 0 0 0 transparent; }
}
.fx-job-dock-title {
  margin: 0;
  font-family: "Syne", sans-serif;
  font-weight: 700;
  font-size: 14px;
  color: var(--text-primary);
  letter-spacing: -0.01em;
}
.fx-job-dock-sub {
  margin: 2px 0 0;
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 52vw;
}
.fx-job-dock-body {
  padding: 0 12px 12px;
  border-top: 1px solid var(--border-subtle);
}
.fx-job-dock .fx-stage {
  margin: 10px 0 0;
  box-shadow: none;
}

/* ── Metric / results summary row ── */
.fx-metric-row {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px;
  margin: 0 0 14px;
}
@media (max-width: 720px) { .fx-metric-row { grid-template-columns: repeat(2, 1fr); } }
.fx-metric {
  background: var(--surface-1); border: 1px solid var(--border-subtle);
  padding: 12px 14px; border-radius: 6px;
}
.fx-metric .n {
  font-size: 22px; font-weight: 600; color: var(--text-primary); line-height: 1.1;
  font-variant-numeric: tabular-nums;
}
.fx-metric .l {
  font-size: 10px; letter-spacing: .1em; text-transform: uppercase;
  color: var(--text-tertiary); margin-top: 4px; font-weight: 500;
}

/* ── Fetch bar / mode ── */
.fx-bar {
  display: flex; align-items: baseline; justify-content: space-between; gap: 16px;
  border: 1px solid var(--border-subtle); background: var(--surface-1);
  padding: 12px 16px; margin: 0 0 14px; border-radius: 6px;
}
.fx-bar strong { color: var(--text-primary); font-weight: 600; }
.fx-bar span { color: var(--text-secondary); font-size: 13px; }
.fx-bar code {
  font-size: 11px; background: var(--surface-2); padding: 2px 6px;
  border-radius: 3px; color: var(--text-secondary);
}
.fx-mode {
  border: 1px solid var(--border-subtle); background: var(--surface-1);
  padding: 11px 14px; margin: 0 0 12px; border-radius: 6px;
  display: flex; flex-direction: column; gap: 4px;
  transition: border-color 160ms ease, background 160ms ease;
}
.fx-mode strong { font-size: 13px; color: var(--text-primary); letter-spacing: .03em; }
.fx-mode span { font-size: 13px; color: var(--text-secondary); line-height: 1.45; }
.fx-mode.new { border-color: var(--accent); background: var(--accent-soft); }
.fx-mode.same { border-color: var(--border-subtle); }

/* ── Funnel ── */
.fx-funnel {
  display: grid; grid-template-columns: repeat(6, 1fr); gap: 1px;
  background: var(--border-subtle); border: 1px solid var(--border-subtle);
  margin: 0 0 16px; border-radius: 6px; overflow: hidden;
}
@media (max-width: 900px) { .fx-funnel { grid-template-columns: repeat(3, 1fr); } }
.fx-step { background: var(--surface-1); padding: 12px 12px 11px; }
.fx-step .n {
  font-size: 20px; color: var(--text-primary); font-weight: 600; line-height: 1.1;
  font-variant-numeric: tabular-nums;
}
.fx-step .l {
  font-size: 10px; color: var(--text-tertiary); letter-spacing: .08em;
  text-transform: uppercase; margin-top: 5px; font-weight: 500;
}

/* ── Badges ── */
.fx-badges { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.badge {
  font-size: 10px; letter-spacing: .07em; text-transform: uppercase;
  padding: 4px 8px; border: 1px solid var(--border-subtle); color: var(--text-secondary);
  background: var(--surface-2); border-radius: 4px; font-weight: 500;
  display: inline-flex; align-items: center; gap: 4px;
}
.badge.high { border-color: var(--success); color: var(--success); background: var(--success-soft); }
.badge.med { border-color: var(--warning); color: var(--warning); background: var(--warning-soft); }
.badge.low, .badge.unver { border-color: var(--danger); color: var(--danger); background: var(--danger-soft); }
.badge.pending { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.badge.ok { border-color: var(--success); color: var(--success); background: var(--success-soft); }
.badge.trust-high::before { content: "✓ "; }
.badge.trust-med::before { content: "· "; }
.badge.trust-low::before { content: "! "; }
.badge.warn { border-color: var(--warning); color: var(--warning); background: var(--warning-soft); }

/* ── Pipeline ── */
.fx-pipe-card {
  border: 1px solid var(--border-subtle); background: var(--surface-1);
  border-radius: 12px; padding: 14px 16px; margin: 0 0 8px;
}
.fx-pipe-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.fx-pipe-card h3 {
  font-family: "Syne", sans-serif; font-size: 18px; margin: 2px 0 6px;
  color: var(--text-primary); font-weight: 700;
}
.fx-pipe-person { margin: 0 0 6px; color: var(--text-primary); font-size: 14px; }
.fx-pipe-meta { margin: 0 0 4px; color: var(--text-tertiary); font-size: 12px; }
.fx-pipe-meta code {
  font-size: 11px; background: var(--surface-2); padding: 1px 6px; border-radius: 4px;
}
.fx-pipe-comment {
  margin: 8px 0 0; color: var(--text-secondary); font-size: 13px;
  border-left: 2px solid var(--accent); padding-left: 10px;
}
.fx-stepper {
  display: flex; align-items: center; gap: 0; flex-wrap: wrap;
  margin: 6px 0 10px;
}
.fx-stepper .fx-st {
  font-size: 11px; letter-spacing: .04em; text-transform: uppercase;
  padding: 4px 8px; border-radius: 999px; font-weight: 650;
  color: var(--text-tertiary); background: var(--surface-2);
  border: 1px solid var(--border-subtle);
}
.fx-stepper .fx-st.on {
  color: var(--accent); background: var(--accent-soft); border-color: var(--accent);
}
.fx-stepper .fx-st.done {
  color: var(--success); background: var(--success-soft); border-color: var(--success);
}
.fx-stepper .fx-st.lost {
  color: var(--danger); background: var(--danger-soft); border-color: var(--danger);
}
.fx-stepper .fx-st-gap {
  width: 14px; height: 1px; background: var(--border-strong); margin: 0 4px;
}
.fx-pipe-detail {
  border: 1px solid var(--border-subtle); background: var(--surface-1);
  border-radius: 12px; padding: 14px 16px; margin: 8px 0 12px;
}
.fx-pipe-detail h3 {
  font-family: "Syne", sans-serif; font-size: 20px; margin: 0 0 6px;
}
.fx-sheet-wrap {
  overflow: auto; max-height: min(70vh, 720px);
  border: 1px solid #000; background: #fff; margin: 8px 0 16px;
}
.fx-sheet {
  width: 100%; border-collapse: collapse; background: #fff; color: #000;
  font-family: Calibri, "Segoe UI", Arial, sans-serif; font-size: 12.5px;
}
.fx-sheet th, .fx-sheet td {
  border: 1px solid #000; padding: 5px 8px; text-align: left;
  vertical-align: top; color: #000; background: #fff;
}
.fx-sheet thead th {
  position: sticky; top: 0; z-index: 2;
  background: #efefef; font-weight: 700; white-space: nowrap;
}
.fx-sheet td.fx-sheet-owner { font-weight: 600; }
.fx-sheet tr.fx-sheet-hit td { outline: 2px solid #c9a227; outline-offset: -2px; }
.fx-sheet .fx-sheet-mark { font-weight: 700; }

/* ── Search card ── */
.fx-search-card {
  border: 1px solid var(--border-subtle); background: var(--surface-1);
  padding: 14px 16px; margin: 0 0 10px; border-radius: 6px;
}
.fx-search-card .fx-search-title {
  font-family: "Syne", serif; font-size: 18px; color: var(--text-primary); margin: 0 0 4px;
}
.fx-search-card .fx-search-meta { color: var(--text-secondary); font-size: 12px; margin: 0 0 8px; }
.fx-fetch-row {
  display: flex; justify-content: space-between; gap: 10px; align-items: center;
  padding: 8px 0; border-top: 1px solid var(--border-subtle);
  font-size: 13px; color: var(--text-primary);
}

/* ── Lead detail ── */
.fx-detail { color: var(--text-primary); }
.fx-dh {
  display: flex; justify-content: space-between; align-items: flex-start; gap: 18px;
  padding-bottom: 16px; border-bottom: 1px solid var(--border-subtle); margin-bottom: 14px;
}
.fx-dh h2 {
  font-family: "Syne", serif;
  font-size: clamp(1.5rem, 2.5vw, 1.9rem);
  font-weight: 400; margin: 0 0 8px; color: var(--text-primary); line-height: 1.2;
}
.fx-dh-meta { color: var(--text-secondary); font-size: 13px; margin: 0; line-height: 1.5; }
.fx-dh-meta a { color: var(--accent); text-decoration: none; transition: color 150ms ease; }
.fx-dh-meta a:hover { color: var(--accent-hover); }
.fx-scorebox {
  min-width: 72px; text-align: right; padding: 8px 12px;
  background: var(--surface-2); border: 1px solid var(--border-subtle); border-radius: 6px;
}
.fx-scorebox .n {
  font-size: 32px; font-weight: 600; color: var(--text-primary); line-height: 1;
  font-variant-numeric: tabular-nums;
}
.fx-scorebox .l {
  font-size: 10px; letter-spacing: .12em; text-transform: uppercase;
  color: var(--text-tertiary); margin-top: 5px; font-weight: 500;
}

.fx-chips { display: flex; gap: 6px; flex-wrap: wrap; margin: 0 0 16px; }

.fx-grid {
  display: grid; grid-template-columns: 1.1fr 1fr .9fr; gap: 10px; margin-bottom: 18px;
}
@media (max-width: 1100px) { .fx-grid { grid-template-columns: 1fr; } }
.fx-tile {
  background: var(--surface-1); border: 1px solid var(--border-subtle);
  padding: 14px 14px 12px; min-height: 118px; border-radius: 6px;
  transition: border-color 160ms ease, background 160ms ease;
}
.fx-tile:hover { background: var(--surface-hover); }
.fx-tile .k {
  font-size: 10px; letter-spacing: .14em; text-transform: uppercase;
  color: var(--text-tertiary); margin: 0 0 8px; font-weight: 500;
}
.fx-tile h4 { margin: 0 0 4px; font-size: 15px; font-weight: 600; color: var(--text-primary); }
.fx-tile p { margin: 0; color: var(--text-secondary); font-size: 13px; line-height: 1.45; }
.fx-tile a { color: var(--accent); text-decoration: none; }

.fx-sec { margin: 22px 0 0; }
.fx-sec h3 {
  font-size: 11px; letter-spacing: .14em; text-transform: uppercase;
  color: var(--text-tertiary); margin: 0 0 10px; font-weight: 500;
  border-bottom: 1px solid var(--border-subtle); padding-bottom: 8px;
}
.fx-copy { color: var(--text-primary); font-size: 14.5px; line-height: 1.55; margin: 0; }
.fx-muted { color: var(--text-secondary); font-size: 13px; }

.fx-bars { display: grid; gap: 8px; }
.fx-barline { display: grid; grid-template-columns: 72px 1fr 28px; gap: 8px; align-items: center; }
.fx-barline span { font-size: 11px; color: var(--text-secondary); }
.fx-barline b { font-size: 11px; color: var(--text-primary); text-align: right; font-weight: 500; }
.fx-track { height: 4px; background: var(--bg-secondary); border-radius: 2px; overflow: hidden; }
.fx-fill { height: 4px; background: var(--accent); border-radius: 2px; transition: width 180ms ease; }

.fx-person {
  border: 1px solid var(--border-subtle); background: var(--surface-1);
  padding: 12px 14px; margin-bottom: 8px; border-radius: 6px;
  transition: border-color 160ms ease, background 160ms ease;
}
.fx-person.primary {
  border-left: 3px solid var(--accent); background: var(--accent-soft);
}
.fx-person-top { display: flex; justify-content: space-between; gap: 10px; align-items: baseline; }
.fx-person-top strong { font-size: 15px; color: var(--text-primary); }
.fx-person-top em { font-style: normal; color: var(--text-tertiary); font-size: 12px; }
.fx-person .role { color: var(--text-secondary); font-size: 13px; margin: 2px 0 8px; }
.fx-chans { display: flex; flex-wrap: wrap; gap: 8px 14px; font-size: 12.5px; color: var(--text-primary); }
.fx-chans a { color: var(--accent); text-decoration: none; }
.fx-why { color: var(--text-secondary); font-size: 12.5px; margin: 8px 0 0; line-height: 1.4; }

.fx-src { font-size: 13px; margin: 0 0 6px; color: var(--text-secondary); }
.fx-src a { color: var(--accent); text-decoration: none; }
.fx-letter {
  background: var(--surface-2); border-left: 3px solid var(--accent);
  padding: 14px 16px; border-radius: 0 6px 6px 0;
  white-space: pre-wrap; color: var(--text-primary); line-height: 1.55; font-size: 14px;
}
.fx-proof {
  margin: 0 0 10px; padding: 10px 12px; border-left: 2px solid var(--border-strong);
  background: var(--surface-2); border-radius: 0 4px 4px 0;
}
.fx-proof.related { border-left-color: #b8894a; }
.fx-proof b { color: var(--text-primary); }
.fx-proof p { margin: 2px 0 0; color: var(--text-secondary); font-size: 13.5px; line-height: 1.4; }
.fx-proof-tier {
  display: inline-block; margin-left: 6px; font-size: 11px; font-weight: 600;
  letter-spacing: 0.02em; text-transform: uppercase; color: var(--text-secondary);
}
.fx-proof-tier.related { color: #9a6b2f; }
.fx-proof-hint {
  margin-top: 6px !important; font-size: 12.5px !important; line-height: 1.45 !important;
}
.fx-flag { font-size: 13px; color: var(--warning); margin: 0 0 4px; }
.fx-flag.ok { color: var(--text-secondary); }

/* Direct / Indirect contact cards */
.fx-banner { font-size: 28px; font-weight: 600; letter-spacing: -0.02em; margin: 4px 0 6px; color: var(--text-primary); }
.fx-banner em { font-style: italic; font-weight: 500; color: var(--accent); }
.fx-banner-sub { color: var(--text-secondary); font-size: 14px; margin: 0 0 14px; line-height: 1.45; max-width: 52rem; }
.fx-rail { display: flex; gap: 8px; flex-wrap: wrap; margin: 0 0 18px; }
.fx-pill {
  display: inline-flex; align-items: center; gap: 8px;
  background: var(--accent-soft); color: var(--accent);
  padding: 6px 12px; border-radius: 999px; font-size: 12px; font-weight: 500;
}
.fx-pill .n { font-weight: 700; font-size: 14px; }
.fx-pill.indirect { background: var(--warning-soft); color: var(--warning); }
.fx-hit {
  margin: 0 0 14px; border: 1px solid var(--border-subtle); border-radius: 10px;
  background: var(--surface-1); overflow: hidden;
  animation: fx-in 280ms ease both;
}
.fx-hit.indirect { border-left: 3px solid var(--warning); }
@keyframes fx-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.fx-hit-inner { padding: 16px 18px 18px; }
.fx-hit-top { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 12px; }
.fx-hit-co { margin: 0; font-size: 18px; font-weight: 600; color: var(--text-primary); }
.fx-hit-meta { margin: 4px 0 0; font-size: 12.5px; color: var(--text-secondary); }
.fx-hit-meta a { color: var(--accent); text-decoration: none; }
.fx-hit-score { text-align: right; }
.fx-hit-score .n { font-size: 22px; font-weight: 600; color: var(--accent); line-height: 1; }
.fx-hit-score .l { font-size: 10px; letter-spacing: .12em; text-transform: uppercase; color: var(--text-tertiary); }
.fx-person-block {
  display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr); gap: 16px;
}
@media (max-width: 900px) { .fx-person-block { grid-template-columns: 1fr; } }
.fx-who h4 { margin: 0; font-size: 15px; color: var(--text-primary); }
.fx-who .role { margin: 2px 0 10px; color: var(--text-secondary); font-size: 13px; }
.fx-chan-chip {
  display: inline-block; margin: 0 8px 8px 0; padding: 4px 10px;
  background: var(--surface-2); border: 1px solid var(--border-subtle);
  border-radius: 999px; font-size: 12px; color: var(--text-primary);
}
.fx-chan-chip a { color: var(--accent); text-decoration: none; }
.fx-mail-label {
  font-size: 10px; letter-spacing: .14em; text-transform: uppercase;
  color: var(--text-tertiary); margin: 0 0 6px; font-weight: 500;
}
.fx-mail {
  background: var(--surface-2); border-left: 3px solid var(--accent);
  padding: 12px 14px; border-radius: 0 6px 6px 0;
  white-space: pre-wrap; color: var(--text-primary); line-height: 1.5; font-size: 13.5px;
  max-height: 280px; overflow: auto;
}
.fx-person-mail {
  margin-top: 10px; background: var(--surface-2); border-left: 3px solid var(--accent);
  padding: 10px 12px; border-radius: 0 6px 6px 0;
  white-space: pre-wrap; color: var(--text-primary); line-height: 1.5; font-size: 13px;
}

/* ── Buttons (high-contrast labels; covers Streamlit 1.6x kinds) ── */
.stButton > button,
.stDownloadButton > button,
.stFormSubmitButton > button,
button[kind="secondary"],
button[kind="secondaryFormSubmit"],
button[kind="tertiary"],
button[kind="tertiaryFormSubmit"],
[data-testid="baseButton-secondary"],
[data-testid="baseButton-secondaryFormSubmit"],
[data-testid="baseButton-tertiary"],
[data-testid="baseButton-tertiaryFormSubmit"] {
  background: var(--btn-secondary-bg) !important;
  color: var(--btn-secondary-fg) !important;
  -webkit-text-fill-color: var(--btn-secondary-fg) !important;
  border: 1px solid var(--btn-secondary-border) !important;
  font-weight: 600 !important;
  border-radius: 5px !important;
  padding: 0.55rem 1rem !important;
  opacity: 1 !important;
  transition: background 160ms ease, border-color 160ms ease, color 160ms ease !important;
}
.stButton > button:hover,
.stDownloadButton > button:hover,
.stFormSubmitButton > button:hover,
button[kind="secondary"]:hover,
button[kind="secondaryFormSubmit"]:hover,
button[kind="tertiary"]:hover,
button[kind="tertiaryFormSubmit"]:hover,
[data-testid="baseButton-secondary"]:hover,
[data-testid="baseButton-secondaryFormSubmit"]:hover,
[data-testid="baseButton-tertiary"]:hover,
[data-testid="baseButton-tertiaryFormSubmit"]:hover {
  border-color: var(--btn-secondary-border) !important;
  background: var(--btn-secondary-hover) !important;
  color: var(--btn-secondary-fg) !important;
  -webkit-text-fill-color: var(--btn-secondary-fg) !important;
}
.stButton > button p,
.stButton > button span,
.stButton > button div,
.stButton > button [data-testid="stMarkdownContainer"],
.stButton > button [data-testid="stMarkdownContainer"] p,
.stDownloadButton > button p,
.stDownloadButton > button span,
.stDownloadButton > button div,
.stDownloadButton > button [data-testid="stMarkdownContainer"],
.stDownloadButton > button [data-testid="stMarkdownContainer"] p,
.stFormSubmitButton > button p,
.stFormSubmitButton > button span,
.stFormSubmitButton > button div,
.stFormSubmitButton > button [data-testid="stMarkdownContainer"],
.stFormSubmitButton > button [data-testid="stMarkdownContainer"] p,
button[kind="secondary"] p,
button[kind="secondary"] span,
button[kind="secondary"] div,
button[kind="secondary"] [data-testid="stMarkdownContainer"] p,
button[kind="secondaryFormSubmit"] p,
button[kind="secondaryFormSubmit"] span,
button[kind="secondaryFormSubmit"] div,
button[kind="secondaryFormSubmit"] [data-testid="stMarkdownContainer"] p,
button[kind="tertiary"] p,
button[kind="tertiary"] span,
button[kind="tertiary"] div,
button[kind="tertiary"] [data-testid="stMarkdownContainer"] p,
button[kind="tertiaryFormSubmit"] p,
button[kind="tertiaryFormSubmit"] span,
button[kind="tertiaryFormSubmit"] div,
button[kind="tertiaryFormSubmit"] [data-testid="stMarkdownContainer"] p,
[data-testid="baseButton-secondary"] p,
[data-testid="baseButton-secondary"] span,
[data-testid="baseButton-secondary"] div,
[data-testid="baseButton-secondary"] [data-testid="stMarkdownContainer"] p,
[data-testid="baseButton-secondaryFormSubmit"] p,
[data-testid="baseButton-secondaryFormSubmit"] span,
[data-testid="baseButton-secondaryFormSubmit"] div,
[data-testid="baseButton-secondaryFormSubmit"] [data-testid="stMarkdownContainer"] p,
[data-testid="baseButton-tertiary"] p,
[data-testid="baseButton-tertiary"] span,
[data-testid="baseButton-tertiary"] div,
[data-testid="baseButton-tertiary"] [data-testid="stMarkdownContainer"] p,
[data-testid="baseButton-tertiaryFormSubmit"] p,
[data-testid="baseButton-tertiaryFormSubmit"] span,
[data-testid="baseButton-tertiaryFormSubmit"] div,
[data-testid="baseButton-tertiaryFormSubmit"] [data-testid="stMarkdownContainer"] p {
  color: var(--btn-secondary-fg) !important;
  -webkit-text-fill-color: var(--btn-secondary-fg) !important;
  opacity: 1 !important;
}

.stButton > button[kind="primary"],
.stButton > button[kind="primaryFormSubmit"],
.stButton > button[data-testid="baseButton-primary"],
.stButton > button[data-testid="baseButton-primaryFormSubmit"],
.stDownloadButton > button[kind="primary"],
.stDownloadButton > button[data-testid="baseButton-primary"],
.stFormSubmitButton > button[kind="primary"],
.stFormSubmitButton > button[kind="primaryFormSubmit"],
.stFormSubmitButton > button[data-testid="baseButton-primary"],
.stFormSubmitButton > button[data-testid="baseButton-primaryFormSubmit"],
button[kind="primary"],
button[kind="primaryFormSubmit"],
[data-testid="baseButton-primary"],
[data-testid="baseButton-primaryFormSubmit"] {
  background: var(--btn-primary-bg) !important;
  color: #FFFFFF !important;
  -webkit-text-fill-color: #FFFFFF !important;
  border: 0 !important;
  font-weight: 700 !important;
  opacity: 1 !important;
}
.stButton > button[kind="primary"]:hover,
.stButton > button[kind="primaryFormSubmit"]:hover,
.stButton > button[data-testid="baseButton-primary"]:hover,
.stButton > button[data-testid="baseButton-primaryFormSubmit"]:hover,
.stDownloadButton > button[kind="primary"]:hover,
.stDownloadButton > button[data-testid="baseButton-primary"]:hover,
.stFormSubmitButton > button[kind="primary"]:hover,
.stFormSubmitButton > button[kind="primaryFormSubmit"]:hover,
.stFormSubmitButton > button[data-testid="baseButton-primary"]:hover,
.stFormSubmitButton > button[data-testid="baseButton-primaryFormSubmit"]:hover,
button[kind="primary"]:hover,
button[kind="primaryFormSubmit"]:hover,
[data-testid="baseButton-primary"]:hover,
[data-testid="baseButton-primaryFormSubmit"]:hover {
  background: var(--btn-primary-hover) !important;
  color: #FFFFFF !important;
  -webkit-text-fill-color: #FFFFFF !important;
}
.stButton > button[kind="primary"] p,
.stButton > button[kind="primary"] span,
.stButton > button[kind="primary"] div,
.stButton > button[kind="primary"] [data-testid="stMarkdownContainer"],
.stButton > button[kind="primary"] [data-testid="stMarkdownContainer"] p,
.stButton > button[kind="primaryFormSubmit"] p,
.stButton > button[kind="primaryFormSubmit"] span,
.stButton > button[kind="primaryFormSubmit"] div,
.stButton > button[kind="primaryFormSubmit"] [data-testid="stMarkdownContainer"],
.stButton > button[kind="primaryFormSubmit"] [data-testid="stMarkdownContainer"] p,
.stButton > button[data-testid="baseButton-primary"] p,
.stButton > button[data-testid="baseButton-primary"] span,
.stButton > button[data-testid="baseButton-primary"] div,
.stButton > button[data-testid="baseButton-primary"] [data-testid="stMarkdownContainer"] p,
.stButton > button[data-testid="baseButton-primaryFormSubmit"] p,
.stButton > button[data-testid="baseButton-primaryFormSubmit"] span,
.stButton > button[data-testid="baseButton-primaryFormSubmit"] div,
.stButton > button[data-testid="baseButton-primaryFormSubmit"] [data-testid="stMarkdownContainer"] p,
.stDownloadButton > button[kind="primary"] p,
.stDownloadButton > button[kind="primary"] span,
.stDownloadButton > button[kind="primary"] div,
.stDownloadButton > button[kind="primary"] [data-testid="stMarkdownContainer"] p,
.stDownloadButton > button[data-testid="baseButton-primary"] p,
.stDownloadButton > button[data-testid="baseButton-primary"] span,
.stDownloadButton > button[data-testid="baseButton-primary"] div,
.stDownloadButton > button[data-testid="baseButton-primary"] [data-testid="stMarkdownContainer"] p,
.stFormSubmitButton > button[kind="primary"] p,
.stFormSubmitButton > button[kind="primary"] span,
.stFormSubmitButton > button[kind="primary"] div,
.stFormSubmitButton > button[kind="primary"] [data-testid="stMarkdownContainer"] p,
.stFormSubmitButton > button[kind="primaryFormSubmit"] p,
.stFormSubmitButton > button[kind="primaryFormSubmit"] span,
.stFormSubmitButton > button[kind="primaryFormSubmit"] div,
.stFormSubmitButton > button[kind="primaryFormSubmit"] [data-testid="stMarkdownContainer"] p,
.stFormSubmitButton > button[data-testid="baseButton-primary"] p,
.stFormSubmitButton > button[data-testid="baseButton-primary"] span,
.stFormSubmitButton > button[data-testid="baseButton-primary"] div,
.stFormSubmitButton > button[data-testid="baseButton-primary"] [data-testid="stMarkdownContainer"] p,
.stFormSubmitButton > button[data-testid="baseButton-primaryFormSubmit"] p,
.stFormSubmitButton > button[data-testid="baseButton-primaryFormSubmit"] span,
.stFormSubmitButton > button[data-testid="baseButton-primaryFormSubmit"] div,
.stFormSubmitButton > button[data-testid="baseButton-primaryFormSubmit"] [data-testid="stMarkdownContainer"] p,
button[kind="primary"] p,
button[kind="primary"] span,
button[kind="primary"] div,
button[kind="primary"] [data-testid="stMarkdownContainer"] p,
button[kind="primaryFormSubmit"] p,
button[kind="primaryFormSubmit"] span,
button[kind="primaryFormSubmit"] div,
button[kind="primaryFormSubmit"] [data-testid="stMarkdownContainer"] p,
[data-testid="baseButton-primary"] p,
[data-testid="baseButton-primary"] span,
[data-testid="baseButton-primary"] div,
[data-testid="baseButton-primary"] [data-testid="stMarkdownContainer"] p,
[data-testid="baseButton-primaryFormSubmit"] p,
[data-testid="baseButton-primaryFormSubmit"] span,
[data-testid="baseButton-primaryFormSubmit"] div,
[data-testid="baseButton-primaryFormSubmit"] [data-testid="stMarkdownContainer"] p {
  color: #FFFFFF !important;
  -webkit-text-fill-color: #FFFFFF !important;
  opacity: 1 !important;
}

/* Default download = primary teal + white label */
.stDownloadButton > button {
  background: var(--btn-primary-bg) !important;
  color: #FFFFFF !important;
  -webkit-text-fill-color: #FFFFFF !important;
  border: 0 !important;
  font-weight: 700 !important;
  border-radius: 5px !important;
  opacity: 1 !important;
}
.stDownloadButton > button p,
.stDownloadButton > button span,
.stDownloadButton > button div,
.stDownloadButton > button [data-testid="stMarkdownContainer"],
.stDownloadButton > button [data-testid="stMarkdownContainer"] p {
  color: #FFFFFF !important;
  -webkit-text-fill-color: #FFFFFF !important;
  opacity: 1 !important;
}

.fx-page-kicker {
  font-size: 11px; letter-spacing: .14em; text-transform: uppercase;
  color: var(--text-secondary); margin: 4px 0 12px; font-weight: 500;
}

/* ── Inputs ── */
div[data-testid="stTextArea"] textarea,
div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input {
  color: var(--text-primary) !important;
  background: var(--surface-1) !important;
  border: 1px solid var(--border-subtle) !important;
  border-radius: 5px !important;
  -webkit-text-fill-color: var(--text-primary) !important;
  transition: border-color 160ms ease !important;
}
div[data-testid="stTextArea"] textarea:focus,
div[data-testid="stTextInput"] input:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 1px var(--accent-soft) !important;
}
div[data-testid="stSelectbox"] div,
div[data-testid="stSelectbox"] span {
  color: var(--text-primary) !important;
}
label, [data-testid="stWidgetLabel"] p {
  color: var(--text-secondary) !important;
}

/* Body copy — never inside primary buttons */
.stMarkdown, .stCaption { color: var(--text-secondary); }
.stMarkdown p, .stMarkdown li { color: var(--text-primary); }
.stCaption, [data-testid="stCaptionContainer"] {
  color: var(--text-secondary) !important;
}
.stCaption p, [data-testid="stCaptionContainer"] p {
  color: var(--text-secondary) !important;
}

/* Force Streamlit text readable (exclude button label containers) */
.stApp [data-testid="stMarkdownContainer"] p {
  color: var(--text-primary);
}
button[kind="primary"] [data-testid="stMarkdownContainer"] p,
button[kind="primaryFormSubmit"] [data-testid="stMarkdownContainer"] p,
[data-testid="baseButton-primary"] [data-testid="stMarkdownContainer"] p,
[data-testid="baseButton-primaryFormSubmit"] [data-testid="stMarkdownContainer"] p,
.stDownloadButton [data-testid="stMarkdownContainer"] p,
.stFormSubmitButton button[kind="primary"] [data-testid="stMarkdownContainer"] p,
.stFormSubmitButton button[kind="primaryFormSubmit"] [data-testid="stMarkdownContainer"] p {
  color: #FFFFFF !important;
  -webkit-text-fill-color: #FFFFFF !important;
}
.stButton > button[data-testid="baseButton-secondary"] [data-testid="stMarkdownContainer"] p,
.stButton > button[data-testid="baseButton-secondaryFormSubmit"] [data-testid="stMarkdownContainer"] p,
.stFormSubmitButton button[kind="secondary"] [data-testid="stMarkdownContainer"] p,
.stFormSubmitButton button[kind="secondaryFormSubmit"] [data-testid="stMarkdownContainer"] p,
button[kind="secondary"] [data-testid="stMarkdownContainer"] p,
button[kind="secondaryFormSubmit"] [data-testid="stMarkdownContainer"] p,
button[kind="tertiary"] [data-testid="stMarkdownContainer"] p,
button[kind="tertiaryFormSubmit"] [data-testid="stMarkdownContainer"] p {
  color: var(--btn-secondary-fg) !important;
  -webkit-text-fill-color: var(--btn-secondary-fg) !important;
}

/* ── Radio list ── */
[data-testid="stRadio"] > label,
[data-testid="stRadio"] [data-testid="stWidgetLabel"] {
  display: none !important; height: 0 !important; margin: 0 !important; padding: 0 !important;
}
div[role="radiogroup"] { gap: 0 !important; }
div[role="radiogroup"] label {
  background: var(--surface-1) !important;
  border: 1px solid var(--border-subtle) !important;
  border-radius: 4px !important;
  padding: 10px 12px !important;
  margin: 0 0 4px !important;
  font-size: 13px !important;
  line-height: 1.35 !important;
  color: var(--text-primary) !important;
  transition: background 160ms ease, border-color 160ms ease !important;
}
div[role="radiogroup"] label p,
div[role="radiogroup"] label span,
div[role="radiogroup"] label div {
  color: var(--text-primary) !important;
}
div[role="radiogroup"] label:has(input:checked) {
  border-color: var(--accent) !important;
  background: var(--accent-soft) !important;
  position: relative; z-index: 1;
}
div[role="radiogroup"] label:has(input:checked),
div[role="radiogroup"] label:has(input:checked) p,
div[role="radiogroup"] label:has(input:checked) span,
div[role="radiogroup"] label:has(input:checked) div {
  color: var(--text-primary) !important;
}

/* ── Tabs ── */
div[data-testid="stTabs"] button {
  font-family: "Manrope", sans-serif;
  letter-spacing: .03em; color: var(--text-secondary) !important;
  -webkit-text-fill-color: var(--text-secondary) !important;
  transition: color 160ms ease !important;
}
div[data-testid="stTabs"] button p,
div[data-testid="stTabs"] button span,
div[data-testid="stTabs"] button div {
  color: inherit !important;
  -webkit-text-fill-color: inherit !important;
}
div[data-testid="stTabs"] button[aria-selected="true"] {
  color: var(--text-primary) !important;
  -webkit-text-fill-color: var(--text-primary) !important;
  border-bottom-color: var(--accent) !important;
}
div[data-testid="stTabs"] button[aria-selected="true"] p,
div[data-testid="stTabs"] button[aria-selected="true"] span,
div[data-testid="stTabs"] button[aria-selected="true"] div {
  color: var(--text-primary) !important;
  -webkit-text-fill-color: var(--text-primary) !important;
}
hr { border-color: var(--border-subtle) !important; }

/* ── Expanders ── */
[data-testid="stExpander"] {
  background: var(--surface-1) !important;
  border: 1px solid var(--border-subtle) !important;
  border-radius: 6px !important;
  color: var(--text-primary) !important;
}
[data-testid="stExpander"] p,
[data-testid="stExpander"] span,
[data-testid="stExpander"] summary {
  color: var(--text-primary) !important;
}

/* ── Metrics / checkboxes / tables ── */
[data-testid="stMetricValue"] { color: var(--text-primary) !important; }
[data-testid="stMetricLabel"] { color: var(--text-secondary) !important; }

[data-testid="stCheckbox"] label,
[data-testid="stCheckbox"] label span,
[data-testid="stCheckbox"] label p {
  color: var(--text-primary) !important;
}

[data-testid="stDataFrame"],
[data-testid="stTable"] {
  color: var(--text-primary);
}

/* ── Final button label lock (wins cascade vs body markdown ink) ── */
button[kind="primary"],
button[kind="primaryFormSubmit"],
[data-testid="baseButton-primary"],
[data-testid="baseButton-primaryFormSubmit"],
.stDownloadButton > button {
  color: #FFFFFF !important;
  -webkit-text-fill-color: #FFFFFF !important;
}
button[kind="primary"] p,
button[kind="primary"] span,
button[kind="primary"] div,
button[kind="primary"] [data-testid="stMarkdownContainer"] p,
button[kind="primaryFormSubmit"] p,
button[kind="primaryFormSubmit"] span,
button[kind="primaryFormSubmit"] div,
button[kind="primaryFormSubmit"] [data-testid="stMarkdownContainer"] p,
[data-testid="baseButton-primary"] p,
[data-testid="baseButton-primary"] span,
[data-testid="baseButton-primary"] div,
[data-testid="baseButton-primary"] [data-testid="stMarkdownContainer"] p,
[data-testid="baseButton-primaryFormSubmit"] p,
[data-testid="baseButton-primaryFormSubmit"] span,
[data-testid="baseButton-primaryFormSubmit"] div,
[data-testid="baseButton-primaryFormSubmit"] [data-testid="stMarkdownContainer"] p,
.stDownloadButton > button p,
.stDownloadButton > button span,
.stDownloadButton > button div,
.stDownloadButton > button [data-testid="stMarkdownContainer"] p {
  color: #FFFFFF !important;
  -webkit-text-fill-color: #FFFFFF !important;
}
button[kind="secondary"],
button[kind="secondaryFormSubmit"],
button[kind="tertiary"],
button[kind="tertiaryFormSubmit"],
[data-testid="baseButton-secondary"],
[data-testid="baseButton-secondaryFormSubmit"],
[data-testid="baseButton-tertiary"],
[data-testid="baseButton-tertiaryFormSubmit"] {
  color: var(--btn-secondary-fg) !important;
  -webkit-text-fill-color: var(--btn-secondary-fg) !important;
}
button[kind="secondary"] p,
button[kind="secondary"] span,
button[kind="secondary"] div,
button[kind="secondary"] [data-testid="stMarkdownContainer"] p,
button[kind="secondaryFormSubmit"] p,
button[kind="secondaryFormSubmit"] span,
button[kind="secondaryFormSubmit"] div,
button[kind="secondaryFormSubmit"] [data-testid="stMarkdownContainer"] p,
button[kind="tertiary"] p,
button[kind="tertiary"] span,
button[kind="tertiary"] div,
button[kind="tertiary"] [data-testid="stMarkdownContainer"] p,
button[kind="tertiaryFormSubmit"] p,
button[kind="tertiaryFormSubmit"] span,
button[kind="tertiaryFormSubmit"] div,
button[kind="tertiaryFormSubmit"] [data-testid="stMarkdownContainer"] p,
[data-testid="baseButton-secondary"] p,
[data-testid="baseButton-secondary"] span,
[data-testid="baseButton-secondary"] div,
[data-testid="baseButton-secondary"] [data-testid="stMarkdownContainer"] p,
[data-testid="baseButton-secondaryFormSubmit"] p,
[data-testid="baseButton-secondaryFormSubmit"] span,
[data-testid="baseButton-secondaryFormSubmit"] div,
[data-testid="baseButton-secondaryFormSubmit"] [data-testid="stMarkdownContainer"] p,
[data-testid="baseButton-tertiary"] p,
[data-testid="baseButton-tertiary"] span,
[data-testid="baseButton-tertiary"] div,
[data-testid="baseButton-tertiary"] [data-testid="stMarkdownContainer"] p,
[data-testid="baseButton-tertiaryFormSubmit"] p,
[data-testid="baseButton-tertiaryFormSubmit"] span,
[data-testid="baseButton-tertiaryFormSubmit"] div,
[data-testid="baseButton-tertiaryFormSubmit"] [data-testid="stMarkdownContainer"] p {
  color: var(--btn-secondary-fg) !important;
  -webkit-text-fill-color: var(--btn-secondary-fg) !important;
}

/* ── Signal desk ── */
.fx-desk-hero {
  padding: 4px 0 26px;
  margin: 0 0 8px;
  border-bottom: 1px solid var(--border-subtle);
}
.fx-desk-hero h2 {
  font-family: "Syne", sans-serif;
  font-size: clamp(1.95rem, 3.6vw, 2.7rem);
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1.08;
  margin: 0 0 12px;
  color: var(--text-primary);
}
.fx-desk-hero h2 em {
  color: var(--accent);
  font-style: italic;
  font-weight: 600;
}
.fx-desk-hero p {
  color: var(--text-secondary);
  margin: 0;
  max-width: 44rem;
  font-size: 14.5px;
  line-height: 1.6;
}
.fx-desk-panel {
  background: linear-gradient(160deg, var(--surface-1), var(--surface-2));
  border: 1px solid var(--border-subtle);
  border-radius: 18px;
  padding: 18px 20px 8px;
  margin: 0 0 12px;
  min-height: 148px;
  box-shadow: 0 16px 44px rgba(0,0,0,.08);
}
.fx-desk-panel-kicker {
  font-size: 10px;
  letter-spacing: .2em;
  text-transform: uppercase;
  color: var(--accent);
  font-weight: 700;
  margin: 0 0 8px;
}
.fx-desk-panel h3 {
  font-family: "Syne", sans-serif;
  font-size: 1.15rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin: 0 0 8px;
  color: var(--text-primary);
}
.fx-desk-panel p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 13.5px;
  line-height: 1.5;
}
.fx-desk-banner {
  margin: 8px 0 16px;
  padding: 12px 16px;
  border-radius: 12px;
  border: 1px solid var(--accent-soft);
  background: var(--accent-soft);
  color: var(--text-primary);
  font-size: 13.5px;
}
.fx-desk-metrics { margin: 10px 0 6px; }
.fx-desk-viewlabel {
  color: var(--text-tertiary);
  font-size: 11px;
  letter-spacing: .14em;
  text-transform: uppercase;
  font-weight: 600;
  margin: 0 0 14px;
}
.fx-desk-actions { margin: 4px 0 18px; }
.fx-news-card {
  display: grid;
  grid-template-columns: 5px 1fr;
  border: 1px solid var(--border-subtle);
  border-radius: 16px;
  overflow: hidden;
  background: linear-gradient(165deg, var(--surface-1) 0%, var(--surface-2) 100%);
  margin: 0 0 12px;
  box-shadow: 0 14px 40px rgba(0,0,0,.07);
  transition: border-color 160ms ease, transform 160ms ease;
}
.fx-news-card:hover {
  border-color: var(--border-strong);
  transform: translateY(-1px);
}
.fx-news-rail { background: var(--accent); }
.fx-news-rail.exec { background: var(--accent); }
.fx-news-rail.frac { background: var(--warning); }
.fx-news-rail.cap { background: var(--success); }
.fx-news-rail.other { background: var(--border-strong); }
.fx-news-body { padding: 16px 18px 14px; }
.fx-news-top {
  display: flex; align-items: center; justify-content: space-between;
  gap: 10px; margin-bottom: 6px;
}
.fx-news-scorewrap { display: inline-flex; align-items: baseline; gap: 10px; }
.fx-news-rank {
  font-family: "Syne", sans-serif;
  font-size: 11px;
  letter-spacing: 0.08em;
  color: var(--text-tertiary);
  font-weight: 700;
}
.fx-pill {
  display: inline-block;
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 700;
}
.fx-news-score {
  font-family: "Syne", sans-serif;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-tertiary);
  letter-spacing: 0.04em;
}
.fx-news-meta {
  font-size: 10.5px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-tertiary);
  font-weight: 650;
  margin: 0 0 6px;
}
.fx-news-title {
  font-family: "Syne", sans-serif;
  font-size: 1.18rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.28;
  margin: 0 0 10px;
}
.fx-news-title a {
  color: var(--text-primary);
  text-decoration: none;
}
.fx-news-title a:hover { color: var(--accent); }
.fx-news-why {
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.55;
  margin: 0 0 8px;
}
.fx-news-hooks {
  margin: 0;
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--text-tertiary);
}
.fx-eval-row {
  display: flex; align-items: center; gap: 10px;
  margin: 2px 0 14px; min-height: 28px;
}
.fx-eval-spin {
  width: 12px; height: 12px; border-radius: 50%;
  border: 2px solid var(--border-subtle);
  border-top-color: var(--accent);
  animation: fxEvalSpin 0.7s linear infinite;
  flex: 0 0 auto;
}
@keyframes fxEvalSpin { to { transform: rotate(360deg); } }
.fx-eval-busy {
  font-size: 12.5px; color: var(--text-secondary); letter-spacing: 0.02em;
}
.fx-eval-verdict {
  margin: 6px 0 0;
  font-size: 12px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  font-weight: 700;
}
.fx-eval-verdict.ok { color: var(--success); }
.fx-eval-verdict.no { color: var(--warning); }
.fx-desk-empty {
  text-align: center;
  padding: 42px 24px;
  border: 1px dashed var(--border-strong);
  border-radius: 18px;
  background: var(--surface-2);
  margin: 8px 0 20px;
}
.fx-desk-empty h3 {
  font-family: "Syne", sans-serif;
  font-size: 1.35rem;
  margin: 0 0 8px;
  color: var(--text-primary);
}
.fx-desk-empty p {
  margin: 0 auto;
  max-width: 32rem;
  color: var(--text-secondary);
  line-height: 1.55;
}
.fx-desk-invite {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 0 4px;
  margin: 0 0 10px;
  border-bottom: 1px solid var(--border-subtle);
}
.fx-desk-invite p { margin: 0; color: var(--text-secondary); font-size: 13.5px; max-width: 46rem; }
"""


DEFAULT_THEME = "dark"
VALID_THEMES = frozenset({"dark", "light"})


def normalize_theme(value: str | None) -> str:
    mode = (value or "").strip().lower()
    return mode if mode in VALID_THEMES else DEFAULT_THEME


def theme_from_query_value(raw) -> str | None:
    """Parse theme from query param value; None if missing/invalid."""
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    if raw is None:
        return None
    mode = str(raw).strip().lower()
    return mode if mode in VALID_THEMES else None


def inject(theme: str = "light") -> str:
    """Inject CSS for light (editorial mist) or dark (charcoal desk) mode."""
    mode = normalize_theme(theme)
    vars_block = DARK_VARS if mode == "dark" else LIGHT_VARS
    return (
        f"<style>\n"
        f":root {{{vars_block}}}\n"
        f"html, body, .stApp, [data-testid=\"stAppViewContainer\"] {{{vars_block}}}\n"
        f"{SHARED_CSS}\n"
        f"</style>"
    )


# Back-compat: default CSS snapshot is light mode
CSS = inject("light")


def splash_html() -> str:
    """One-shot brand intro — CSS-only, short, token-driven."""
    word = brand_wordmark()
    return f"""
<div class="fx-splash" aria-hidden="true">
  <div style="text-align:center">
    <p class="fx-splash-word">{word}</p>
    <div class="fx-splash-rule"></div>
  </div>
</div>
"""


def topbar_html() -> str:
    word = brand_wordmark()
    return f"""
<div class="fx-top">
  <div class="fx-brand">
    <p class="fx-wordmark">{word}</p>
    <p class="fx-top-sub">Lead intelligence</p>
  </div>
</div>
"""


def shell_actions_hint() -> str:
    """Optional spacer under the shell chrome."""
    return '<div class="fx-shell-hint" aria-hidden="true"></div>'


def composer_header_html() -> str:
    """Premium command-center header for create-search flow."""
    return """
<div class="fx-composer">
  <p class="fx-composer-kicker">New search</p>
  <h2>Launch a brief</h2>
  <p>Name the run, describe the ICP, and fire the research graph. Fetch more anytime from an open search.</p>
</div>
"""


def empty_state_html(title: str, body: str) -> str:
    return (
        f'<div class="fx-empty">'
        f"<h3>{html.escape(title or '')}</h3>"
        f"<p>{html.escape(body or '')}</p>"
        f"</div>"
    )


def results_summary_html(funnel: dict, n_leads: int) -> str:
    """Compact metrics row for review results."""
    funnel = funnel or {}
    metrics = [
        ("Matched", funnel.get("matched") or funnel.get("returned") or n_leads),
        ("Direct", funnel.get("with_people") or 0),
        ("Indirect", funnel.get("channel_only") or 0),
        ("Skipped", funnel.get("skipped_this_run") or funnel.get("skipped_seen") or 0),
    ]
    cells = "".join(
        f'<div class="fx-metric"><div class="n">{html.escape(str(n))}</div>'
        f'<div class="l">{html.escape(label)}</div></div>'
        for label, n in metrics
    )
    return f'<div class="fx-metric-row">{cells}</div>'


def agent_stages_html(active_label: str, stages: list[str] | None = None) -> str:
    """Single-row horizontal stage rail; one strip that callers should replace in-place."""
    default_stages = [
        "Plan",
        "Search",
        "Extract",
        "Score",
        "Enrich",
        "Draft",
    ]
    labels = list(stages) if stages else default_stages
    active = (active_label or "").strip().lower()
    active_idx = -1
    for i, lab in enumerate(labels):
        low = lab.strip().lower()
        if low == active or active in low or low in active:
            active_idx = i
            break
    parts: list[str] = []
    for i, lab in enumerate(labels):
        if active_idx >= 0 and i < active_idx:
            cls = "fx-stage-item done"
        elif active_idx >= 0 and i == active_idx:
            cls = "fx-stage-item active"
        elif active and lab.strip().lower() == active:
            cls = "fx-stage-item active"
        else:
            cls = "fx-stage-item upcoming"
        safe = html.escape(lab)
        parts.append(
            f'<span class="{cls}" title="{safe}">'
            f'<span class="fx-stage-dot" aria-hidden="true"></span>'
            f'<span class="fx-stage-label">{safe}</span>'
            f"</span>"
        )
        if i < len(labels) - 1:
            parts.append('<span class="fx-stage-sep" aria-hidden="true"></span>')
    return (
        f'<div class="fx-stage" role="status" aria-live="polite">'
        f'<div class="fx-stage-track">{"".join(parts)}</div>'
        f"</div>"
    )


def job_dock_header_html(*, stage_label: str, query_hint: str = "", expanded: bool = False) -> str:
    """Compact bar for a running background fetch (expand/collapse via Streamlit buttons)."""
    stage = html.escape((stage_label or "Working").strip() or "Working")
    hint = html.escape((query_hint or "").strip())
    mode = "Expanded" if expanded else "Minimized — click Show progress for details"
    sub = f"{stage}" + (f" · {hint}" if hint else "")
    return (
        '<div class="fx-job-dock">'
        '<div class="fx-job-dock-bar">'
        '<div class="fx-job-dock-left">'
        '<span class="fx-job-pulse" aria-hidden="true"></span>'
        "<div>"
        '<p class="fx-job-dock-title">Fetch running in background</p>'
        f'<p class="fx-job-dock-sub">{html.escape(mode)} · {sub}</p>'
        "</div></div></div></div>"
    )


def key_status(openai_ok: bool, tavily_ok: bool) -> str:
    """Deprecated — kept for import compatibility; renders nothing."""
    return ""


def hero() -> str:
    return """
<div class="fx-hero">
  <h1>Lead Intelligence <em>Agent</em></h1>
  <p>Create a new search, name it, describe who you want — then go. Fetch more anytime on the open search. Manage past searches in Workspace.</p>
</div>
"""


def fetch_bar(
    *,
    run_id: str,
    n_leads: int,
    service_line: str = "",
    csv_name: str = "",
    mode: str = "",
) -> str:
    bits = [f"<strong>{n_leads} companies</strong> in this fetch"]
    if mode:
        bits.insert(0, f"<strong>{html.escape(mode)}</strong>")
    if service_line:
        bits.append(html.escape(service_line))
    if run_id:
        bits.append(f"<code>{html.escape(run_id)}</code>")
    if csv_name:
        bits.append(html.escape(csv_name))
    return f'<div class="fx-bar"><span>{" · ".join(bits)}</span></div>'


def search_mode_html(*, mode: str, detail: str) -> str:
    """Clear New ICP vs same-ICP Fetch more messaging."""
    tone = "new" if mode.lower().startswith("new") else "same"
    return (
        f'<div class="fx-mode {tone}"><strong>{html.escape(mode)}</strong>'
        f"<span>{html.escape(detail)}</span></div>"
    )


def funnel_html(funnel: dict) -> str:
    steps = [
        ("Queries", funnel.get("queries") or 0),
        ("URLs", funnel.get("hits") or 0),
        ("New cos", funnel.get("companies") or 0),
        ("Skipped", funnel.get("skipped_this_run") or funnel.get("skipped_seen") or 0),
        ("Matched", funnel.get("matched") or funnel.get("returned") or funnel.get("queued") or 0),
        ("Direct", funnel.get("with_people") or 0),
        ("Indirect", funnel.get("channel_only") or 0),
    ]
    cells = "".join(
        f'<div class="fx-step"><div class="n">{html.escape(str(n))}</div>'
        f'<div class="l">{html.escape(label)}</div></div>'
        for label, n in steps
    )
    return f'<div class="fx-funnel">{cells}</div>'


def _conf_class(conf: str) -> str:
    c = (conf or "").upper()
    if c == "HIGH":
        return "high"
    if c == "MEDIUM":
        return "med"
    if c == "UNVERIFIED":
        return "unver"
    return "low"


def _trust_badge(conf: str) -> str:
    """Human-readable trust chip with visual hierarchy."""
    c = (conf or "").upper()
    if c == "HIGH":
        return '<span class="badge high trust-high">Verified</span>'
    if c == "MEDIUM":
        return '<span class="badge med trust-med">Medium</span>'
    if c == "UNVERIFIED":
        return '<span class="badge unver trust-low">Needs review</span>'
    return f'<span class="badge low trust-low">{_esc(conf or "Unknown")}</span>'


def _esc(text: str) -> str:
    return html.escape(text or "")


def _link(url: str, label: str | None = None) -> str:
    if not url:
        return "—"
    lab = html.escape(label or re.sub(r"^https?://(www\.)?", "", url).rstrip("/"))
    return f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{lab}</a>'


def queue_label(lead: dict) -> str:
    """One-line picker label: score, company, person/channel, confidence."""
    score = (lead.get("score") or {}).get("total") or 0
    name = lead.get("name") or "—"
    section = lead.get("result_section") or ""
    contact = lead.get("contact") or {}
    person = contact.get("name") or "no contact"
    if person in {"not_found", "unknown"}:
        person = (contact.get("role") or "no contact")
    if section == "approach_channels":
        ch = lead.get("best_approach_channel") or ""
        person = ch.split(":", 1)[-1] if ch else "company channel"
    elif section == "unresolved":
        person = "needs enrichment"
    conf = (lead.get("signal") or {}).get("confidence") or ""
    status = lead.get("review_status") or "pending"
    return f"{int(score):02d}  {name}  ·  {person}  ·  {conf}  ·  {status}"


def lead_card(lead: dict, active: bool = False) -> str:
    """Kept for callers; queue list now uses queue_label."""
    return detail_html(lead) if active else ""


def _score_bars(score: dict) -> str:
    parts = [
        ("ICP", score.get("icp_fit") or 0, 30),
        ("Signal", score.get("signal_strength") or 0, 25),
        ("Recency", score.get("recency") or 0, 15),
        ("Approach", score.get("approach_quality") or score.get("contact_relevance") or 0, 20),
        ("Evidence", score.get("evidence_depth") or 0, 10),
    ]
    rows = []
    for label, val, cap in parts:
        pct = min(100, int(100 * float(val) / cap)) if cap else 0
        rows.append(
            f'<div class="fx-barline"><span>{_esc(label)}</span>'
            f'<div class="fx-track"><div class="fx-fill" style="width:{pct}%"></div></div>'
            f"<b>{int(val)}</b></div>"
        )
    return f'<div class="fx-bars">{"".join(rows)}</div>'


def _channels_line(person: dict) -> str:
    bits = []
    if person.get("email"):
        bits.append(f'<a href="mailto:{html.escape(person["email"])}">{_esc(person["email"])}</a>')
    if person.get("phone"):
        bits.append(_esc(person["phone"]))
    if person.get("linkedin_url"):
        bits.append(_link(person["linkedin_url"], "LinkedIn"))
    if person.get("twitter_url"):
        bits.append(_link(person["twitter_url"], "X"))
    extra = person.get("other_social") or []
    for u in extra[:2]:
        bits.append(_link(u))
    return " · ".join(bits) if bits else '<span class="fx-muted">No public channel yet</span>'


def _people_html(lead: dict, *, omit_drafts: bool = False) -> str:
    """All people for this company with channels (+ optional outreach drafts)."""
    section = lead.get("result_section") or ""
    people = [
        p
        for p in (lead.get("verified_contacts") or lead.get("contacts") or [])
        if (p.get("name") or "").lower() not in {"", "unknown", "not_found"}
    ]
    if not people:
        c = lead.get("contact") or {}
        if (c.get("name") or "").lower() not in {"", "unknown", "not_found"}:
            people = [c]

    if section == "approach_channels" and not people:
        if omit_drafts:
            return (
                '<p class="fx-muted">No verified decision-maker for this ICP. '
                "See <b>Best approaching channel</b> below — edit outreach messages in the section under this dossier.</p>"
            )
        mail = (lead.get("email_draft") or "").strip()
        li = (lead.get("linkedin_note") or "").strip()
        drafts = ""
        if mail or li:
            drafts = (
                f'<p class="fx-mail-label" style="margin-top:12px">Outreach message (reusable)</p>'
                f'<div class="fx-person-mail">{_esc(mail) if mail else "Pending"}</div>'
                f'<p class="fx-mail-label" style="margin-top:12px">LinkedIn note</p>'
                f'<div class="fx-person-mail">{_esc(li) if li else "Pending"}</div>'
            )
        return (
            '<p class="fx-muted">No verified decision-maker for this ICP. '
            "See <b>Best approaching channel</b> below and the Indirect contacts tab.</p>"
            + drafts
        )

    if not people:
        return '<p class="fx-muted">No named public contact yet — check Indirect contacts for company channels.</p>'

    blocks = []
    for c in people[:6]:
        primary = bool(c.get("is_primary"))
        rank = c.get("rank") or ""
        verified = bool(c.get("person_verified") or section == "verified_people")
        tag = "Primary" if primary else (f"#{rank}" if rank else "Contact")
        if verified:
            tag = f"{tag} · verified"
        cls = "fx-person primary" if primary else "fx-person"
        conf = _esc(c.get("confidence") or "")
        pname = c.get("name") or "not_found"
        name = _esc(pname)
        role = _esc(c.get("role") or "")
        why = _esc(c.get("why") or c.get("likelihood_reason") or "")
        src = c.get("source_url") or ""
        why_html = f'<p class="fx-why">{why}</p>' if why else ""
        src_html = f'<p class="fx-why">Source: {_link(src)}</p>' if src else ""
        drafts_html = ""
        if not omit_drafts:
            mail = (c.get("email_draft") or "").strip()
            li_note = (c.get("linkedin_note") or "").strip()
            if primary:
                if not mail:
                    mail = (lead.get("email_draft") or "").strip()
                if not li_note:
                    li_note = (lead.get("linkedin_note") or "").strip()
            draft_parts = []
            if mail:
                draft_parts.append(
                    f'<p class="fx-mail-label" style="margin-top:12px">Outreach message for {name}</p>'
                    f'<p class="fx-why" style="margin:0 0 6px">Reusable — email, LinkedIn InMail, or message</p>'
                    f'<div class="fx-person-mail">{_esc(mail)}</div>'
                )
            if li_note:
                draft_parts.append(
                    f'<p class="fx-mail-label" style="margin-top:12px">LinkedIn note for {name}</p>'
                    f'<div class="fx-person-mail">{_esc(li_note)}</div>'
                )
            if not draft_parts and not lead.get("_selected_messages"):
                draft_parts.append(
                    f'<p class="fx-mail-label" style="margin-top:12px">Outreach message for {name}</p>'
                    f'<div class="fx-person-mail">Outreach message pending — re-run search.</div>'
                    f'<p class="fx-mail-label" style="margin-top:12px">LinkedIn note for {name}</p>'
                    f'<div class="fx-person-mail">LinkedIn note pending — re-run search.</div>'
                )
            drafts_html = "".join(draft_parts)
        blocks.append(
            f'<div class="{cls}">'
            f'<div class="fx-person-top"><strong>{name}</strong><em>{_esc(tag)} · {conf}</em></div>'
            f'<div class="role">{role}</div>'
            f'<div class="fx-chans">{_channels_line(c)}</div>'
            f"{why_html}{src_html}{drafts_html}"
            f"</div>"
        )
    return "".join(blocks)


def _approach_channels_html(lead: dict) -> str:
    channels = lead.get("approach_channels") or []
    if not channels:
        best = lead.get("best_approach_channel") or ""
        if not best:
            return ""
        return f'<p class="fx-copy">{_esc(best)}</p>'
    blocks = []
    for ch in channels[:6]:
        kind = _esc(ch.get("kind") or "")
        label = _esc(ch.get("label") or kind)
        value = ch.get("value") or ""
        src = ch.get("source_url") or ""
        if (ch.get("kind") or "") == "email":
            val_html = f'<a href="mailto:{html.escape(value)}">{_esc(value)}</a>'
        elif value.startswith("http"):
            val_html = _link(value)
        else:
            val_html = _esc(value)
        src_html = f' · source {_link(src)}' if src else ""
        blocks.append(
            f'<div class="fx-person"><div class="fx-person-top"><strong>{label}</strong>'
            f"<em>{kind}</em></div><div class=\"fx-chans\">{val_html}{src_html}</div></div>"
        )
    return "".join(blocks)


def detail_html(lead: dict, *, selected_only: bool = False, omit_drafts: bool = False) -> str:
    score = lead.get("score") or {}
    signal = lead.get("signal") or {}
    contact = lead.get("contact") or {}
    website = lead.get("website") or ""
    industry = lead.get("industry") or "unknown"
    city = lead.get("city") or ""
    country = lead.get("country") or ""
    loc = ", ".join(x for x in [city, country] if x and x != "unknown")
    stage = lead.get("funding_stage") or ""
    conf = signal.get("confidence") or "UNVERIFIED"
    status = lead.get("review_status") or "pending"
    outreach = lead.get("outreach_status") or ""
    sig_type = (signal.get("type") or "").replace("_", " ")
    section = lead.get("result_section") or ""
    person_name = contact.get("name") or "not_found"
    person_role = contact.get("role") or ""
    if section == "approach_channels":
        person_name = "Company channel"
        person_role = lead.get("best_approach_channel") or "No verified decision-maker"
    elif section == "unresolved":
        person_name = "Needs enrichment"
        person_role = "No verified person or company channel yet"

    meta_bits = [industry]
    if loc:
        meta_bits.append(loc)
    if stage and stage != "unknown":
        meta_bits.append(stage.replace("_", " "))
    if website and website not in {"not_found", "unknown"}:
        meta_bits.append(_link(website))
    meta = " · ".join(meta_bits)

    chips = [
        _trust_badge(conf),
        f'<span class="badge {_conf_class(conf)}">{_esc(conf)}</span>',
        f'<span class="badge pending">{_esc(status)}</span>',
    ]
    if section == "verified_people":
        chips.append('<span class="badge high">Direct contact</span>')
    elif section == "approach_channels":
        chips.append('<span class="badge med">Indirect contact</span>')
    elif section == "unresolved":
        chips.append('<span class="badge low">Needs enrichment</span>')
    if outreach:
        chips.append(f'<span class="badge">{_esc(outreach)}</span>')
    if sig_type:
        chips.append(f'<span class="badge">{_esc(sig_type)}</span>')
    if selected_only:
        chips.append('<span class="badge high">Selected messages only</span>')

    signal_body = _esc(signal.get("summary") or "No verified signal.")
    evidence = signal.get("evidence_quote") or ""
    sources = signal.get("sources") or []
    src_html = "".join(
        f'<div class="fx-src">{_link(s.get("url") or "", s.get("title") or s.get("url"))}'
        f' · {_esc(s.get("date") or "date unknown")}</div>'
        for s in sources[:4]
    )

    why_int = (lead.get("why_interested") or "").strip()
    why_score = (score.get("why") or "").strip()
    reasons = score.get("reasons") or []
    reason_html = "".join(
        f'<p class="fx-muted" style="margin:4px 0 0">{_esc(r)}</p>' for r in reasons[:4]
    )

    proofs = lead.get("proofs") or []
    proof_parts = []
    for p in proofs:
        tier = (p.get("match_tier") or "direct").strip().lower()
        if tier not in {"direct", "related"}:
            tier = "related" if (p.get("usage_hint") or "").strip() else "direct"
        tier_label = "Related suggestion" if tier == "related" else "Direct match"
        hint = (p.get("usage_hint") or "").strip()
        related_cls = " related" if tier == "related" else ""
        hint_html = f'<p class="fx-proof-hint">{_esc(hint)}</p>' if hint else ""
        proof_parts.append(
            f'<div class="fx-proof{related_cls}">'
            f'<b>{_esc(p.get("company"))}</b>'
            f' — {_esc(", ".join(p.get("roles_placed") or []))}'
            f'<span class="fx-proof-tier{related_cls}">'
            f"{_esc(tier_label)}</span>"
            f'<p>{_esc(p.get("outcome") or "")}</p>'
            f'<p class="fx-muted">{_esc(p.get("why_matched") or "")}</p>'
            f"{hint_html}"
            f"</div>"
        )
    proof_html = "".join(proof_parts) or '<p class="fx-muted">No proof-point match.</p>'

    flags = lead.get("qa_flags") or []
    uncertainty = lead.get("field_uncertainty") or []
    flag_html = (
        "".join(f'<p class="fx-flag">{_esc(f)}</p>' for f in flags)
        or '<p class="fx-flag ok">No QA flags.</p>'
    )
    unc_html = (
        "".join(f'<p class="fx-flag">{_esc(u)}</p>' for u in uncertainty)
        or '<p class="fx-flag ok">None flagged.</p>'
    )

    found_via = lead.get("discovery_web_query") or ""
    people_title = (
        "Selected outreach (email + LinkedIn)"
        if selected_only
        else (
            "People & contacts"
            if omit_drafts
            else "People & contacts (channels + outreach message + LinkedIn note each)"
        )
    )
    approach_block = _approach_channels_html(lead)
    approach_sec = ""
    if approach_block or section == "approach_channels":
        approach_sec = f"""
  <div class="fx-sec">
    <h3>Best approaching channel</h3>
    <p class="fx-muted">Company-level contact when a verified decision-maker was not found.</p>
    {approach_block or '<p class="fx-muted">No company approach channel sourced.</p>'}
  </div>"""

    return f"""
<div class="fx-detail">
  <div class="fx-dh">
    <div>
      <h2>{_esc(lead.get("name") or "")}</h2>
      <p class="fx-dh-meta">{meta}</p>
    </div>
    <div class="fx-scorebox"><div class="n">{int(score.get("total") or 0)}</div><div class="l">score</div></div>
  </div>
  <div class="fx-chips">{"".join(chips)}</div>
  <div class="fx-grid">
    <div class="fx-tile">
      <p class="k">Signal</p>
      <h4>{_esc(sig_type or "Unspecified")}</h4>
      <p>{signal_body}</p>
    </div>
    <div class="fx-tile">
      <p class="k">Approach</p>
      <h4>{_esc(person_name)}</h4>
      <p>{_esc(person_role)}</p>
      <p style="margin-top:8px">{_channels_line(contact) if section == "verified_people" else (_approach_channels_html(lead) or _channels_line(contact))}</p>
    </div>
    <div class="fx-tile">
      <p class="k">Why this score</p>
      {_score_bars(score)}
    </div>
  </div>
  <div class="fx-sec">
    <h3>Why they may want {brand_name()}</h3>
    <p class="fx-copy">{_esc(why_int) if why_int else "Interest brief not generated — signal may be too weak."}</p>
    {f'<p class="fx-muted" style="margin-top:8px">{_esc(why_score)}</p>' if why_score else ""}
    {reason_html}
  </div>
  <div class="fx-sec">
    <h3>Evidence</h3>
    {f'<p class="fx-copy">“{_esc(evidence)}”</p>' if evidence else '<p class="fx-muted">No quote captured.</p>'}
    <div style="margin-top:10px">{src_html or '<p class="fx-muted">No sources.</p>'}</div>
    {f'<p class="fx-muted" style="margin-top:8px">Found via: {_esc(found_via)}</p>' if found_via else ""}
  </div>
  <div class="fx-sec">
    <h3>{people_title}</h3>
    {_people_html(lead, omit_drafts=omit_drafts and not selected_only)}
  </div>
  {approach_sec}
  <div class="fx-sec">
    <h3>{brand_name()} proof</h3>
    {proof_html}
  </div>
  <div class="fx-sec">
    <h3>Checks</h3>
    {flag_html}
    <p class="fx-muted" style="margin-top:8px">Uncertainty</p>
    {unc_html}
  </div>
</div>
"""
