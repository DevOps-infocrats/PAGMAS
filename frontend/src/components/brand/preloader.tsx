import { Logo } from "./logo";
import { SplashController } from "./splash-controller";

/**
 * App splash shown on every full page load (first visit, refresh, opening a link in a new tab).
 * In-app navigation keeps the root layout mounted, so it never re-appears while moving between pages.
 */
export function Preloader() {
  return (
    <>
      <div className="splash" role="status" aria-live="polite" aria-label="Loading Pratap network analytics">
        <div className="splash-glow" aria-hidden />
        <div className="splash-inner">
          <div className="splash-orb" aria-hidden>
            <span className="splash-ring-track" />
            <span className="splash-ring" />
            <span className="splash-mark">
              <Logo variant="mark" width={52} eager />
            </span>
          </div>
          <div className="splash-word">
            <Logo variant="wordmark" width={168} eager />
          </div>
          <div className="fibre-track" aria-hidden />
          <p className="splash-tagline mt-4 text-[12px] font-semibold uppercase tracking-[0.28em] text-[#9fb6c4]">Carving Lives · Network Analytics</p>
        </div>
      </div>
      <SplashController />
    </>
  );
}
