// micu-ai-lib · 亮 / 暗主题切换
const THEME_KEY = "micu-ai-lib-theme-v2";
const LIGHT = "micu";
const DARK = "dark";

function applyTheme(theme) {
  const t = theme === DARK ? DARK : LIGHT;
  document.documentElement.setAttribute("data-theme", t);
  const icon = document.getElementById("theme-toggle-icon");
  const label = document.getElementById("theme-toggle-label");
  if (icon) icon.textContent = t === DARK ? "○" : "◐";
  if (label) label.textContent = t === DARK ? "LIGHT" : "DARK";
  try { localStorage.setItem(THEME_KEY, t); } catch {}
}

function currentTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === LIGHT || saved === DARK) return saved;
  } catch {}
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? DARK : LIGHT;
}

function init() {
  applyTheme(currentTheme());
  document.getElementById("theme-toggle")?.addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === DARK ? LIGHT : DARK;
    applyTheme(next);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
