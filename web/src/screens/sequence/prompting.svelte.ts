// Which prompt of a sequence this page folded with "Later" (its run, step and kind):
// the dialog stays away for it, the Sequences view still asks in its dock.
class Prompting {
  dismissed: string | null = $state(null);
}

export const prompting = new Prompting();
