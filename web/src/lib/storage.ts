// Frame storage as the server lays it out (ADR 0013).

// A name as the server cleans it for a folder on any drive, FAT included
// (nocs.storage.layout.clean): letters and digits of any script and -_.+ are
// kept, spaces become _, anything else is dropped.
export function folderName(name: string): string {
  return name
    .normalize("NFC")
    .trim()
    .replace(/\s/g, "_")
    .replace(/[^\p{L}\p{N}\-_.+]/gu, "")
    .replace(/_{2,}/g, "_")
    .replace(/^[._]+|[._]+$/g, "")
    .slice(0, 64)
    .replace(/[._]+$/, "");
}
