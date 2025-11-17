/**
 * Admin page route wrapper.
 *
 * The actual implementation is in features/admin/AdminPage.
 */

import { AdminPage as AdminFeature } from "../features/admin/AdminPage";

export function AdminPage() {
  return <AdminFeature />;
}
