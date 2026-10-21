/**
 * Tiny text-only PDF writer used ONLY for the Phase 1 demo download.
 * Every page carries a "DEMO – NOT A VERIFIED REPORT" watermark. Real PDFs
 * will be produced by the Python backend (see report-service.ts).
 */

export interface PdfLine {
  text: string;
  size?: number;
  bold?: boolean;
  gap?: number;
  color?: [number, number, number];
}

const PAGE_W = 595;
const PAGE_H = 842;
const MARGIN = 48;

/** PDF base fonts use WinAnsi; map common Unicode punctuation to ASCII. */
function sanitize(s: string): string {
  return s
    .replace(/[–—]/g, "-")
    .replace(/[≥]/g, ">=")
    .replace(/[≤]/g, "<=")
    .replace(/[·•]/g, "|")
    .replace(/[“”]/g, '"')
    .replace(/[‘’]/g, "'")
    .replace(/[−]/g, "-")
    .replace(/±/g, "+/-")
    .replace(/[^\x20-\x7e]/g, "?")
    .replace(/\\/g, "\\\\")
    .replace(/\(/g, "\\(")
    .replace(/\)/g, "\\)");
}

function wrap(text: string, size: number): string[] {
  const maxChars = Math.floor((PAGE_W - MARGIN * 2) / (size * 0.5));
  const words = text.split(" ");
  const out: string[] = [];
  let line = "";
  for (const w of words) {
    if ((line + " " + w).trim().length > maxChars) {
      out.push(line);
      line = w;
    } else line = (line + " " + w).trim();
  }
  if (line) out.push(line);
  return out.length ? out : [""];
}

export function buildPdf(lines: PdfLine[], footer: string): Blob {
  const pages: string[] = [];
  let ops: string[] = [];
  let y = PAGE_H - MARGIN;

  const watermark = () =>
    `q 0.85 0.85 0.85 rg BT /F2 46 Tf 0.7071 0.7071 -0.7071 0.7071 120 210 Tm (${sanitize("DEMO - NOT A VERIFIED REPORT")}) Tj ET Q`;
  const footerOps = (n: number) =>
    `BT /F1 8 Tf 0.45 0.45 0.45 rg ${MARGIN} 28 Td (${sanitize(`${footer}  |  Page ${n}`)}) Tj ET`;

  const newPage = () => {
    if (ops.length) {
      pages.push([watermark(), ...ops, footerOps(pages.length + 1)].join("\n"));
    }
    ops = [];
    y = PAGE_H - MARGIN;
  };

  for (const l of lines) {
    const size = l.size ?? 10;
    const lead = size * 1.45;
    y -= l.gap ?? 0;
    for (const chunk of wrap(l.text, size)) {
      if (y - lead < MARGIN + 20) newPage();
      y -= lead;
      const [r, g, b] = l.color ?? [0.1, 0.12, 0.16];
      ops.push(`BT /${l.bold ? "F2" : "F1"} ${size} Tf ${r} ${g} ${b} rg ${MARGIN} ${y.toFixed(1)} Td (${sanitize(chunk)}) Tj ET`);
    }
  }
  newPage();

  // Assemble objects: 1 catalog, 2 pages, 3 font, 4 bold font, then page+content pairs.
  const objects: string[] = [];
  const pageIds: number[] = [];
  objects[1] = "<< /Type /Catalog /Pages 2 0 R >>";
  objects[3] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>";
  objects[4] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>";
  let next = 5;
  for (const content of pages) {
    const pageId = next++;
    const contentId = next++;
    pageIds.push(pageId);
    objects[pageId] = `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${PAGE_W} ${PAGE_H}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents ${contentId} 0 R >>`;
    objects[contentId] = `<< /Length ${content.length} >>\nstream\n${content}\nendstream`;
  }
  objects[2] = `<< /Type /Pages /Kids [${pageIds.map((id) => `${id} 0 R`).join(" ")}] /Count ${pageIds.length} >>`;

  let pdf = "%PDF-1.4\n";
  const offsets: number[] = [];
  for (let i = 1; i < objects.length; i++) {
    offsets[i] = pdf.length;
    pdf += `${i} 0 obj\n${objects[i]}\nendobj\n`;
  }
  const xref = pdf.length;
  pdf += `xref\n0 ${objects.length}\n0000000000 65535 f \n`;
  for (let i = 1; i < objects.length; i++) pdf += `${String(offsets[i]).padStart(10, "0")} 00000 n \n`;
  pdf += `trailer\n<< /Size ${objects.length} /Root 1 0 R /Info << /Title (${sanitize("DEMO weekly report")}) >> >>\nstartxref\n${xref}\n%%EOF`;
  return new Blob([pdf], { type: "application/pdf" });
}
