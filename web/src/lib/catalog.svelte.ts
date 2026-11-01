// Catalog objects by id, asked for once and shared, for targets the server keeps
// by id: tonight's target (`plan.target`) is shown in the viewer's language, not
// in the language of whoever chose it.

import { getTarget } from "./api";
import { objectName } from "./targets";
import type { CatalogObject, PlannedTarget } from "./types";

class CatalogObjects {
  #known: Record<string, CatalogObject> = $state({});
  #asked = new Set<string>();

  // The object, once it arrived; asks for it the first time.
  get(id: string): CatalogObject | null {
    if (!this.#asked.has(id)) {
      this.#asked.add(id);
      getTarget(id)
        .then((object) => (this.#known[id] = object))
        .catch(() => this.#asked.delete(id));
    }
    return this.#known[id] ?? null;
  }
}

export const catalogObjects = new CatalogObjects();

// "M 42 · Orion Nebula" in this language; the stored name until the object arrives,
// or for a target that is not from the catalog.
export function plannedName(target: PlannedTarget, locale: string): string {
  const object = target.id ? catalogObjects.get(target.id) : null;
  return object ? objectName(object, locale) : target.name;
}
