import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.css'
import App from './App.vue'
// Side-effecting import: configures the generated OpenAPI client's BASE URL.
import './services/apiClient.js'

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
app.mount('#app')
