// Temperature module Pinia store. Owns the sensor / heater set, the
// rolling 30 s chart history, the unit toggle, and the per-entry
// visibility / colour maps.

import { defineStore, storeToRefs } from "pinia";
import { onScopeDispose, ref, watch, type Ref } from "vue";

import manifest from "./manifest";
import { createModuleSettings } from "../../core/modules/settings";
import { useBaseThreadStore } from "../../stores/baseThread";
import { TemperatureUnit } from "../../entities";
import type { ReadingSet } from "../../entities/temperature";

import type { CommandResult } from "../../entities";
import {HeaterControlRequest} from "../../entities/tools/Heater";
import TemperatureService from "../../facades/temperatureFacade";

// Chart is locked to a fixed 30 s window of 1 s ticks.
const WINDOW_SECONDS = 30;
const DEFAULT_POLL_MS = 1_000;

// Purple fallback color
const FALLBACK_COLOR = "#A855F7";
const DEFAULT_SENSOR_COLORS: Record<string, string> = {};

// `module_` prefix prevents collisions with legacy top-level stores.
const STORE_ID = `module_${manifest.id}`;

// Singleton settings client
let settingsClientSingleton: any = null;
function settingsClient() {
    if (!settingsClientSingleton) {
        settingsClientSingleton = createModuleSettings(manifest.id);
    }
    return settingsClientSingleton;
}

function clone<T>(value: T): T {
    if (typeof structuredClone === "function") {
        try {
            return structuredClone(value);
        } catch (_) {
            // Fall through to JSON path.
        }
    }
    return JSON.parse(JSON.stringify(value));
}

function roundTo(value: number, decimals: number): number {
    if (!Number.isFinite(value)) return 0;
    const factor = Math.pow(10, decimals);
    return Math.round(value * factor) / factor;
}

interface ChartSensorShape {
    actual: number;
    target?: number;
}

interface HistoryPoint {
    timestamp: number;
    time: string;
    sensors: Record<string, ChartSensorShape>;
}

function readingsToChartShape(readings: ReadingSet): Record<string, ChartSensorShape> {
    const out: Record<string, ChartSensorShape> = {};
    readings.forEach((r) => {
        out[r.id] = {
            actual: r.actualCelsius,
            ...(r.isControllable && { target: (r as any).targetCelsius }),
        };
    });
    return out;
}

export const useTemperatureStore = defineStore(
    STORE_ID,
    () => {
        // --- reactive state ------------------------------------------- //
        const sensors: Ref<Record<string, ChartSensorShape>> = ref({});
        const history: Ref<HistoryPoint[]> = ref([]);
        const windowMs = ref(WINDOW_SECONDS * 1000);
        const pollMs = ref(DEFAULT_POLL_MS);
        const unit = ref<TemperatureUnit>(TemperatureUnit.CELSIUS);
        const visibleSensors: Ref<Record<string, boolean>> = ref({});
        const sensorColors: Ref<Record<string, string>> = ref({ ...DEFAULT_SENSOR_COLORS });

        // --- non-reactive handles ------------------------------------- //
        let pollHandle: ReturnType<typeof setInterval> | null = null;
        let running = false;

        // --- helpers -------------------------------------------------- //

        function seedVisibility(readings: ReadingSet) {
            const next: Record<string, boolean> = {};
            readings.forEach((r) => {
                if (typeof visibleSensors.value[r.id] === "boolean") {
                    next[r.id] = visibleSensors.value[r.id];
                } else {
                    next[r.id] = true;
                }
            });
            visibleSensors.value = next;
        }

        function applySettings(settings: any) {
            if (!settings || typeof settings !== "object") return;
            if (settings.unit === TemperatureUnit.CELSIUS || settings.unit === TemperatureUnit.KELVIN) {
                unit.value = settings.unit;
            }
            if (settings.sensor_colors && typeof settings.sensor_colors === "object") {
                const next = { ...sensorColors.value };
                for (const [name, hex] of Object.entries(settings.sensor_colors)) {
                    if (typeof hex === "string" && /^#[0-9A-Fa-f]{6}$/.test(hex)) {
                        next[name] = hex;
                    }
                }
                sensorColors.value = next;
            }
        }

        function displayTemp(celsius: number | null | undefined): number {
            if (!Number.isFinite(celsius)) return 0;
            const val = celsius as number;
            const value = unit.value === TemperatureUnit.KELVIN ? val + 273.15 : val;
            return roundTo(value, 2);
        }

        async function setUnit(nextUnit: TemperatureUnit) {
            if (nextUnit !== TemperatureUnit.CELSIUS && nextUnit !== TemperatureUnit.KELVIN) return;
            if (unit.value === nextUnit) return;
            unit.value = nextUnit;
            try {
                await settingsClient().writeKey("unit", nextUnit);
            } catch (_) {
                // Best-effort
            }
        }

        function toggleSensorVisibility(name: string) {
            const current = visibleSensors.value[name];
            visibleSensors.value = {
                ...visibleSensors.value,
                [name]: !(current !== false),
            };
        }

        async function setSensorColor(name: string, hex: string) {
            if (!name || typeof name !== "string") return;
            if (typeof hex !== "string" || !/^#[0-9A-Fa-f]{6}$/.test(hex)) return;
            const next = { ...sensorColors.value, [name]: hex };
            sensorColors.value = next;
            try {
                await settingsClient().writeKey("sensor_colors", { ...next });
            } catch (_) {
                // Best-effort
            }
        }

        function colorFor(name: string): string {
            return sensorColors.value[name] || FALLBACK_COLOR;
        }

        function snapshot() {
            const now = Date.now();
            const date = new Date(now);
            const pad = (n: number) => n.toString().padStart(2, "0");
            const cents = Math.floor(date.getMilliseconds() / 10);
            const label = `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(
                date.getSeconds(),
            )}.${cents.toString().padStart(2, "0")}`;

            history.value.push({
                timestamp: now,
                time: label,
                sensors: clone(sensors.value || {}),
            });
            const cutoff = now - windowMs.value;
            history.value = history.value.filter((p) => p.timestamp >= cutoff);
        }

        function start() {
            if (running) return;
            running = true;
            snapshot();
            pollHandle = setInterval(snapshot, pollMs.value);
        }

        function stop() {
            running = false;
            if (pollHandle !== null) {
                clearInterval(pollHandle);
                pollHandle = null;
            }
        }

        function ingest(readings: ReadingSet) {
            if (!readings || typeof readings.forEach !== "function") return;
            sensors.value = readingsToChartShape(readings);
            seedVisibility(readings);
        }

        /**
         * Set the target temperature for a heater using the HeaterControlRequest DTO.
         */
        async function setTarget(request: HeaterControlRequest): Promise<CommandResult> {
            return await TemperatureService.setTarget(request);
        }

        async function refreshSettings() {
            try {
                const settings = await settingsClient().readAll();
                if (settings) applySettings(settings);
            } catch (_) {
                // Best-effort
            }
        }

        async function refreshSensors() {
            await useBaseThreadStore().refresh();
        }

        // --- base-thread consumer -------------------------------------- //
        const baseThread = useBaseThreadStore();
        ingest(baseThread.readings);

        const stopReadingsWatch = watch(
            () => baseThread.readings,
            (next) => {
                if (next && typeof next.forEach === "function") {
                    ingest(next);
                }
            },
            { immediate: true, deep: true },
        );

        refreshSettings();

        onScopeDispose(() => {
            stop();
            if (stopReadingsWatch) {
                stopReadingsWatch();
            }
        });

        return {
            sensors,
            history,
            windowMs,
            pollMs,
            unit,
            visibleSensors,
            sensorColors,
            ingest,
            snapshot,
            start,
            stop,
            refreshSettings,
            refreshSensors,
            displayTemp,
            setUnit,
            toggleSensorVisibility,
            setSensorColor,
            colorFor,
            setTarget,
        };
    },
);

export function useTemperatureRefs() {
    const store = useTemperatureStore();
    return { store, ...storeToRefs(store) };
}

export default useTemperatureStore;