import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import './style.css'
import App from './App.vue'
import './services/apiClient' // configures the generated OpenAPI client's BASE URL
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

app.mount('#app')

if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  registerSW({ immediate: true })
}