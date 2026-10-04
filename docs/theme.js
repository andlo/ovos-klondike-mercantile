// Light/dark theme. Follows the system setting until the visitor picks
// one with the button; the choice is kept in localStorage. Loaded in
// <head> so the theme is set before the page paints (no light flash).
(function () {
  const KEY = "klondike_theme";
  const MODES = ["auto", "light", "dark"];
  const ICON = { auto: "🌓", light: "☀️", dark: "🌙" };
  const LABEL = { auto: "Theme: follows your system", light: "Theme: light", dark: "Theme: dark" };

  function load() {
    try { return localStorage.getItem(KEY) || "auto"; } catch { return "auto"; }
  }
  function save(mode) {
    try { localStorage.setItem(KEY, mode); } catch { /* private mode: works for this page only */ }
  }
  function apply(mode) {
    if (mode === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", mode);
  }

  let mode = load();
  if (!MODES.includes(mode)) mode = "auto";
  apply(mode);

  function addButton() {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "theme-toggle";
    const show = () => {
      btn.textContent = ICON[mode];
      btn.title = LABEL[mode] + " (click to change)";
      btn.setAttribute("aria-label", LABEL[mode]);
    };
    btn.addEventListener("click", () => {
      mode = MODES[(MODES.indexOf(mode) + 1) % MODES.length];
      save(mode);
      apply(mode);
      show();
    });
    show();
    document.body.appendChild(btn);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", addButton);
  else addButton();
})();
