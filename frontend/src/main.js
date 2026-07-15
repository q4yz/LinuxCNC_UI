import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.css'
import App from './App.vue'
// Side-effecting import: configures the generated OpenAPI client's BASE URL.
import './services/apiClient.js'
// Registry boot — must run before mount so App.vue can read registry
// state synchronously inside ``onMounted``. Boot is wrapped in a
// try/catch so a single broken module never prevents the app from
// rendering.
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

// Boot the registry. The promise resolves once every module's
// ``onLoad`` hook has run. Mount the app immediately so the user
// sees something even if a module's loader is slow.
app.mount('#app')
registry.boot().catch((err) => {
  // eslint-disable-next-line no-console
  console.error('[registry] boot failed:', err)
})
