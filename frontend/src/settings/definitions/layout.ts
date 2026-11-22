// Page layouts: the panels of the Dashboard and the Running page.
import { DEFAULT_LAYOUTS } from "../../layout/pagePanels";
import { PageLayoutSetting } from "../types/PageLayoutSetting";

export const dashboardLayout = new PageLayoutSetting(
  "Page layout",
  "Dashboard",
  "layout.dashboard",
  "dashboard",
  DEFAULT_LAYOUTS.dashboard,
  {
    description: "The Dashboard's panels in one, two or three columns — the page uses the widest layout that is on and fits its width.",
    order: 0,
  },
);

export const runningLayout = new PageLayoutSetting(
  "Page layout",
  "Running",
  "layout.running",
  "running",
  DEFAULT_LAYOUTS.running,
  {
    description: "The Running page's panels in one, two or three columns — the page uses the widest layout that is on and fits its width.",
    order: 1,
  },
);
