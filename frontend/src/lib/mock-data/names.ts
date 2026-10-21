import type { Random } from "./random";

/**
 * Synthetic place-name fragments. Generated district/block/GP names are
 * fictional and only used for DEMO DATA.
 */
const PREFIXES = [
  "Ram", "Shiv", "Hari", "Sona", "Chand", "Bela", "Kesh", "Madhu", "Nand", "Dev", "Gopal", "Kusum",
  "Lal", "Moti", "Pipal", "Basant", "Kamal", "Indra", "Suraj", "Tara", "Amar", "Jai", "Kalyan", "Bhim",
  "Hira", "Asha", "Raj", "Ganga", "Neel", "Sundar", "Vijay", "Shanti", "Bodh", "Kanak", "Mani", "Prem",
];
const SUFFIXES = [
  "pur", "garh", "nagar", "ganj", "pura", "khera", "wadi", "gaon", "abad", "pali", "dih", "bagh",
  "tal", "kot", "sar", "patti", "nagla", "sarai", "chak", "bari",
];

export function placeName(rng: Random, used: Set<string>): string {
  for (let i = 0; i < 50; i++) {
    const name = rng.pick(PREFIXES) + rng.pick(SUFFIXES);
    if (!used.has(name)) {
      used.add(name);
      return name;
    }
  }
  // Practically unreachable (720 combinations); disambiguate with a word, not a number.
  const fallback = `${rng.pick(["Nava", "Purana", "Uttar", "Dakshin"])} ${rng.pick(PREFIXES)}${rng.pick(SUFFIXES)}`;
  used.add(fallback);
  return fallback;
}

export const CIRCLE_SEEDS = [
  { code: "UPE", name: "Uttar Pradesh (East)", districts: 5, weight: 1.25 },
  { code: "BR", name: "Bihar", districts: 5, weight: 1.15 },
  { code: "MP", name: "Madhya Pradesh", districts: 4, weight: 1.05 },
  { code: "RJ", name: "Rajasthan", districts: 4, weight: 0.95 },
  { code: "OD", name: "Odisha", districts: 4, weight: 0.9 },
  { code: "JH", name: "Jharkhand", districts: 3, weight: 0.8 },
  { code: "MH", name: "Maharashtra", districts: 4, weight: 1.0 },
  { code: "GJ", name: "Gujarat", districts: 3, weight: 0.85 },
] as const;
