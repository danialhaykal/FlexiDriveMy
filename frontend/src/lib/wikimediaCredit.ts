// The Wikimedia Commons file page for a car photo hosted by Wikimedia, so the
// vehicle page can credit it ("Photo: Wikimedia Commons"): the file page names
// the author and the licence, which is the attribution those licences ask for.
// Worked out from the URL alone - nothing is keyed per car - so any photo an
// admin adds later from Commons gets its credit link automatically.
//
//   https://upload.wikimedia.org/wikipedia/commons/2/2f/BMW_G20.jpg
//   https://upload.wikimedia.org/wikipedia/commons/thumb/2/2f/BMW_G20.jpg/1280px-BMW_G20.jpg
//   https://thumb.wikimedia.org/wikipedia/commons/thumb/2/2f/BMW_G20.jpg/1280px-BMW_G20.jpg
//     -> https://commons.wikimedia.org/wiki/File:BMW_G20.jpg
//
// thumb.wikimedia.org is where the Commons API's own thumbnail URLs now point
// (same path as upload.wikimedia.org). Any other host, or a path that is not a
// Commons file, gives null - and no credit line is shown.

const WIKIMEDIA_HOSTS = new Set(["upload.wikimedia.org", "thumb.wikimedia.org"]);
const COMMONS_FILE_PATH = /^\/wikipedia\/commons\/(?:thumb\/)?[0-9a-f]\/[0-9a-f]{2}\/([^/]+\.[A-Za-z0-9]+)(?:\/.*)?$/;

export function wikimediaFilePageUrl(photoUrl: string | null | undefined): string | null {
  if (!photoUrl) return null;
  let url: URL;
  try {
    url = new URL(photoUrl);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" || !WIKIMEDIA_HOSTS.has(url.hostname)) return null;
  const match = COMMONS_FILE_PATH.exec(url.pathname);
  if (!match) return null;
  let fileName: string;
  try {
    fileName = decodeURIComponent(match[1]); // decoded once, as the file page names it
  } catch {
    return null;
  }
  return `https://commons.wikimedia.org/wiki/File:${fileName}`;
}
