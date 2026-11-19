/** UI only: permissions are recomputed and enforced by the backend. */
export type WorkCapabilities = {
  create: boolean;
  assign: boolean;
  crew: boolean;
  priority: boolean;
  start: boolean;
  complete: boolean;
  cancel: boolean;
  revalidate: boolean;
  hold: boolean;
  resume: boolean;
};
