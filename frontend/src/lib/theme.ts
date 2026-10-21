export type ThemePreference = "light" | "dark" | "system";
export const THEME_STORAGE_KEY = "pratap-theme";

/** Runs before first paint (see app/layout.tsx) so there is no theme flash. */
export const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem('${THEME_STORAGE_KEY}')||'light';var d=t==='dark'||(t==='system'&&matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.classList.toggle('dark',d);}catch(e){}})();`;
