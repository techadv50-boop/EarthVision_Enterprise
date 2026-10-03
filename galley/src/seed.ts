import type { Journal, Store } from "./types";
import { fetchIcon } from "./storage";

const IJIST = "/ijist";

const PARTNERS = [
  "partner-01.png",
  "partner-02.png",
  "partner-03.png",
  "partner-04.png",
  "partner-05.png",
  "partner-06.png",
  "partner-07.png",
  "partner-08.png",
  "partner-09.png",
  "partner-10.png",
  "partner-11.png",
  "partner-12.png",
  "partner-13.jpeg",
  "partner-14.png",
  "partner-15.png",
];

export async function seedStore(): Promise<Store> {
  const [openAccessIcon, top1, top2, ...partners] = await Promise.all([
    fetchIcon(`${IJIST}/open-access.jpeg`, "Open Access", 28),
    fetchIcon(`${IJIST}/top-1.jpeg`, "Research and Innovation Division", 58),
    fetchIcon(`${IJIST}/top-2.jpeg`, "Journal mark", 58),
    ...PARTNERS.map((name, index) => fetchIcon(`${IJIST}/${name}`, `Partner ${index + 1}`, 40)),
  ]);

  const ijist: Journal = {
    id: "ijist",
    name: "International Journal of Innovations in Science & Technology",
    abbreviation: "IJIST",
    issnP: "2618-1630",
    issnE: "2618-1630",
    topIcons: [top1, top2],
    partnerIcons: partners,
  };
  const ijasd: Journal = {
    id: "ijasd",
    name: "International Journal of Agriculture and Sustainable Development",
    abbreviation: "IJASD",
    issnP: "2618-1193",
    issnE: "2618-1193",
    topIcons: [],
    partnerIcons: [],
  };
  return { openAccessIcon, journals: [ijist, ijasd], galleys: [] };
}
