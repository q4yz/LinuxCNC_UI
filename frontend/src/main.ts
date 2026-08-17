import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router, { registerModuleRoutes } from './router'
import './style.css'
import App from './App.vue'
import './services/apiClient' // configures the generated OpenAPI client's BASE URL
import { registry } from './core/modules/registry'

// ECharts imports
import ECharts from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, TitleComponent, MarkLineComponent } from 'echarts/components'

use([
  CanvasRenderer,
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  MarkLineComponent
])

const app = createApp(App)
const pinia = createPinia()

app.component('v-chart', ECharts)
app.use(pinia)
app.use(router)

// Boot the registry before mounting so the module's ``onLoad``
// hooks run before any shell component instantiates. The boot is
// synchronous (the contract forbids ``onLoad`` returning a Promise)
// so we do not need a Promise chain here; ``boot()`` returns
// ``undefined``.
//
// Module-owned Vue Router routes are registered *after* boot
// completes — ``registerModuleRoutes`` walks ``registry.modules`` and
// adds one route per sidebar entry so a sidebar click on e.g. Camera
// resolves the same way a built-in click does. See
// ``router/index.js`` for the contract.
try {
  registry.boot()
  registerModuleRoutes(registry)
} catch (err) {
  // eslint-disable-next-line no-console
  console.error('[registry] boot failed:', err)
}
app.mount('#app')
