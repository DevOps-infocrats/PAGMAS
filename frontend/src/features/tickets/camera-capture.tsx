"use client";

import { Camera, Check, Loader2, MapPin, RefreshCw, RotateCcw, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/overlays";
import type { CameraGeo, GeoFile } from "@/lib/api";

/** A location older than this is not used for a photo (the device may have moved). */
const FRESH_MS = 2 * 60 * 1000;

function cameraError(e: unknown): string {
  const name = e instanceof DOMException ? e.name : "";
  if (name === "NotAllowedError" || name === "SecurityError")
    return "Camera permission was denied. Allow the camera for this site in the browser settings (the lock / camera icon in the address bar), then press Try again.";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "No camera was found on this device.";
  if (name === "NotReadableError" || name === "AbortError") return "The camera is busy in another app. Close that app and press Try again.";
  return "The camera could not be started. Press Try again, or use “Open phone camera”.";
}

function locationError(e: GeolocationPositionError): string {
  if (e.code === e.PERMISSION_DENIED)
    return "Location permission was denied. Allow location for this site in the browser settings and turn on the device's location (GPS), then press Retry location.";
  if (e.code === e.TIMEOUT) return "The location took too long. Go to an open area with GPS on and press Retry location.";
  return "The location is not available. Turn on the device's location (GPS) and press Retry location.";
}

const stampTime = (d: Date) => d.toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });

/** Draws the image with a stamp (GP, latitude / longitude, accuracy, date and time) and returns the JPEG photo. */
async function stamped(src: CanvasImageSource, w: number, h: number, geo: CameraGeo, label: string): Promise<Blob> {
  const max = 1920;
  const k = Math.min(1, max / Math.max(w, h));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(w * k);
  canvas.height = Math.round(h * k);
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("This browser cannot process the photo");
  ctx.drawImage(src, 0, 0, canvas.width, canvas.height);
  const size = Math.max(14, Math.round(canvas.width / 45));
  const lines = [
    label,
    `Lat ${geo.lat.toFixed(6)}, Lng ${geo.lng.toFixed(6)}${geo.accuracy != null ? ` (±${Math.round(geo.accuracy)} m)` : ""}`,
    stampTime(new Date(geo.capturedAt)),
  ];
  const pad = Math.round(size * 0.6);
  const boxH = lines.length * size * 1.35 + pad;
  ctx.fillStyle = "rgba(0,0,0,0.55)";
  ctx.fillRect(0, canvas.height - boxH, canvas.width, boxH);
  ctx.fillStyle = "#fff";
  ctx.font = `600 ${size}px system-ui, sans-serif`;
  lines.forEach((t, i) => ctx.fillText(t, pad, canvas.height - boxH + pad / 2 + size * (i + 1) * 1.25));
  return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("The photo could not be saved"))), "image/jpeg", 0.85));
}

/**
 * Live photo for the FRT's Daily Achievement: the device camera (rear camera on a phone) and the current location.
 * The photo is taken only with a fresh location; it is stamped with the GP, latitude / longitude and the time, shown for
 * preview / retake, and handed back as a JPEG carrying its location / time (sent with the submission as proofMeta –
 * the backend requires it from the FRT). Camera and location need https (or localhost); without camera access the
 * phone's own camera app can be used instead (location still required).
 */
export function CameraCapture({ open, gpCode, gpName, onClose, onCapture }: { open: boolean; gpCode: string; gpName?: string; onClose: () => void; onCapture: (file: GeoFile) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const watch = useRef<number | null>(null);
  const native = useRef<HTMLInputElement>(null);
  const [camState, setCamState] = useState<"starting" | "live" | "error">("starting");
  const [camErr, setCamErr] = useState<string | null>(null);
  const [pos, setPos] = useState<GeolocationPosition | null>(null);
  const [locErr, setLocErr] = useState<string | null>(null);
  const [shot, setShot] = useState<{ url: string; file: GeoFile } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now()); // re-checked every few seconds: is the location still fresh?
  const secure = typeof window === "undefined" || window.isSecureContext;

  const stopCamera = () => {
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
  };
  const stopLocation = () => {
    if (watch.current != null) navigator.geolocation?.clearWatch(watch.current);
    watch.current = null;
  };

  const startLocation = useCallback(() => {
    stopLocation();
    setLocErr(null);
    if (!secure) return setLocErr("Location needs a secure (https) connection – open the portal with https://.");
    if (!("geolocation" in navigator)) return setLocErr("This browser cannot read the location.");
    watch.current = navigator.geolocation.watchPosition(
      (p) => {
        setPos(p);
        setNowMs(Date.now());
        setLocErr(null);
      },
      (e) => setLocErr(locationError(e)),
      { enableHighAccuracy: true, timeout: 20_000, maximumAge: 0 },
    );
  }, [secure]);

  const startCamera = useCallback(async () => {
    stopCamera();
    setCamErr(null);
    setCamState("starting");
    if (!secure || !navigator.mediaDevices?.getUserMedia) {
      setCamState("error");
      return setCamErr(secure ? "This browser cannot open the camera here – use “Open phone camera”." : "The camera needs a secure (https) connection – open the portal with https://, or use “Open phone camera”.");
    }
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false });
      stream.current = s;
      if (video.current) {
        video.current.srcObject = s;
        await video.current.play().catch(() => undefined);
      }
      setCamState("live");
    } catch (e) {
      setCamState("error");
      setCamErr(cameraError(e));
    }
  }, [secure]);

  useEffect(() => {
    if (!open) return;
    // start both when the dialog opens; stop them when it closes (no camera / GPS left running)
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void startCamera();
    startLocation();
    return () => {
      stopCamera();
      stopLocation();
    };
  }, [open, startCamera, startLocation]);

  useEffect(() => () => {
    if (shot) URL.revokeObjectURL(shot.url);
  }, [shot]);

  useEffect(() => {
    if (!open) return;
    const id = window.setInterval(() => setNowMs(Date.now()), 5000);
    return () => window.clearInterval(id);
  }, [open]);

  const fresh = !!pos && nowMs - pos.timestamp < FRESH_MS;
  const geoNow = (): CameraGeo | null =>
    pos && Date.now() - pos.timestamp < FRESH_MS ? { lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: pos.coords.accuracy ?? null, capturedAt: new Date().toISOString() } : null;

  const finish = async (src: CanvasImageSource, w: number, h: number) => {
    const geo = geoNow();
    if (!geo) return setErr("Waiting for the location – the photo is taken with the current latitude / longitude.");
    setBusy(true);
    setErr(null);
    try {
      const blob = await stamped(src, w, h, geo, `GP ${gpCode}${gpName ? ` – ${gpName}` : ""}`);
      const file = new File([blob], `camera-${gpCode}-${geo.capturedAt.replace(/[^0-9]/g, "").slice(0, 14)}.jpg`, { type: "image/jpeg" }) as GeoFile;
      file.geo = geo;
      setShot({ url: URL.createObjectURL(blob), file });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The photo could not be taken");
    } finally {
      setBusy(false);
    }
  };

  const capture = () => {
    const v = video.current;
    if (!v || !v.videoWidth) return setErr("The camera is not ready yet.");
    void finish(v, v.videoWidth, v.videoHeight);
  };

  const fromNative = async (f: File | undefined) => {
    if (!f) return;
    if (!/^image\/(jpeg|png)$/i.test(f.type)) return setErr("Take a JPG / PNG photo.");
    try {
      const bmp = await createImageBitmap(f);
      await finish(bmp, bmp.width, bmp.height);
    } catch {
      setErr("The photo could not be read – take it again.");
    }
  };

  const close = () => {
    setShot(null);
    setErr(null);
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && !busy && close()}>
      <DialogContent className="top-[3vh] max-h-[94dvh] max-w-xl">
        <div className="space-y-3 p-4 sm:p-5">
          <div className="pr-8">
            <DialogTitle className="text-base font-bold sm:text-lg">Camera – GP {gpCode}</DialogTitle>
            <DialogDescription className="mt-0.5 text-[0.8125rem] text-muted-foreground">
              Take a live photo of the work. Its location (latitude / longitude), date and time are saved with it.
            </DialogDescription>
          </div>

          {/* live camera / preview */}
          <div className="relative overflow-hidden rounded-lg bg-black">
            {shot ? (
              // eslint-disable-next-line @next/next/no-img-element -- a local preview (blob:) of the photo just taken
              <img src={shot.url} alt={`Photo of GP ${gpCode}`} className="mx-auto max-h-[55dvh] w-full object-contain" />
            ) : (
              <video ref={video} playsInline muted autoPlay className={camState === "live" ? "mx-auto max-h-[55dvh] w-full object-contain" : "hidden"} />
            )}
            {!shot && camState === "starting" && (
              <p className="flex h-48 items-center justify-center gap-2 text-sm text-white/80">
                <Loader2 className="size-4 animate-spin" /> Starting the camera…
              </p>
            )}
            {!shot && camState === "error" && (
              <div className="flex min-h-48 flex-col items-center justify-center gap-2 p-4 text-center text-sm text-white">
                <TriangleAlert className="size-6 text-warning" aria-hidden />
                <p role="alert">{camErr}</p>
                <div className="flex flex-wrap justify-center gap-2">
                  <Button size="sm" variant="outline" className="bg-white/10 text-white hover:bg-white/20" onClick={() => void startCamera()}>
                    <RefreshCw /> Try again
                  </Button>
                  <Button size="sm" variant="primary" onClick={() => native.current?.click()}>
                    <Camera /> Open phone camera
                  </Button>
                </div>
              </div>
            )}
          </div>
          <input ref={native} type="file" accept="image/jpeg,image/png" capture="environment" className="sr-only" onChange={(e) => { void fromNative(e.target.files?.[0]); e.target.value = ""; }} aria-label="Take a photo with the phone camera" />

          {/* location */}
          <div className={`flex flex-wrap items-center gap-2 rounded-md px-3 py-2 text-[0.8125rem] ${locErr ? "bg-critical-soft text-critical-text" : fresh ? "bg-good-soft text-good-text" : "bg-warning-soft text-warning-text"}`}>
            <MapPin className="size-4 shrink-0" aria-hidden />
            {locErr ? (
              <span role="alert" className="min-w-0 flex-1">{locErr}</span>
            ) : fresh && pos ? (
              <span className="min-w-0 flex-1">
                Lat <b>{pos.coords.latitude.toFixed(6)}</b>, Lng <b>{pos.coords.longitude.toFixed(6)}</b>
                {pos.coords.accuracy != null && <> · ±{Math.round(pos.coords.accuracy)} m</>}
              </span>
            ) : (
              <span className="flex min-w-0 flex-1 items-center gap-1.5">
                <Loader2 className="size-3.5 animate-spin" /> Getting the location…
              </span>
            )}
            {(locErr || !fresh) && (
              <button type="button" onClick={startLocation} className="rounded px-1.5 py-0.5 font-semibold underline-offset-2 hover:underline">
                Retry location
              </button>
            )}
          </div>
          {shot?.file.geo && (
            <p className="text-[0.75rem] text-muted-foreground">
              Taken {stampTime(new Date(shot.file.geo.capturedAt))} at {shot.file.geo.lat.toFixed(6)}, {shot.file.geo.lng.toFixed(6)}
            </p>
          )}
          {err && (
            <p role="alert" className="rounded-md border border-critical/30 bg-critical-soft px-3 py-2 text-sm text-critical-text">
              {err}
            </p>
          )}

          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="outline" onClick={close} disabled={busy}>
              Cancel
            </Button>
            {shot ? (
              <>
                <Button variant="outline" onClick={() => setShot(null)} disabled={busy}>
                  <RotateCcw /> Retake
                </Button>
                <Button
                  variant="primary"
                  onClick={() => {
                    onCapture(shot.file);
                    setShot(null);
                    onClose();
                  }}
                >
                  <Check /> Use photo
                </Button>
              </>
            ) : (
              <Button variant="primary" onClick={capture} disabled={busy || camState !== "live" || !fresh} title={!fresh ? "Waiting for the location" : undefined}>
                {busy ? <Loader2 className="animate-spin" /> : <Camera />} Capture
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
