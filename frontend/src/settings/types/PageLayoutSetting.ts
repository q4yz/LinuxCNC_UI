import { defineAsyncComponent, type Component } from "vue";
import { BaseSetting, type SettingOptions } from "../core/BaseSetting";
import { normaliseLayout, type PageId, type PageLayout } from "../../layout/pagePanels";

// Lazy: the editor .vue is only loaded when the Settings view renders it.
const SettingPageLayout = defineAsyncComponent(() => import("../components/SettingPageLayout.vue"));

/** Which panels a page (Dashboard / Running) shows, per column, in order. */
export class PageLayoutSetting extends BaseSetting<PageLayout> {
  constructor(category: string, label: string, key: string, page: PageId, defaultValue: PageLayout,
              options: SettingOptions = {}) {
    super(category, label, key, defaultValue, { ...options, config: { page } });
  }

  get type(): string {
    return "page-layout";
  }

  get component(): Component {
    return SettingPageLayout;
  }

  get page(): PageId {
    return this.config.page as PageId;
  }

  validate(raw: unknown): PageLayout | undefined {
    return normaliseLayout(raw, this.defaultValue);
  }
}
