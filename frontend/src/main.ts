import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import './style.css'
import App from './App.vue'
import './services/apiClient' // configures the generated OpenAPI client's BASE URL
// Eager: every UI setting registers itself (and shows in the Settings view) at start.
import './settings/definitions'
import { settingsRegistry } from './settings'
import { registerSW } from 'virtual:pwa-register'

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
  MarkLineComponent,
])

const app = createApp(App)
const pinia = createPinia()

app.component('v-chart', ECharts)
app.use(pinia)
app.use(router)

// One fetch of every stored UI setting for the session (system service —
// works with the machine offline). Settings show their defaults until then.
void settingsRegistry.fetchAll()

app.mount('#app')

if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  registerSW({ immediate: true })
}