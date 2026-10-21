import { Logo } from "./logo";
import { InlineScript } from "./inline-script";
import { SplashController } from "./splash-controller";

export const SPLASH_KEY = "pratap-splash-seen";

/**
 * App splash shown once per browser session. The inline script runs before
 * first paint: if the splash was already seen this session it is hidden
 * immediately, so later reloads never flash it.
 */
export function Preloader() {
  return (
    <>
      <InlineScript
        html={`try{if(sessionStorage.getItem('${SPLASH_KEY}'))document.documentElement.dataset.splash='done'}catch(e){document.documentElement.dataset.splash='done'}`}
      />
      <div className="splash" role="status" aria-live="polite" aria-label="Loading Pratap network analytics">
        <div className="flex flex-col items-center gap-5">
          <div className="splash-logo">
            <Logo variant="wordmark" width={200} eager />
          </div>
          <div className="fibre-track" aria-hidden />
          <p className="splash-tagline text-sm font-medium tracking-wide text-muted-foreground">Carving Lives</p>
        </div>
      </div>
      <SplashController storageKey={SPLASH_KEY} />
    </>
  );
}
