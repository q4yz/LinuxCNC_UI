import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.css'
import App from './App.vue'
import './services/apiClient.js' // configures the generated OpenAPI client's BASE URL
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

// Boot the registry before mounting so the optional machine adapter
// can register the real module store before legacy shell components
// instantiate. A broken module is still isolated: the shell mounts
// from the fallback path.
registry.boot()
  .catch((err) => {
    // eslint-disable-next-line no-console
    console.error('[registry] boot failed:', err)
  })
  .finally(() => {
    app.mount('#app')
  })
