# ADR-0010: Shared workspace context and scoped person navigation

Status: Proposed in PR #14 (2026-11-13).

## Problem

After PR #12 the UI has a permanent organization/personnel rail, but
each domain panel independently initializes a separate enterprise ID,
department selection and person ID. Users can view one enterprise in the
right rail and inadvertently edit another in the central panel. Person
selection is lost when switching between Personnel, Credentials,
Competence and Availability.

## Decision

Use `WorkspaceProvider` (React context) as a single source of truth for:

- current authenticated session;
- permitted/accessible enterprise collection (server-listed plus optional
  verified own Person linkage);
- selected enterprise UUID;
- loaded server-authorized organization units and selected unit UUID;
- selected Person UUID and its server-fetched visible profile;
- explicit refresh and error state.

Every existing functional module uses this same enterprise ID. The
Person-focused modules (Personnel, Competence, Credentials, Availability)
share one selected Person UUID. The Personnel filter and right rail share
one unit UUID; the WorkOrder create form aligns with the selected unit
while retaining local draft form state. This makes changing context
visible and consistent across navigation.

Data from the backend remains authoritative. The provider does not
create privileges, mint tokens, or cache personal data in localStorage.
Enterprise selection is restricted to the backend-returned allowed list;
unit selection to the loaded permitted units. Person details are
validated by the original scoped `GET /personnel/persons/{id}` endpoint.
A missing/inaccessible Person is cleared from shared state.

The context is **memory-only**: no account IDs, personal data or
organization scope stored in URLs or browser storage. The URL hash
continues to designate the active application module only; this keeps
links usable without accidentally exposing cross-user filter state.

An `auth-changed` event clears all selected context immediately.
A fresh session then loads the permitted enterprise set. Switching
enterprises resets the selected unit and Person. Switching a department
resets Person selection. A choice from the global people search or
right rail selects that Person and navigates to the Personnel page.
Backend Person visibility is still enforced on each request.

## UX

- Context breadcrumbs: `TWM / module / enterprise / unit / person`.
  Clicking enterprise or unit changes application navigation and clears
  more specific selection.
- Header search: 250 ms debounced person lookup using the authorized
  `GET /personnel/enterprises/{id}/persons?q=...&limit=20` API.
  Search is performed in the **currently selected enterprise** across
  department boundaries; results are server-scoped.
- Context rail enterprise selector, hierarchy and person list reflect the
  same state as the central domain module.
- Keyboard support: Escape closes results; Enter selects first result.

## Scope and non-goals

PR #14 deliberately avoids backend schema changes, new permissions,
full-text infrastructure, organization tree subtree evaluation on
the client, and persistent saved filters. The right rail's unit filter
still uses **direct department membership**. It does not implicitly
include descendants. WorkOrder assignment, permissions, credentials,
competence and safety hold logic remain unchanged.

## Acceptance

1. Selecting enterprise/unit in right rail updates Personnel filter
   and WorkOrder creation target.
2. Changing enterprise in a domain panel updates the rail and clears
   stale unit/person state.
3. Selecting a Person carries the focus across Personnel, Competence,
   Credentials and Availability when the Person is visible.
4. Global search finds a visible worker in another department, updates
   unit/person context and opens their profile.
5. Viewer only sees permitted workers and units. On logout/login as
   another user, the old context is erased before new data is displayed.
6. Existing PR #13 Playwright and backend CI remain green.

## Remaining items

A later improvement should add enterprise-wide work-order list filters
and explicit scope-aware selection for complex, multi-enterprise
assignments; handle >100 personnel pagination in all module dropdowns;
use debounced cursor pagination for >20 global search matches; and
implement accessible keyboard roving/arrow support and session expiry
handling while the app is open. These are not authorization bypasses.
